class CoingeckoRequestError(Exception):
    pass


class Coingecko404(CoingeckoRequestError):
    pass


class CoingeckoRateLimitError(CoingeckoRequestError):
    """
    {
    "status": {
        "error_code": 429,
        "error_message": "You've exceeded the Rate Limit. Please visit https://www.coingecko.com/en/api/pricing to subscribe to our API plans for higher rate limits."
        }
    }
    """
