from typing import Any, Dict, Optional


def clean_receipt_log(receipt_log: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Clean receipt log and make them JSON compliant
    :param receipt_log:
    :return:
    """
    parsed_log = {
        "address": receipt_log["address"],
        "data": receipt_log["data"],
        "topics": [topic.hex() for topic in receipt_log["topics"]],
    }
    return parsed_log
