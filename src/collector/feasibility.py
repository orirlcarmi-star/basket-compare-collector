"""Feasibility check (build plan step 1.1): can a GitHub-hosted runner reach the chains?

GitHub's runners sit outside Israel. This downloads one real Shufersal price file
end to end and checks that every other source host answers, then writes a small
report. Run with:  python -m collector.feasibility
"""

import os
import re
import sys
import time
from urllib.error import HTTPError, URLError

from collector.encoding import decode_price_file
from collector.sources import shufersal

ONLINE_STORE_ID = 413  # "שופרסל ONLINE"

# Every other place chains publish from (docs/04-data-sources.md).
OTHER_HOSTS = {
    "Carrefour (open site)": "https://prices.carrefour.co.il/",
    "Cerberus portal (Rami Levy, Osher Ad, ...)": "https://url.publishedprices.co.il/login",
    "Nibit / Matrix (Victory, ...)": "https://laibcatalog.co.il/",
    "Bina (Bareket)": "https://superbareket.binaprojects.com/Main.aspx",
    "Hazi Hinam": "https://shop.hazi-hinam.co.il/Prices",
}

_ITEM_TAG = re.compile(r"<Item>", re.IGNORECASE)


def check_shufersal() -> tuple[bool, str]:
    started = time.monotonic()
    page = shufersal.fetch(shufersal.list_url(shufersal.CATEGORY_PRICE_FULL, ONLINE_STORE_ID))
    links = shufersal.parse_file_links(page.decode("utf-8", errors="replace"))
    if not links:
        return False, "file list loaded but contained no price-file links"
    raw = shufersal.fetch(links[0].url)
    items = len(_ITEM_TAG.findall(decode_price_file(raw)))
    seconds = time.monotonic() - started
    ok = items > 0
    return ok, f"{links[0].name}: {len(raw) / 1024:.0f} KB, {items:,} items, {seconds:.1f}s"


def probe(url: str) -> tuple[bool, str]:
    started = time.monotonic()
    try:
        shufersal.fetch(url, timeout=30)
        status = "200"
    except HTTPError as error:
        status = str(error.code)
    except (URLError, TimeoutError, OSError) as error:
        return False, f"unreachable: {error}"
    seconds = time.monotonic() - started
    return status.startswith("2"), f"HTTP {status}, {seconds:.1f}s"


def main() -> int:
    rows = []
    try:
        shufersal_ok, detail = check_shufersal()
    except Exception as error:  # report every failure; this is a diagnostic
        shufersal_ok, detail = False, f"{type(error).__name__}: {error}"
    rows.append(("Shufersal — full download", shufersal_ok, detail))
    for name, url in OTHER_HOSTS.items():
        rows.append((name, *probe(url)))

    report = "\n".join(
        ["| Source | OK | Detail |", "|---|---|---|"]
        + [f"| {name} | {'✅' if ok else '❌'} | {detail} |" for name, ok, detail in rows]
    )
    print(report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## Feasibility: reaching chain sources from GitHub\n\n" + report + "\n")
    return 0 if shufersal_ok else 1


if __name__ == "__main__":
    sys.exit(main())
