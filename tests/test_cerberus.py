import pytest

from collector.sources.cerberus import RemoteFile, csrf_token, parse_file_list


def test_csrf_token_from_meta_or_input():
    assert csrf_token('<meta name="csrftoken" content="abc123">') == "abc123"
    assert csrf_token('<input type="hidden" name="csrftoken" value="xyz">') == "xyz"
    with pytest.raises(ValueError):
        csrf_token("<html></html>")


def test_parse_file_list_keeps_files_only():
    payload = (
        '{"aaData":[{"fname":"PriceFull7290058140886-001-001-20261027-070006.gz",'
        '"ftype":"file","size":26624},{"fname":"archive","ftype":"folder"}]}'
    )
    assert parse_file_list(payload) == [
        RemoteFile(name="PriceFull7290058140886-001-001-20261027-070006.gz", size=26624)
    ]
