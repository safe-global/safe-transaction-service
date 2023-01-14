class CoingeckoRequestError(Exception):
    pass


class Coingecko404(CoingeckoRequestError):
    pass


class CannotGetPrice(CoingeckoRequestError):
    pass
