from __future__ import annotations

import secrets
import time
import uuid

_LAST_MS = -1
_SEQUENCE = 0


def generate_uuid7() -> uuid.UUID:
    global _LAST_MS, _SEQUENCE

    now_ms = time.time_ns() // 1_000_000
    if now_ms <= _LAST_MS:
        now_ms = _LAST_MS
        _SEQUENCE = (_SEQUENCE + 1) & 0xFFF
    else:
        _LAST_MS = now_ms
        _SEQUENCE = secrets.randbits(12)

    random_tail = secrets.randbits(62)
    value = 0
    value |= (now_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= (_SEQUENCE & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_tail
    return uuid.UUID(int=value)
