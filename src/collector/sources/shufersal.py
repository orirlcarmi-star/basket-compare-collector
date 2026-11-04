"""Shufersal's public price-transparency site (prices.shufersal.co.il).

The site lists files in an HTML table. Each row links to a gzip file on public
cloud storage through a signed URL that expires (within minutes to hours), so a file must be
downloaded right after its link is read. Reading all the pages first and downloading afterwards
does not work: reading them took 15 minutes and the first links had expired (HTTP 403 "Server
failed to authenticate the request ... signature", 2026-11-04). Asking the site for one store at a
time is too slow (25-35 seconds a request, two per store: about 7 hours for 417 stores).

So: read the general listing page by page (`pages`), and download the files of a page at once,
before asking for the next page (see collect.py). When a download still answers with an expired
signature, `download` asks for a fresh link to the same file once (a listing of that store: slow,
but it should be rare).
"""

import html
import re
import time
import urllib.error
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.request import Request, urlopen

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


def pages(category: int, store_id: int = 0) -> Iterator[list[FileLink]]:
    """The file links of a category one page at a time (store_id 0 = all stores). A page is
    requested only when the caller asks for the next one, so whatever the caller does with a
    page (downloading its files) happens before the next request."""
    started = time.monotonic()
    first = fetch(list_url(category, store_id)).decode("utf-8", errors="replace")
    total = min(last_page(first), _MAX_PAGES)
    print(f"  shufersal list, category {category}: {total} pages", flush=True)
    yield parse_file_links(first)
    for page in range(2, total + 1):
        html_page = fetch(list_url(category, store_id, page)).decode("utf-8", errors="replace")
        if page % 5 == 0 or page == total:
            minutes = (time.monotonic() - started) / 60
            print(
                f"  shufersal list, category {category}: page {page}/{total} "
                f"({minutes:.1f} min since the first)",
                flush=True,
            )
        yield parse_file_links(html_page)


def list_all(category: int, store_id: int = 0) -> list[FileLink]:
    """Every file link of a category across all pages (store_id 0 = all stores)."""
    return [link for page in pages(category, store_id) for link in page]


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
