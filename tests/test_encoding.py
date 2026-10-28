import gzip

import pytest

from collector.encoding import decode_price_file

SAMPLE = "<Root><ItemName>חלב 3% 1 ל</ItemName></Root>"


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(SAMPLE.encode("utf-8"), id="utf-8"),
        pytest.param(b"\xef\xbb\xbf" + SAMPLE.encode("utf-8"), id="utf-8 with BOM (Shufersal)"),
        pytest.param(SAMPLE.encode("utf-16"), id="utf-16 with BOM"),
        pytest.param(SAMPLE.encode("utf-16-le"), id="utf-16-le without BOM (Rami Levy stores)"),
        pytest.param(gzip.compress(b"\xef\xbb\xbf" + SAMPLE.encode("utf-8")), id="gzip"),
    ],
)
def test_decodes_every_encoding_chains_use(raw):
    assert decode_price_file(raw) == SAMPLE


def test_invalid_bytes_raise_instead_of_guessing():
    with pytest.raises(UnicodeDecodeError):
        decode_price_file(b"<Root>\xff\xfe\xfa</Root>")
