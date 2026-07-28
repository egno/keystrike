import os
import time

# Crockford base32 alphabet (ULID standard)
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = ["0"] * length
    for i in range(length - 1, -1, -1):
        chars[i] = _ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)


class UlidGenerator:
    """Generate ULIDs (48-bit ms timestamp + 80-bit randomness), stdlib only."""

    def new_id(self) -> str:
        ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
        rand = int.from_bytes(os.urandom(10), "big")
        return _encode(ts_ms, 10) + _encode(rand, 16)
