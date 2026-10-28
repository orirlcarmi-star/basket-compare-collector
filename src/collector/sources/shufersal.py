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
CATEGORY_PRICE = 1
CATEGORY_PRICE_FULL = 2
CATEGORY_PROMO = 3
CATEGORY_PROMO_FULL = 4
CATEGORY_STORES = 5

# PriceFull7290027600007-001-413-20261027-030000.gz, Stores7290027600007-000-20261028-020.gz
_FILE_LINK = re.compile(
    r'href="(?P<url>https://pricesprodpublic\.blob\.core\.windows\.net/[^"]+/'
    r'(?P<name>[A-Za-z]+\d{13}(?:-\d+)+)\.gz[^"]*)"'
)
_PAGE_NUMBER = re.compile(r"[?&;]page=(\d+)")  # ";" because the HTML writes &amp;page=
_MAX_PAGES = 200  # safety stop; Shufersal had 22 pages of full price files


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


def last_page(page_html: str) -> int:
    """Highest page number the pager links to (1 when there is no pager)."""
    return max((int(n) for n in _PAGE_NUMBER.findall(page_html)), default=1)


def list_url(category: int, store_id: int, page: int = 1) -> str:
    url = f"{BASE_URL}/FileObject/UpdateCategory?catID={category}&storeId={store_id}"
    return url if page == 1 else f"{url}&page={page}"


def list_all(category: int, store_id: int = 0) -> list[FileLink]:
    """Every file link of a category across all pages (store_id 0 = all stores)."""
    links: list[FileLink] = []
    first = fetch(list_url(category, store_id)).decode("utf-8", errors="replace")
    links += parse_file_links(first)
    for page in range(2, min(last_page(first), _MAX_PAGES) + 1):
        html_page = fetch(list_url(category, store_id, page)).decode("utf-8", errors="replace")
        links += parse_file_links(html_page)
    return links


def latest_per_store(links: list[FileLink]) -> dict[str, FileLink]:
    """Keep the newest file for each store (names end in -<store>-<date>-<time>)."""
    latest: dict[str, FileLink] = {}
    for link in links:
        parts = link.name.split("-")
        if len(parts) < 5:
            continue  # not a per-store file (e.g. the stores list)
        store, stamp = parts[2], parts[3] + parts[4]
        current = latest.get(store)
        if current is None or stamp > "".join(current.name.split("-")[3:5]):
            latest[store] = link
    return latest


def fetch(url: str, timeout: float = 60) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https hosts only
        return response.read()
