"""A `Fetcher` that drives a real browser, for agencies that refuse HTTP.

Nine of the 24 agencies serve a well-formed listing to a browser and 403 to
every HTTP client tried -- urllib, curl, the .NET stack and httpx, all with a
browser User-Agent. The block is on client fingerprint, not on collection: the
pages are public, the newsrooms are read by ordinary people all day, and the
Internet Archive crawls several of them successfully every day.

THE POINT OF THIS CLASS IS THAT IT CHANGES NOTHING ELSE.

`BrowserFetcher` presents the same four methods `Fetcher` does -- `get_text`,
`get_bytes`, `get_json`, `rest` -- so an adapter written against one works
against the other with no edit. That was the argument for splitting `tier` from
`transport` in H-46: a site's shape and a site's reachability are independent,
and USDA, Defense, HHS, DOL, NRC, SSA and Transportation are ordinary listing
agencies that happen to need a different pipe.

    fetcher = BrowserFetcher(pause=0.6)
    refs = UsdaAdapter(fetcher=fetcher).list_documents(start, end)
    fetcher.close()

Two deliberate properties:

**The profile persists.** `launch_persistent_context` writes to a profile
directory, so cookies survive between runs. That is what makes an agency behind
a one-off human-verification step workable: a person clears it once in a headed
window and the resulting session is reused by later headless runs. The
verification is completed by a human, which is what it is asking for; nothing
here attempts to answer one.

**Headless is the default, headed is a deliberate act.** `headed=True` exists
for the first run against a site that needs a person, and for debugging. It is
not the normal mode.

Playwright is the only non-stdlib dependency in the collection layer, and it is
confined to this file. `harvest_us.py` imports it lazily, so a run over the
fifteen HTTP agencies still works on a machine that has never installed it.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from typing import Optional

from .base import USER_AGENT

#: Where the persistent profile lives. Cookies, and therefore any cleared
#: challenge, survive here between runs.
DEFAULT_PROFILE = os.path.join(
    os.path.expanduser("~"), ".eps-browser-profile")

#: A real Chrome UA. Unlike the HTTP fetchers there is no honesty gained by
#: sending a custom token here -- the client genuinely IS Chromium, and a
#: site that fingerprints the browser would be told one thing by the headers
#: and another by the TLS handshake. The project identifies itself in the
#: `X-Research-Contact` header instead, which is sent on every request.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


class BrowserUnavailable(RuntimeError):
    """Playwright is not installed, or its browser binary is missing."""


class BrowserFetcher:
    """Same interface as `base.Fetcher`, backed by Chromium."""

    def __init__(self, pause: float = 0.6, retries: int = 3, timeout: int = 45,
                 user_agent: str = BROWSER_UA, headed: bool = False,
                 profile_dir: str = DEFAULT_PROFILE,
                 wait_until: str = "domcontentloaded"):
        self.pause = pause
        self.retries = retries
        self.timeout = timeout
        self.user_agent = user_agent
        self.headed = headed
        self.profile_dir = profile_dir
        self.wait_until = wait_until
        self.calls = 0
        self._pw = None
        self._ctx = None
        self._page = None

    # -- lifecycle ---------------------------------------------------------

    def _ensure(self):
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:                   # pragma: no cover
            raise BrowserUnavailable(
                "playwright is not installed. `pip install playwright` then "
                "`playwright install chromium`. The fifteen HTTP-reachable "
                "agencies do not need it.") from exc
        self._pw = sync_playwright().start()
        os.makedirs(self.profile_dir, exist_ok=True)
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(
                self.profile_dir,
                headless=not self.headed,
                user_agent=self.user_agent,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
                extra_http_headers={
                    # The project's identity travels in a header, since the UA
                    # has to stay a real browser's for the handshake to match.
                    "X-Research-Contact":
                        "eps-research/0.1 (academic research; "
                        "contact via institution)",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        except Exception as exc:                     # pragma: no cover
            self.close()
            raise BrowserUnavailable(
                "could not launch chromium: %s. Run "
                "`playwright install chromium`." % exc) from exc
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._page.set_default_timeout(self.timeout * 1000)

    def close(self) -> None:
        for obj, meth in ((self._ctx, "close"), (self._pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, meth)()
            except Exception:                        # pragma: no cover
                pass
        self._pw = self._ctx = self._page = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # -- the Fetcher interface --------------------------------------------

    def get_text(self, url: str, params: Optional[dict] = None) -> str:
        self._ensure()
        target = url
        if params:
            target = url + ("&" if "?" in url else "?") + \
                urllib.parse.urlencode(params)
        last = None
        for attempt in range(self.retries):
            try:
                resp = self._page.goto(target, wait_until=self.wait_until,
                                       timeout=self.timeout * 1000)
                status = resp.status if resp else 0
                # A challenge page answers 200 with a few hundred bytes, so
                # status alone is not enough to call it a success.
                html = self._page.content()
                if status and status >= 400:
                    raise RuntimeError("HTTP %d" % status)
                if _looks_like_challenge(html):
                    raise ChallengePresented(
                        "%s served an interactive verification page. Run once "
                        "with headed=True and clear it by hand; the profile at "
                        "%s keeps the session for later runs."
                        % (urllib.parse.urlsplit(target).netloc,
                           self.profile_dir))
                self.calls += 1
                return html
            except ChallengePresented:
                raise                                # not worth retrying
            except Exception as exc:                 # noqa: BLE001
                last = exc
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
        raise last if last else RuntimeError("browser fetch failed: " + target)

    def get_bytes(self, url: str, params: Optional[dict] = None) -> bytes:
        return self.get_text(url, params).encode("utf-8", "replace")

    def get_json(self, url: str, params: Optional[dict] = None):
        """JSON through a browser, which wraps it in a viewer's <pre>."""
        html = self.get_text(url, params)
        raw = html
        start, end = html.find("<pre"), html.rfind("</pre>")
        if start != -1 and end != -1:
            raw = html[html.find(">", start) + 1:end]
        import re
        from html import unescape
        raw = unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        return json.loads(raw)

    def rest(self) -> None:
        time.sleep(self.pause)


class ChallengePresented(RuntimeError):
    """The site served an interactive human-verification page.

    Raised rather than retried, and never answered. A CAPTCHA is a request for
    a person, so the only legitimate response is to put a person in front of it
    once -- `headed=True` -- after which the persistent profile carries the
    session.
    """


#: Signatures of the interstitials the survey met, plus the length test that
#: separates them from real pages. Cloudflare's is ~260 bytes of visible text;
#: an agency listing is tens of kilobytes.
_CHALLENGE_MARKERS = (
    "Just a moment", "Performing security verification",
    "confirm you are human", "Human Verification",
    "Checking your browser", "cf-browser-verification", "bm-verify",
    "Access Denied",
)


def _looks_like_challenge(html: str) -> bool:
    if not html or len(html) > 20000:
        return False
    return any(m.lower() in html.lower() for m in _CHALLENGE_MARKERS)
