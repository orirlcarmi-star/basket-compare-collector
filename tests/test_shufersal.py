from collector.sources.shufersal import (
    FileLink,
    last_page,
    list_url,
    parse_file_links,
)

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
    assert list_url(2, 0, page=3).endswith("catID=2&storeId=0&page=3")


def test_parses_stores_file_link_with_short_name():
    row = (
        '<a href="https://pricesprodpublic.blob.core.windows.net/stores/'
        'Stores7290027600007-000-20261028-020.gz?sv=1&amp;sp=r">x</a>'
    )
    assert [link.name for link in parse_file_links(row)] == ["Stores7290027600007-000-20261028-020"]


def test_last_page_reads_the_pager():
    pager = '<a href="?catID=2&amp;page=2">2</a><a href="?catID=2&amp;page=22">&gt;&gt;</a>'
    assert last_page(pager) == 22
    assert last_page("<table></table>") == 1


# --- signed links expire: list a store, download at once, ask for a new link when it expired ---

import io  # noqa: E402
import json  # noqa: E402
import urllib.error  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402

from collector import collect  # noqa: E402
from collector.sources import shufersal as sh  # noqa: E402

EXPIRED = (
    b'<?xml version="1.0"?><Error><Code>AuthenticationFailed</Code><Message>Server failed to '
    b"authenticate the request. Make sure the value of Authorization header is formed correctly "
    b"including the signature.</Message></Error>"
)
REFUSED = (
    b"<Error><Code>AuthorizationFailure</Code>"
    b"<Message>This request is not authorized.</Message></Error>"
)


def http_error(code, body=b""):
    return urllib.error.HTTPError("https://blob/x", code, "no", {}, io.BytesIO(body))


def link(name, token="a"):
    return sh.FileLink(name=name, url=f"https://blob/{name}.gz?sig={token}")


NAME = "PriceFull7290027600007-001-413-20261104-030000"


def test_only_a_403_about_the_signature_is_an_expired_link():
    assert sh.is_expired_signature(http_error(403, EXPIRED))
    assert not sh.is_expired_signature(http_error(403, REFUSED))  # the server refusing us
    assert not sh.is_expired_signature(http_error(403, b""))
    assert not sh.is_expired_signature(http_error(404, EXPIRED))  # not a 403
    assert not sh.is_expired_signature(http_error(500, EXPIRED))
    assert not sh.is_expired_signature(OSError("reset"))


def test_an_expired_link_is_replaced_by_a_fresh_one_for_the_same_file():
    asked, listed = [], []

    def getter(url):
        asked.append(url)
        if url.endswith("sig=old"):
            raise http_error(403, EXPIRED)
        return b"the file"

    def listing(category, store):
        listed.append((category, store))
        return [link("another-file", "new"), link(NAME, "new")]

    got = sh.download(link(NAME, "old"), 2, 413, listing=listing, getter=getter)
    assert got == b"the file"
    assert asked == [f"https://blob/{NAME}.gz?sig=old", f"https://blob/{NAME}.gz?sig=new"]
    assert listed == [(2, 413)]  # one fresh listing of that store, for that kind of file


def test_any_other_403_is_not_tried_again():
    asked, listed = [], []

    def getter(url):
        asked.append(url)
        raise http_error(403, REFUSED)

    with pytest.raises(urllib.error.HTTPError):
        sh.download(link(NAME), 2, 413, listing=lambda *a: listed.append(a) or [], getter=getter)
    assert len(asked) == 1 and listed == []  # one try, no new listing


def test_a_new_link_is_asked_for_only_once():
    asked = []

    def getter(url):
        asked.append(url)
        raise http_error(403, EXPIRED)  # even the fresh link is refused

    with pytest.raises(urllib.error.HTTPError):
        sh.download(
            link(NAME, "old"), 2, 413, listing=lambda *a: [link(NAME, "new")], getter=getter
        )
    assert len(asked) == 2


def test_an_expired_link_to_a_file_that_is_no_longer_listed_is_an_error():
    def getter(url):
        raise http_error(403, EXPIRED)

    with pytest.raises(urllib.error.HTTPError):
        sh.download(link(NAME, "old"), 2, 413, listing=lambda *a: [link("other")], getter=getter)


STORES_XML = (
    "<Root><ChainID>7290027600007</ChainID><SubChains><SubChain><SubChainID>1</SubChainID><Stores>"
    + "".join(
        f"<Store><StoreID>{n}</StoreID><StoreName>סניף {n}</StoreName><Address>א</Address>"
        f"<City>חיפה</City></Store>"
        for n in ("2", "413", "71")
    )
    + "</Stores></SubChain></SubChains></Root>"
)
TODAY = datetime.now(UTC).strftime("%Y%m%d")


def price_xml(store):
    return (
        f"<Root><ChainID>7290027600007</ChainID><SubChainID>1</SubChainID><StoreID>{store}</StoreID>"
        "<Items><Item><ItemCode>1</ItemCode><ItemName>חלב</ItemName><ItemPrice>7.35</ItemPrice>"
        "</Item></Items></Root>"
    )


def file_name(kind, store, day=None, time="030000"):
    return f"{kind}7290027600007-001-{store}-{day or TODAY}-{time}"


class FakeSite:
    """Shufersal's site: the listing in pages, links that can be made to expire, and a log of every
    request in the order it was made."""

    def __init__(self, monkeypatch):
        self.events = []
        self.listings = {}  # category -> list of pages (each a list of file names)
        self.dead = set()  # links (the part after sig=) that answer "expired"
        self.issued = 0
        monkeypatch.setattr(sh, "pages", self.pages)
        monkeypatch.setattr(sh, "list_all", self.list_all)
        monkeypatch.setattr(sh, "fetch", self.fetch)

    def new_link(self, name):
        self.issued += 1
        return sh.FileLink(name=name, url=f"https://blob/{name}.gz?sig=t{self.issued}")

    def pages(self, category, store_id=0):
        pages = self.listings.get(category, [[]])
        for number, names in enumerate(pages, start=1):
            self.events.append(("page", category, number))  # runs only when the page is asked for
            yield [self.new_link(n) for n in names]

    def list_all(self, category, store_id=0):
        self.events.append(("relist", category, store_id))
        return [link for page in self.pages_quiet(category) for link in page]

    def pages_quiet(self, category):
        return [[self.new_link(n) for n in names] for names in self.listings.get(category, [[]])]

    def fetch(self, url, timeout=60):
        self.events.append(("get", url.split("/")[-1].split(".gz")[0]))
        if "sig=" in url and url.split("sig=")[1] in self.dead:
            raise http_error(403, EXPIRED)
        if url.startswith("https://blob/Stores"):
            return STORES_XML.encode()
        store = int(url.split("-001-")[1][:3])
        return (price_xml(store) if "PriceFull" in url else "<Root><Promotions/></Root>").encode()


@pytest.fixture
def site(monkeypatch):
    fake = FakeSite(monkeypatch)
    fake.listings[sh.CATEGORY_STORES] = [[f"Stores7290027600007-000-{TODAY}-020"]]
    return fake


def price_pages(site, *pages):
    site.listings[sh.CATEGORY_PRICE_FULL] = [
        [file_name("PriceFull", s) for s in page] for page in pages
    ]


def steps(site, kind="PriceFull"):
    """The page requests and the downloads of one kind of file, in the order they were made."""
    return [
        ("page" if e[0] == "page" else "get")
        for e in site.events
        if (e[0] == "page" and e[1] == sh.CATEGORY_PRICE_FULL) or (e[0] == "get" and kind in e[1])
    ]


def test_the_files_of_a_page_are_downloaded_before_the_next_page_is_asked_for(site, tmp_path):
    price_pages(site, ("002", "413"), ("071",))
    assert collect.collect_shufersal(tmp_path, None) == 0
    # page 1, its two files, page 2, its file: never a page request between a link and its file
    assert steps(site) == ["page", "get", "get", "page", "get"]
    prices = sorted(p.name for p in (tmp_path / "shufersal" / "prices").glob("*.json"))
    assert prices == ["002.json", "071.json", "413.json"]
    applied = json.loads((tmp_path / "shufersal" / "applied.json").read_text(encoding="utf-8"))
    assert sorted(applied) == ["2", "413", "71"]


def test_listing_requests_do_not_grow_with_the_number_of_stores(site, tmp_path):
    few = [("002", "413", "071")]
    many = [tuple(f"{n:03d}" for n in range(1, 21))]  # one page, twenty stores
    counts = []
    for page in (few, many):
        site.events.clear()
        price_pages(site, *page)
        assert collect.collect_shufersal(tmp_path / str(len(page[0])), None) == 0
        counts.append(sum(1 for e in site.events if e[0] in ("page", "relist")))
    # the stores file, the price page and the promotion page: the same for 3 and for 20 stores
    assert counts[0] == counts[1] == 3


def test_a_newer_file_on_a_later_page_replaces_an_older_one_and_not_the_other_way(site, tmp_path):
    older = file_name("PriceFull", "002", time="010000")
    newer = file_name("PriceFull", "002", time="050000")
    site.listings[sh.CATEGORY_PRICE_FULL] = [[older], [newer], [older]]
    assert collect.collect_shufersal(tmp_path, None) == 0
    got = [e[1] for e in site.events if e[0] == "get" and "PriceFull" in e[1]]
    assert got == [older, newer]  # the older one on the third page is not downloaded again
    applied = json.loads((tmp_path / "shufersal" / "applied.json").read_text(encoding="utf-8"))
    assert applied == {"2": f"{TODAY}050000"}


def test_files_older_than_a_week_are_not_taken(site, tmp_path):
    site.listings[sh.CATEGORY_PRICE_FULL] = [
        [file_name("PriceFull", "002"), file_name("PriceFull", "413", day="20200101")]
    ]
    assert collect.collect_shufersal(tmp_path, None) == 0
    assert [p.name for p in (tmp_path / "shufersal" / "prices").glob("*.json")] == ["002.json"]


def test_an_expired_link_is_renewed_once_with_a_listing_of_that_store(site, tmp_path, monkeypatch):
    name = file_name("PriceFull", "413")
    price_pages(site, ("413",))
    first = {"done": False}
    original = site.fetch

    def fetch(url, timeout=60):
        if name in url and not first["done"]:
            first["done"] = True
            site.events.append(("get", name))
            raise http_error(403, EXPIRED)
        return original(url, timeout)

    monkeypatch.setattr(sh, "fetch", fetch)
    # the store-filtered listing the renewal asks for
    site.listings[sh.CATEGORY_PRICE_FULL] = [[name]]
    assert collect.collect_shufersal(tmp_path, None) == 0
    assert [e for e in site.events if e[0] == "get" and name in e[1]] == [("get", name)] * 2
    assert sum(1 for e in site.events if e[0] == "relist") == 1  # one renewal, no more
    assert (tmp_path / "shufersal" / "prices" / "413.json").exists()


def test_promotions_are_taken_only_for_stores_with_prices(site, tmp_path):
    price_pages(site, ("002", "413"))
    site.listings[sh.CATEGORY_PROMO_FULL] = [
        [file_name("PromoFull", s) for s in ("002", "071", "413")]
    ]
    assert collect.collect_shufersal(tmp_path, None) == 0
    deals = sorted(p.name for p in (tmp_path / "shufersal" / "deals").glob("*.json"))
    assert deals == ["002.json", "413.json"]  # 071 has no prices, so no promotion download
    assert not [e for e in site.events if e[0] == "get" and "PromoFull" in e[1] and "-071-" in e[1]]


def test_the_limit_stops_reading_the_listing_early(site, tmp_path):
    price_pages(site, ("002", "413"), ("071", "100"), ("200",))
    assert collect.collect_shufersal(tmp_path, 2) == 0
    pages_asked = [e for e in site.events if e[0] == "page" and e[1] == sh.CATEGORY_PRICE_FULL]
    assert len(pages_asked) == 1  # a small test run reads one page, not twenty-two
    assert len(list((tmp_path / "shufersal" / "prices").glob("*.json"))) == 2


def test_a_file_that_cannot_be_downloaded_is_counted_and_the_rest_are_taken(
    site, tmp_path, monkeypatch
):
    price_pages(site, ("002", "413"))
    bad = file_name("PriceFull", "002")
    original = site.fetch

    def fetch(url, timeout=60):
        if bad in url:
            raise http_error(403, REFUSED)  # a plain refusal: raised, not renewed
        return original(url, timeout)

    monkeypatch.setattr(sh, "fetch", fetch)
    assert collect.collect_shufersal(tmp_path, None) == 1
    assert [p.name for p in (tmp_path / "shufersal" / "prices").glob("*.json")] == ["413.json"]
    assert not [e for e in site.events if e[0] == "relist"]  # no renewal for another 403
