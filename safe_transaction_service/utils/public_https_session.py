# SPDX-License-Identifier: FSL-1.1-MIT
import socket
from http.cookiejar import DefaultCookiePolicy
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.exceptions import (
    ConnectTimeoutError,
    NameResolutionError,
    NewConnectionError,
)
from urllib3.util.connection import allowed_gai_family, create_connection

NON_PUBLIC_NETWORKS_MISSING_FROM_IS_GLOBAL = tuple(
    ip_network(network)
    for network in (
        "192.0.0.0/24",
        "192.88.99.0/24",
        "::/96",
        "::ffff:0:0/96",
        "::ffff:0:0:0/96",
        "64:ff9b::/96",
        "5f00::/16",
        "fec0::/10",
    )
)


class NonPublicAddressError(Exception):
    pass


def is_public_ip_address(address: IPv4Address | IPv6Address) -> bool:
    return (
        address.is_global
        and not address.is_multicast
        and not any(
            address in network for network in NON_PUBLIC_NETWORKS_MISSING_FROM_IS_GLOBAL
        )
    )


class PublicAddressHTTPSConnection(HTTPSConnection):
    """
    Connects only to addresses that passed the check. Resolving the host again
    to connect would let a DNS answer that changes after the check (DNS
    rebinding) reach an internal address.
    """

    def _resolve_public_ip_addresses(self) -> list[IPv4Address | IPv6Address]:
        try:
            address_infos = socket.getaddrinfo(
                self._dns_host, self.port, allowed_gai_family(), socket.SOCK_STREAM
            )
        except socket.gaierror as e:
            raise NameResolutionError(self.host, self, e) from e

        resolved_ip_addresses = [
            ip_address(socket_address[0]) for *_, socket_address in address_infos
        ]
        for resolved_ip_address in resolved_ip_addresses:
            if not is_public_ip_address(resolved_ip_address):
                raise NonPublicAddressError(
                    f"{self._dns_host} resolves to {resolved_ip_address}, which is not a public address"
                )
        return resolved_ip_addresses

    def _new_conn(self) -> socket.socket:
        connect_error: OSError | None = None
        for public_ip_address in self._resolve_public_ip_addresses():
            try:
                return create_connection(
                    (str(public_ip_address), self.port),
                    self.timeout,
                    source_address=self.source_address,
                    socket_options=self.socket_options,
                )
            except OSError as e:
                connect_error = e

        if isinstance(connect_error, TimeoutError):
            raise ConnectTimeoutError(
                self,
                f"Connection to {self.host} timed out. (connect timeout={self.timeout})",
            ) from connect_error
        raise NewConnectionError(
            self,
            f"Failed to establish a new connection: {connect_error}",
        ) from connect_error


class PublicAddressHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = PublicAddressHTTPSConnection


class PublicAddressHTTPSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs) -> None:
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {
            "https": PublicAddressHTTPSConnectionPool
        }

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        raise NonPublicAddressError(
            f"Proxy {proxy} is not allowed, connections through it skip the address check"
        )


def build_public_https_session(max_redirects: int) -> requests.Session:
    """
    :param max_redirects: every redirect target goes through the same check
    :return: session that raises :class:`NonPublicAddressError` when a request
        or one of its redirects targets an address that is not public, and
        :class:`requests.exceptions.InvalidSchema` when it is not ``https``
    """
    session = requests.Session()
    # Proxies from env vars would make every request fail, as the adapter rejects them
    session.trust_env = False
    # The session is long lived and the hosts are chosen by whoever controls the URL
    session.cookies.set_policy(DefaultCookiePolicy(allowed_domains=()))
    session.max_redirects = max_redirects
    session.adapters.clear()
    session.mount("https://", PublicAddressHTTPSAdapter())
    return session
