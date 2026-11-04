"""Shufersal's public price-transparency site (prices.shufersal.co.il).

The site lists files in an HTML table. Each row links to a gzip file on public
cloud storage through a signed URL that expires (within minutes to hours), so a file must be
downloaded right after its link is read. Listing everything first and downloading afterwards
does not work: reading all the pages took 15 minutes and the first links had expired (HTTP 403
"Server failed to authenticate the request ... signature", 2026-11-04). So: list one store's
files, download them at once, go to the next store (`latest_link`, `download`); and when a
download still answers with an expired signature, ask for a fresh link to the same file once.
"""

import html
import re
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass
from urllib.request import Request, urlopen

from collector.files import file_stamp
from collector.retry import with_retries

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
    pages = min(last_page(first), _MAX_PAGES)
    print(f"  shufersal list, category {category}: {pages} pages", flush=True)
    for page in range(2, pages + 1):
        html_page = fetch(list_url(category, store_id, page)).decode("utf-8", errors="replace")
        links += parse_file_links(html_page)
        if page % 5 == 0 or page == pages:
            print(f"  shufersal list, category {category}: page {page}/{pages}", flush=True)
    return links


def fetch(url: str, timeout: float = 60) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})

    def once() -> bytes:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https hosts only
            return response.read()

    return with_retries(once)


# What the storage answers when a signed link has expired or its signature is wrong. Other 403s
# (the server refusing us, a blocked address) say something else and are not "try a new link".
_SIGNATURE_WORDS = ("authenticationfailed", "failed to authenticate", "signature", "signed expiry")


def is_expired_signature(error: Exception) -> bool:
    """True for HTTP 403 from the storage because of the signature (an old link)."""
    if not isinstance(error, urllib.error.HTTPError) or error.code != 403:
        return False
    try:
        body = error.read(4096).decode("utf-8", errors="replace").lower()
    except Exception:  # an unreadable answer: assume it is not the signature
        return False
    return any(word in body for word in _SIGNATURE_WORDS)


def latest_link(category: int, store_number: int, listing=None) -> FileLink | None:
    """The newest file of a category for one store, from a listing read right now.
    `listing` is a stand-in for `list_all` in tests."""
    links = (listing or list_all)(category, store_number)
    return max(links, key=lambda link: file_stamp(link.name), default=None)


def download(
    link: FileLink,
    category: int,
    store_number: int,
    listing=None,
    getter: Callable[[str], bytes] | None = None,
) -> bytes:
    """Download the file of a link read just now. If the answer is an expired signature, read the
    store's listing again, take the new link to the same file and try once more. Any other error,
    including any other 403, is raised as it is."""
    get = getter or fetch
    try:
        return get(link.url)
    except urllib.error.HTTPError as error:
        if not is_expired_signature(error):
            raise
        fresh = next(
            (
                item
                for item in (listing or list_all)(category, store_number)
                if item.name == link.name
            ),
            None,
        )
        if fresh is None:
            raise
        return get(fresh.url)
