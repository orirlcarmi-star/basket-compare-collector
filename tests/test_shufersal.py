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


def test_the_newest_file_of_a_store_is_chosen():
    older = link("PriceFull7290027600007-001-413-20261103-030000")
    newer = link("PriceFull7290027600007-001-413-20261104-030000")
    assert sh.latest_link(2, 413, listing=lambda *a: [older, newer]) == newer
    assert sh.latest_link(2, 413, listing=lambda *a: []) is None


STORES_XML = (
    "<Root><ChainID>7290027600007</ChainID><SubChains><SubChain><SubChainID>1</SubChainID><Stores>"
    + "".join(
        f"<Store><StoreID>{n}</StoreID><StoreName>סניף {n}</StoreName><Address>א</Address>"
        f"<City>חיפה</City></Store>"
        for n in ("2", "413", "71")
    )
    + "</Stores></SubChain></SubChains></Root>"
)


def price_xml(store):
    return (
        f"<Root><ChainID>7290027600007</ChainID><SubChainID>1</SubChainID><StoreID>{store}</StoreID>"
        "<Items><Item><ItemCode>1</ItemCode><ItemName>חלב</ItemName><ItemPrice>7.35</ItemPrice>"
        "</Item></Items></Root>"
    )


@pytest.fixture
def fake_site(monkeypatch):
    """Shufersal's site: listings per store with signed links, and links that expire after use."""
    events, dead = [], set()
    now_name = datetime.now(UTC).strftime("%Y%m%d")

    def list_all(category, store_id=0):
        events.append(("list", category, store_id))
        if category == sh.CATEGORY_STORES:
            return [link(f"Stores7290027600007-000-{now_name}-020", "s")]
        kind = "PriceFull" if category == sh.CATEGORY_PRICE_FULL else "PromoFull"
        old = link(f"{kind}7290027600007-001-{store_id:03d}-20200101-030000", f"old{store_id}")
        new = link(f"{kind}7290027600007-001-{store_id:03d}-{now_name}-030000", f"new{store_id}")
        return [old, new]

    def fetch(url, timeout=60):
        events.append(("get", url))
        if "?sig=" in url and url.split("sig=")[1] in dead:
            raise http_error(403, EXPIRED)
        if "Stores" in url:
            return STORES_XML.encode()
        store = int(url.split("-001-")[1][:3])
        kind = "price" if "PriceFull" in url else "promo"
        return (price_xml(store) if kind == "price" else "<Root><Promotions/></Root>").encode()

    monkeypatch.setattr(sh, "list_all", list_all)
    monkeypatch.setattr(sh, "fetch", fetch)
    return events, dead


def test_each_store_is_listed_and_downloaded_before_the_next_one(fake_site, tmp_path):
    events, _ = fake_site
    assert collect.collect_shufersal(tmp_path, None) == 0
    kinds = [e[0] for e in events]
    assert kinds[:2] == ["list", "get"]  # the stores file: list it, download it at once
    # after that: list price, get price, list promo, get promo - store by store, never all listings
    per_store = events[2:]
    assert [e[0] for e in per_store] == ["list", "get", "list", "get"] * 3
    assert [e[2] for e in per_store if e[0] == "list"][::2] == [2, 413, 71]  # sorted by store id
    # every price file is written, under the store's own number
    assert sorted(p.name for p in (tmp_path / "shufersal" / "prices").glob("*.json")) == [
        "2.json", "413.json", "71.json",
    ]  # fmt: skip
    applied = json.loads((tmp_path / "shufersal" / "applied.json").read_text(encoding="utf-8"))
    assert sorted(applied) == ["2", "413", "71"]


def test_an_old_file_is_not_taken_and_an_expired_link_is_renewed(fake_site, tmp_path, monkeypatch):
    events, dead = fake_site
    dead.add("new413")  # the first link read for store 413 will have expired

    original = sh.list_all

    def list_all(category, store_id=0):
        links = original(category, store_id)
        if (
            store_id == 413
            and category == sh.CATEGORY_PRICE_FULL
            and sum(1 for e in events if e == ("list", category, 413)) == 2
        ):
            dead.discard("new413")  # the second listing gives a link that works
        return links

    monkeypatch.setattr(sh, "list_all", list_all)
    assert collect.collect_shufersal(tmp_path, None) == 0
    gets_for_413 = [
        e[1] for e in events if e[0] == "get" and "PriceFull" in e[1] and "-413-" in e[1]
    ]
    assert len(gets_for_413) == 2  # the expired link, then the renewed one
    assert (tmp_path / "shufersal" / "prices" / "413.json").exists()


def test_the_limit_counts_stores_and_leaves_the_rest_alone(fake_site, tmp_path):
    events, _ = fake_site
    assert collect.collect_shufersal(tmp_path, 1) == 0
    assert [p.name for p in (tmp_path / "shufersal" / "prices").glob("*.json")] == ["2.json"]
    assert [e for e in events if e[0] == "list" and e[2] not in (0, 2)] == []  # others not asked
