"""Turn the raw bytes of a chain price file into text.

Chains publish the same XML schema but not the same encoding: Shufersal uses
UTF-8 with a byte-order mark, Rami Levy's store list is UTF-16, and some files
arrive gzip-compressed. Everything downstream works on plain text.
"""

import gzip

_GZIP_MAGIC = b"\x1f\x8b"
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_UTF8_BOM = b"\xef\xbb\xbf"


def decode_price_file(raw: bytes) -> str:
    """Decompress if needed and decode to text, without a leading byte-order mark."""
    if raw.startswith(_GZIP_MAGIC):
        raw = gzip.decompress(raw)

    if raw.startswith(_UTF16_BOMS):
        return raw.decode("utf-16")
    if raw.startswith(_UTF8_BOM):
        return raw[len(_UTF8_BOM) :].decode("utf-8")
    if _looks_like_utf16_without_bom(raw):
        return raw.decode("utf-16-le")
    return raw.decode("utf-8")


def _looks_like_utf16_without_bom(raw: bytes) -> bool:
    # XML starts with "<"; in UTF-16-LE that is b"<\x00".
    return raw[:2] == b"<\x00"
