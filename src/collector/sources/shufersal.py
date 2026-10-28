"""Shufersal's public price-transparency site (prices.shufersal.co.il).

The site lists files in an HTML table. Each row links to a gzip file on public
cloud storage through a signed URL that expires within hours, so a file must be
downloaded soon after its link is read.
"""

import html
import re
from dataclasses import dataclass
from urllib.request import Request, urlopen

BASE_URL = "https://prices.shufersal.co.il"
USER_AGENT = (
    "basket-compare-collector (+https://github.com/orirlcarmi-star/basket-compare-collector)"
)

# Category numbers used by the site's filter.
CATEGORY_PRICE_FULL = 2

_FILE_LINK = re.compile(
    r'href="(?P<url>https://pricesprodpublic\.blob\.core\.windows\.net/[^"]+/'
    r'(?P<name>[A-Za-z]+\d{13}-\d{3}-\d{3}-\d{8}-\d{6})\.gz[^"]*)"'
)


@dataclass(frozen=True)
class FileLink:
    name: str
    url: str


def parse_file_links(page_html: str) -> list[FileLink]:
    """Extract the download links from one page of the file table."""
    return [
        FileLink(name=m["name"], url=html.unescape(m["url"]))
        for m in _FILE_LINK.finditer(page_html)
    ]


def list_url(category: int, store_id: int) -> str:
    return f"{BASE_URL}/FileObject/UpdateCategory?catID={category}&storeId={store_id}"


def fetch(url: str, timeout: float = 60) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https hosts only
        return response.read()
