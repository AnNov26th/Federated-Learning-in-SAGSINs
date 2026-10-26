import json
import os
import tempfile
from pathlib import Path


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, ensure_ascii=False, allow_nan=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path):
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)
