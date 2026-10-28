"""Write parsed records as JSON files for the next stage (the ready-made files builder).

Decimals become strings (never floats) so prices survive the round trip exactly.
"""

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def to_json(record: Any) -> str:
    if not is_dataclass(record) or isinstance(record, type):
        raise TypeError(f"expected a dataclass instance, got {type(record).__name__}")
    return json.dumps(_plain(asdict(record)), ensure_ascii=False, separators=(",", ":"))


def write_record(path: Path, record: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(record), encoding="utf-8")
