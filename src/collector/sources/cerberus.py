"""The Cerberus file portal run by NCR (url.publishedprices.co.il).

Many chains publish here; each has a public username and an empty password
(docs/04-data-sources.md). One username sees one chain. This module only reads:
it logs in, lists files and downloads them. The portal also offers delete and
rename buttons — never used.
"""

import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

BASE_URL = "https://url.publishedprices.co.il"
USER_AGENT = (
    "basket-compare-collector (+https://github.com/orirlcarmi-star/basket-compare-collector)"
)

# Public usernames for the chains we collect (from the chains' own publications,
# as used by the open-source il-supermarket-scraper project).
USERNAMES = {
    "ramilevi": "RamiLevi",
    "osherad": "osherad",
    "yohananof": "yohananof",
}

_CSRF = re.compile(r'name="csrftoken"\s+content="([^"]+)"|name="csrftoken"\s+value="([^"]+)"')


@dataclass(frozen=True)
class RemoteFile:
    name: str  # e.g. "PriceFull7290058140886-001-001-20261027-070006.gz"
    size: int | None


def csrf_token(page_html: str) -> str:
    match = _CSRF.search(page_html)
    if not match:
        raise ValueError("csrftoken not found on page")
    return match.group(1) or match.group(2)


def parse_file_list(payload: str) -> list[RemoteFile]:
    """The portal's /file/json/dir answer: {"aaData": [{"fname": ..., "size": ...}, ...]}."""
    rows = json.loads(payload).get("aaData", [])
    return [
        RemoteFile(name=row["fname"], size=row.get("size"))
        for row in rows
        if isinstance(row, dict) and row.get("fname") and row.get("ftype", "file") == "file"
    ]


class Session:
    """A logged-in, read-only session for one chain."""

    def __init__(self, username: str, timeout: float = 60) -> None:
        self._timeout = timeout
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self._opener.addheaders = [("User-Agent", USER_AGENT)]
        login_page = self._get("/login")
        self._post(
            "/login/user",
            {"r": "", "username": username, "password": "", "csrftoken": csrf_token(login_page)},
        )
        self._csrf = csrf_token(self._get("/file"))

    def _get(self, path: str) -> str:
        with self._opener.open(BASE_URL + path, timeout=self._timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def _post(self, path: str, fields: dict[str, str]) -> str:
        data = urllib.parse.urlencode(fields).encode()
        with self._opener.open(BASE_URL + path, data=data, timeout=self._timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def list_files(self) -> list[RemoteFile]:
        payload = self._post(
            "/file/json/dir",
            {
                "sEcho": "1",
                "iColumns": "5",
                "iDisplayStart": "0",
                "iDisplayLength": "100000",
                "mDataProp_0": "fname",
                "sSearch": "",
                "cd": "/",
                "csrftoken": self._csrf,
            },
        )
        return parse_file_list(payload)

    def download(self, name: str) -> bytes:
        quoted = urllib.parse.quote(name)
        with self._opener.open(f"{BASE_URL}/file/d/{quoted}", timeout=self._timeout) as response:
            return response.read()
