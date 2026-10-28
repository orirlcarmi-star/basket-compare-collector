from collector.sources.shufersal import FileLink, list_url, parse_file_links

# Trimmed from a real row of prices.shufersal.co.il (signature shortened).
ROW = (
    '<tr><td><a href="https://pricesprodpublic.blob.core.windows.net/pricefull/'
    "PriceFull7290027600007-001-413-20261027-030000.gz?sv=2014-02-14&amp;sr=b&amp;"
    'sig=abc%3D&amp;se=2026-10-27T19%3A15%3A45Z&amp;sp=r" target="_blank">לחץ להורדה</a></td>'
    "<td>10/27/2026 3:00:00 AM</td><td>619.64 KB</td><td>GZ</td><td>pricefull</td>"
    "<td>413 - שופרסל ONLINE</td></tr>"
)


def test_parses_name_and_unescapes_signed_url():
    assert parse_file_links(ROW) == [
        FileLink(
            name="PriceFull7290027600007-001-413-20261027-030000",
            url=(
                "https://pricesprodpublic.blob.core.windows.net/pricefull/"
                "PriceFull7290027600007-001-413-20261027-030000.gz?sv=2014-02-14&sr=b&"
                "sig=abc%3D&se=2026-10-27T19%3A15%3A45Z&sp=r"
            ),
        )
    ]


def test_ignores_links_that_are_not_price_files():
    page = '<a href="?sort=Time&amp;sortdir=ASC">זמן</a>' + ROW + '<a href="/about">אודות</a>'
    assert [link.name for link in parse_file_links(page)] == [
        "PriceFull7290027600007-001-413-20261027-030000"
    ]


def test_list_url():
    assert list_url(2, 413) == (
        "https://prices.shufersal.co.il/FileObject/UpdateCategory?catID=2&storeId=413"
    )
