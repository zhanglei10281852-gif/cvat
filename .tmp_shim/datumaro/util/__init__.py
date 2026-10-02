import json

import attrs
import numpy as np


def _default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "to_json"):
        return value.to_json()
    if attrs.has(type(value)):
        return attrs.asdict(value)
    raise TypeError(f"Unsupported type: {type(value)!r}")


def dump_json(data, *args, **kwargs):
    kwargs.setdefault("default", _default)
    return json.dumps(data, **kwargs).encode("utf-8")


def parse_json(path_or_file, *args, **kwargs):
    if isinstance(path_or_file, (bytes, bytearray)):
        path_or_file = path_or_file.decode("utf-8")

    return json.loads(path_or_file)


def to_snake_case(value):
    return value
