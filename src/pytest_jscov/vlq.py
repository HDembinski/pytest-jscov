"""VLQ decoding helpers for sourcemap parsing."""

_B64 = {
    c: i
    for i, c in enumerate(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    )
}


def vlq_decode_one(s: str, pos: int) -> tuple[int, int]:
    """Decode one VLQ integer starting at *pos* in *s*."""
    value = shift = 0
    while True:
        digit = _B64[s[pos]]
        pos += 1
        value |= (digit & 0x1F) << shift
        shift += 5
        if not (digit & 0x20):
            break
    return (-(value >> 1) if value & 1 else value >> 1), pos


def vlq_decode_segment(s: str) -> list[int]:
    """Decode all VLQ integers in one mapping segment."""
    values, pos = [], 0
    while pos < len(s):
        value, pos = vlq_decode_one(s, pos)
        values.append(value)
    return values
