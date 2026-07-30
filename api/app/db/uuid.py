from __future__ import annotations

import secrets
import threading
import time
import uuid

_LAST_MS = -1
_SEQUENCE = 0
_SEQUENCE_MAX = (1 << 12) - 1
_LOCK = threading.Lock()


def _current_ms() -> int:
    return time.time_ns() // 1_000_000


def _wait_for_next_ms(previous_ms: int) -> int:
    current_ms = _current_ms()
    while current_ms <= previous_ms:
        time.sleep(0)
        current_ms = _current_ms()
    return current_ms


def generate_uuid7() -> uuid.UUID:
    global _LAST_MS, _SEQUENCE

    with _LOCK:
        now_ms = _current_ms()
        if now_ms <= _LAST_MS:
            now_ms = _LAST_MS
            if _SEQUENCE >= _SEQUENCE_MAX:
                # The 12-bit monotonic sequence is exhausted for this millisecond;
                # wait for the next clock millisecond instead of wrapping.
                now_ms = _wait_for_next_ms(_LAST_MS)
                _LAST_MS = now_ms
                _SEQUENCE = secrets.randbits(12)
            else:
                _SEQUENCE += 1
        else:
            _LAST_MS = now_ms
            _SEQUENCE = secrets.randbits(12)

        random_tail = secrets.randbits(62)
        value = 0
        value |= (now_ms & ((1 << 48) - 1)) << 80
        value |= 0x7 << 76
        value |= (_SEQUENCE & _SEQUENCE_MAX) << 64
        value |= 0b10 << 62
        value |= random_tail
        return uuid.UUID(int=value)
