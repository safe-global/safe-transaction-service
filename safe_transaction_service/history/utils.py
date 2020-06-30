import logging
from typing import Any, Dict, List, Optional

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


def chunks(elements: List[Any], n: int):
    """
    :param elements: List
    :param n: Number of elements per chunk
    :return: Yield successive n-sized chunks from l
    """
    for i in range(0, len(elements), n):
        yield elements[i:i + n]


def clean_receipt_log(receipt_logs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Clean receipt logs and make them JSON compliant
    :param receipt_logs:
    :return:
    """
    parsed_logs = {'data': receipt_logs['data'],
                   'topics': [topic.hex() for topic in receipt_logs['topics']]}
    return parsed_logs
