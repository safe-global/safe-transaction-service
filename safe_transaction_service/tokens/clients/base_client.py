import requests


class BaseHTTPClient:
    def __init__(self, request_timeout: int = 10):
        self.http_session = self._prepare_http_session()
        self.request_timeout = request_timeout

    def _prepare_http_session(self) -> requests.Session:
        """
        Prepare http session with custom pooling. See:
        https://urllib3.readthedocs.io/en/stable/advanced-usage.html
        https://docs.python-requests.org/en/v1.2.3/api/#requests.adapters.HTTPAdapter
        https://web3py.readthedocs.io/en/stable/providers.html#httpprovider
        """
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=100,  # Number of concurrent connections
            pool_block=False,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
