# SPDX-License-Identifier: FSL-1.1-MIT
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from unittest import mock

from django.test import SimpleTestCase

import requests
import trustme

from .. import public_https_session
from ..public_https_session import (
    NonPublicAddressError,
    build_public_https_session,
    is_public_ip_address,
)


def build_address_info(address: str) -> tuple:
    if ":" in address:
        return socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0)
    return socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)


class RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", self.server.redirect_location)
        self.send_header("Set-Cookie", "session=attacker; Path=/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        pass


class TestIsPublicIpAddress(SimpleTestCase):
    def test_public_ip_addresses(self):
        """Addresses reachable on the public internet are allowed."""
        for address in (
            "1.1.1.1",
            "8.8.8.8",
            "93.184.215.14",
            "2001:4860:4860::8888",
            "2606:4700:4700::1111",
        ):
            with self.subTest(address=address):
                self.assertTrue(is_public_ip_address(ip_address(address)))

    def test_non_public_ip_addresses(self):
        """One sample address of every blocked range is rejected."""
        for address in (
            "0.1.2.3",  # 0.0.0.0/8 this network
            "10.1.2.3",  # 10.0.0.0/8 private
            "100.64.1.2",  # 100.64.0.0/10 CGNAT
            "127.0.0.1",  # 127.0.0.0/8 loopback
            "169.254.169.254",  # 169.254.0.0/16 link local, cloud metadata
            "172.16.1.2",  # 172.16.0.0/12 private
            "192.0.0.9",  # 192.0.0.0/24 IETF protocol assignments
            "192.0.2.1",  # 192.0.2.0/24 documentation
            "192.88.99.1",  # 192.88.99.0/24 6to4 relay anycast
            "192.168.1.2",  # 192.168.0.0/16 private
            "198.18.0.1",  # 198.18.0.0/15 benchmarking
            "198.51.100.1",  # 198.51.100.0/24 documentation
            "203.0.113.1",  # 203.0.113.0/24 documentation
            "224.0.0.1",  # 224.0.0.0/4 multicast
            "233.252.0.1",  # 233.252.0.0/24 multicast documentation
            "240.0.0.1",  # 240.0.0.0/4 reserved
            "255.255.255.255",  # broadcast
            "::",  # unspecified
            "::1",  # loopback
            "::8.8.8.8",  # ::/96 IPv4-compatible
            "::ffff:8.8.8.8",  # ::ffff:0:0/96 IPv4-mapped
            "::ffff:169.254.169.254",  # ::ffff:0:0/96 IPv4-mapped
            "::ffff:0:a9fe:a9fe",  # ::ffff:0:0:0/96 IPv4-translated
            "64:ff9b::a9fe:a9fe",  # 64:ff9b::/96 NAT64
            "64:ff9b:1::1",  # 64:ff9b:1::/48 local NAT64
            "100::1",  # 100::/64 discard only
            "2001::1",  # 2001::/32 Teredo
            "2001:2::1",  # 2001:2::/48 benchmarking
            "2001:db8::1",  # 2001:db8::/32 documentation
            "2002:a9fe:a9fe::1",  # 2002::/16 6to4
            "3fff::1",  # 3fff::/20 documentation
            "5f00::1",  # 5f00::/16 SRv6 SIDs
            "fc00::1",  # fc00::/7 unique local
            "fd00:ec2::254",  # fc00::/7 unique local, AWS metadata
            "fe80::1",  # fe80::/10 link local
            "fec0::1",  # fec0::/10 site local
            "ff02::1",  # ff00::/8 multicast
            "ff0e::1",  # ff00::/8 multicast, global scope
        ):
            with self.subTest(address=address):
                self.assertFalse(is_public_ip_address(ip_address(address)))


class TestPublicHttpsSession(SimpleTestCase):
    def setUp(self):
        self.session = build_public_https_session(max_redirects=3)

    def build_listening_socket(self, family: int, address: str) -> socket.socket:
        listening_socket = socket.socket(family, socket.SOCK_STREAM)
        listening_socket.bind((address, 0))
        listening_socket.listen()
        listening_socket.setblocking(False)
        self.addCleanup(listening_socket.close)
        return listening_socket

    def assert_no_connection_received(self, listening_socket: socket.socket):
        with self.assertRaises(BlockingIOError):
            listening_socket.accept()

    def mock_dns_answer(self, *ip_addresses: str) -> mock.MagicMock:
        return self.enterContext(
            mock.patch.object(
                public_https_session.socket,
                "getaddrinfo",
                return_value=[build_address_info(address) for address in ip_addresses],
            )
        )

    def mock_create_connection(self, **mock_kwargs) -> mock.MagicMock:
        return self.enterContext(
            mock.patch.object(public_https_session, "create_connection", **mock_kwargs)
        )

    def test_local_targets_are_not_reached(self):
        """Loopback targets fail before connecting, by IP and by hostname."""
        listening_socket = self.build_listening_socket(socket.AF_INET, "127.0.0.1")
        port = listening_socket.getsockname()[1]
        for url in (
            f"https://127.0.0.1:{port}/",
            f"https://localhost:{port}/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(NonPublicAddressError):
                    self.session.get(url, timeout=5)
        self.assert_no_connection_received(listening_socket)

    def test_ipv6_loopback_is_not_reached(self):
        """IPv6 literal hosts are checked too."""
        try:
            listening_socket = self.build_listening_socket(socket.AF_INET6, "::1")
        except OSError:
            self.skipTest("IPv6 loopback is not available")
        port = listening_socket.getsockname()[1]
        with self.assertRaises(NonPublicAddressError):
            self.session.get(f"https://[::1]:{port}/", timeout=5)
        self.assert_no_connection_received(listening_socket)

    def test_cloud_metadata_address_is_rejected(self):
        """The cloud metadata endpoint is rejected without connecting."""
        create_connection_mock = self.mock_create_connection()
        for url in (
            "https://169.254.169.254/latest/meta-data/",
            "https://[fd00:ec2::254]/latest/meta-data/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(NonPublicAddressError):
                    self.session.get(url, timeout=5)
        create_connection_mock.assert_not_called()

    def test_hostname_with_any_non_public_address_is_rejected(self):
        """A hostname is rejected if one of its records is not public, even if others are."""
        self.mock_dns_answer("93.184.215.14", "10.0.0.1")
        create_connection_mock = self.mock_create_connection()
        with self.assertRaisesMessage(
            NonPublicAddressError,
            "metadata.example.com resolves to 10.0.0.1, which is not a public address",
        ):
            self.session.get("https://metadata.example.com/", timeout=5)
        create_connection_mock.assert_not_called()

    def test_connects_to_checked_address(self):
        """The connection goes to the address that was checked, the hostname is resolved only once."""
        getaddrinfo_mock = self.mock_dns_answer(
            "93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"
        )
        create_connection_mock = self.mock_create_connection(
            side_effect=ConnectionRefusedError
        )
        with self.assertRaises(requests.ConnectionError):
            self.session.get("https://metadata.example.com/", timeout=5)
        getaddrinfo_mock.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in create_connection_mock.call_args_list],
            [
                ("93.184.215.14", 443),
                ("2606:2800:21f:cb07:6820:80da:af6b:8b2c", 443),
            ],
        )

    def test_connect_timeout(self):
        """A connect timeout keeps being reported as a timeout."""
        self.mock_dns_answer("93.184.215.14")
        self.mock_create_connection(side_effect=TimeoutError)
        with self.assertRaises(requests.ConnectTimeout):
            self.session.get("https://metadata.example.com/", timeout=5)

    def test_http_is_rejected(self):
        """Plain http URLs fail without connecting."""
        create_connection_mock = self.mock_create_connection()
        with self.assertRaises(requests.exceptions.InvalidSchema):
            self.session.get("http://93.184.215.14/", timeout=5)
        create_connection_mock.assert_not_called()

    def start_redirect_server(self, redirect_location: str) -> int:
        """
        Starts an https server on loopback that redirects every request, makes
        the session trust its certificate and allows loopback for the test so
        the server can be reached.
        """
        certificate_authority = trustme.CA()
        server_ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        certificate_authority.issue_cert("127.0.0.1").configure_cert(server_ssl_context)
        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        server.socket = server_ssl_context.wrap_socket(server.socket, server_side=True)
        server.redirect_location = redirect_location
        threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        self.session.verify = self.enterContext(
            certificate_authority.cert_pem.tempfile()
        )
        loopback_address = ip_address("127.0.0.1")
        self.enterContext(
            mock.patch.object(
                public_https_session,
                "is_public_ip_address",
                side_effect=lambda address: address == loopback_address,
            )
        )
        return server.server_address[1]

    def test_redirect_to_non_public_address_is_rejected(self):
        """Every redirect target goes through the same check."""
        port = self.start_redirect_server("https://169.254.169.254/latest/meta-data/")
        create_connection_mock = self.mock_create_connection(
            wraps=public_https_session.create_connection
        )
        with self.assertRaisesMessage(
            NonPublicAddressError,
            "resolves to 169.254.169.254, which is not a public address",
        ):
            self.session.get(f"https://127.0.0.1:{port}/", timeout=5)
        self.assertEqual(
            [call.args[0] for call in create_connection_mock.call_args_list],
            [("127.0.0.1", port)],
        )

    def test_redirect_to_http_is_rejected(self):
        """A redirect cannot downgrade to plain http."""
        port = self.start_redirect_server("http://93.184.215.14/")
        create_connection_mock = self.mock_create_connection(
            wraps=public_https_session.create_connection
        )
        with self.assertRaises(requests.exceptions.InvalidSchema):
            self.session.get(f"https://127.0.0.1:{port}/", timeout=5)
        self.assertEqual(
            [call.args[0] for call in create_connection_mock.call_args_list],
            [("127.0.0.1", port)],
        )

    def test_redirect_limit(self):
        """Redirects stop after the configured number of hops."""
        port = self.start_redirect_server("/again")
        with self.assertRaises(requests.TooManyRedirects):
            self.session.get(f"https://127.0.0.1:{port}/", timeout=5)

    def test_cookies_are_not_stored(self):
        """The session is shared, so cookies from one target never reach the next request."""
        port = self.start_redirect_server("/again")
        for _ in range(2):
            with self.assertRaises(requests.TooManyRedirects) as context:
                self.session.get(f"https://127.0.0.1:{port}/", timeout=5)
        self.assertEqual(len(self.session.cookies), 0)
        first_request_of_second_get = context.exception.response.history[0].request
        self.assertNotIn("Cookie", first_request_of_second_get.headers)

    def test_proxies_are_rejected(self):
        """Proxies would skip the check, from env vars they are ignored and per request they fail."""
        with mock.patch.dict(
            "os.environ",
            {"HTTPS_PROXY": "http://93.184.215.14:3128", "NO_PROXY": ""},
        ):
            with self.assertRaisesMessage(
                NonPublicAddressError, "resolves to 127.0.0.1"
            ):
                self.session.get("https://127.0.0.1:1/", timeout=5)

        with self.assertRaisesMessage(NonPublicAddressError, "Proxy"):
            self.session.get(
                "https://93.184.215.14/",
                proxies={"https": "http://93.184.215.14:3128"},
                timeout=5,
            )
