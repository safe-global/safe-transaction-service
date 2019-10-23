import logging
from typing import Any, List

from gunicorn import glogging


class IgnoreCheckUrl(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        return not ('GET /check/' in message and '200' in message)


class CustomGunicornLogger(glogging.Logger):
    def setup(self, cfg):
        super().setup(cfg)

        # Add filters to Gunicorn logger
        logger = logging.getLogger("gunicorn.access")
        logger.addFilter(IgnoreCheckUrl())


def chunks(l: List[Any], n: int):
    """
    :param l: List
    :param n: Number of elements per chunk
    :return: Yield successive n-sized chunks from l
    """
    for i in range(0, len(l), n):
        yield l[i:i + n]
