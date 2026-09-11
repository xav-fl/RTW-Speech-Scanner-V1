"""A `Fetcher` that presents a real browser's TLS fingerprint.

Seven agencies -- USDA, Defense/War, HHS, Labor, NRC, SSA and Transportation --
serve a well-formed listing to a browser and 403 to every stdlib HTTP client.
The survey established that the block is not a crawl policy: `robots.txt` on
those hosts either 403s too or permits the newsroom path outright, the pages are
read by the public all day, and the Internet Archive crawls several of them
daily. What they discriminate on is how the client speaks TLS.

WHY NOT A BROWSER
-----------------
A browser was tried first and is the wrong tool here, which is worth recording
so nobody re-treads it:

  * **Headless Chromium is itself detected.** Chromium headless, Chrome headless
    via `channel="chrome"`, and the headless shell all returned 403 from USDA,
    Defense, HHS, Labor, Transportation and Commerce. Only NRC and SSA passed.
  * **Headed Chromium could not be run.** The full binary fails to spawn in a
    non-interactive environment (`spawn UNKNOWN`), and `channel="chrome"`
    headed launches but the page detaches immediately.

`curl_cffi` reproduces Chrome's TLS and HTTP/2 handshake from an ordinary
Python process, which is both lighter than a browser and, here, more effective:
seven of the nine pass, against two for headless Chromium.

WHAT THIS DOES NOT SOLVE
------------------------
Two agencies need a person, not a better client, and this class will not pretend
otherwise:

  * **Commerce** serves a Cloudflare JavaScript challenge. A TLS handshake is not
    the barrier; executing the challenge is, and this client does not run JS.
  * **EPA** serves an interactive CAPTCHA. That is a request for a human, and the
    only legitimate answer is a human.

Both are reachable from an ordinary desktop browser on the project network, so
they are collected by `BrowserFetcher` in a headed session rather than here.

IDENTIFICATION
--------------
The User-Agent has to match the handshake or the mismatch is itself a signal, so
it is Chrome's. The project identifies itself in an `X-Research-Contact` header
sent on every request instead. That is a deliberate trade and it is the same one
`browser.py` makes for the same reason.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from typing import Optional


class ImpersonationUnavailable(RuntimeError):
    """`curl_cffi` is not installed."""


#: Sent on every request so the traffic is attributable to the project even
#: though the User-Agent must remain a browser's.
RESEARCH_HEADERS = {
    "X-Research-Contact":
        "eps-research/0.1 (academic research; contact via institution)",
    "Accept-Language": "en-US,en;q=0.9",
}

#: Which browser `curl_cffi` reproduces. Pinned rather than left to the default
#: so a library upgrade cannot silently change what the agencies see.
IMPERSONATE = "chrome"


class ImpersonatingFetcher:
    """Same interface as `base.Fetcher`, over a browser-shaped TLS handshake."""

    def __init__(self, pause: float = 0.5, retries: int = 4, timeout: int = 45,
                 impersonate: str = IMPERSONATE):
        self.pause = pause
        self.retries = retries
        self.timeout = timeout
        self.impersonate = impersonate
        self.calls = 0
        self._session = None
        #: Set for parity with `Fetcher`; the real UA comes from the
        #: impersonation profile and must not be overridden, or the headers
        #: and the handshake disagree.
        self.user_agent = "(chrome, via curl_cffi impersonation)"

    def _ensure(self):
        if self._session is not None:
            return
        try:
            from curl_cffi import requests as cr
        except ImportError as exc:                   # pragma: no cover
            raise ImpersonationUnavailable(
                "curl_cffi is not installed. `pip install curl_cffi`. The "
                "fifteen HTTP-reachable agencies do not need it.") from exc
        self._session = cr.Session(impersonate=self.impersonate,
                                   headers=dict(RESEARCH_HEADERS))

    def close(self) -> None:
        try:
            if self._session is not None:
                self._session.close()
        except Exception:                            # pragma: no cover
            pass
        self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # -- the Fetcher interface --------------------------------------------

    def get_bytes(self, url: str, params: Optional[dict] = None) -> bytes:
        self._ensure()
        if params:
            url = url + ("&" if "?" in url else "?") + \
                urllib.parse.urlencode(params)
        last = None
        for attempt in range(self.retries):
            try:
                r = self._session.get(url, timeout=self.timeout)
                if r.status_code in (404, 410):
                    # Will not become a 200 on retry; stop paying for it. Same
                    # rule as `base.Fetcher`.
                    raise FileNotFoundError("HTTP %d: %s" % (r.status_code, url))
                if r.status_code >= 400:
                    raise RuntimeError("HTTP %d" % r.status_code)
                self.calls += 1
                return r.content
            except FileNotFoundError:
                raise
            except Exception as exc:                 # noqa: BLE001
                last = exc
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
        raise last if last else RuntimeError("fetch failed: " + url)

    def get_text(self, url: str, params: Optional[dict] = None) -> str:
        return self.get_bytes(url, params).decode("utf-8", "replace")

    def get_json(self, url: str, params: Optional[dict] = None):
        return json.loads(self.get_bytes(url, params))

    def rest(self) -> None:
        time.sleep(self.pause)
