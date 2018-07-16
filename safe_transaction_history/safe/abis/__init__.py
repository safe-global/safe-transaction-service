import json
import os


def load_contract_interface(file_name):
    return _load_json_file(_abi_file_path(file_name))


def _abi_file_path(file):
    return os.path.abspath(os.path.join(os.path.dirname(__file__), file))


def _load_json_file(path):
    with open(path) as f:
        return json.load(f)