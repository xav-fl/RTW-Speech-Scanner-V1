#!/usr/bin/env python3
"""Harvest the agencies that need a person at a browser, then merge them in.

WHO THIS IS FOR
---------------
Four agencies cannot be collected by any automated client:

    us-commerce   Cloudflare JavaScript challenge
    us-epa        interactive human-verification CAPTCHA
    us-energy     listing rendered client-side; ?page= is ignored
    us-nsf        listing paged over AJAX; ?page= is ignored

All four load normally in an ordinary desktop browser. This script opens one,
lets you clear whatever each site asks for, and then runs the ordinary harvest
through that same browser session.

    python scripts/desktop_harvest.py us-commerce us-epa

It MUST be run from a desktop session that can open a window. It will not work
over SSH, in a container, or from an agent sandbox: headless Chromium is
detected and refused by three of these four sites, which is the whole reason
this file exists.

WHAT IT DOES
------------
1. Opens a real Chromium window with a persistent profile
   (`~/.eps-browser-profile`), so a challenge cleared today is still cleared
   tomorrow.
2. Visits each agency's newsroom and waits for you to confirm it has loaded.
3. Runs `list_documents` and `fetch_document` for those agencies through the
   browser, writing to a scratch directory.
4. Merges the result into the main corpus with `merge_harvest.py`, leaving
   every other agency untouched.

Nothing here answers a challenge on your behalf. Step 2 is a person doing what
the site asked.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "src"))
sys.path.insert(0, SRC)

DEFAULT_CORPUS = os.path.normpath(os.path.join(
    HERE, "..", "..", "..", "..", "harvest-code", "us-harvest"))
DEFAULT_OFFICEHOLDERS = os.path.normpath(os.path.join(
    HERE, "..", "..", "..", "..", "harvest-code", "officeholders_2026.csv"))

#: Agencies this script is for, and the page a person has to see load.
BROWSER_AGENCIES = {
    "us-commerce": "https://www.commerce.gov/news/press-releases",
    "us-epa": "https://www.epa.gov/newsreleases/search",
    "us-energy": "https://www.energy.gov/newsroom",
    "us-nsf": "https://www.nsf.gov/news",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("agencies", nargs="*", default=["us-commerce", "us-epa"],
                    help="institution_ids (default: us-commerce us-epa)")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--officeholders", default=DEFAULT_OFFICEHOLDERS)
    ap.add_argument("--pause", type=float, default=0.8)
    ap.add_argument("--no-merge", action="store_true",
                    help="write the scratch run but do not merge it")
    args = ap.parse_args(argv)

    unknown = [a for a in args.agencies if a not in BROWSER_AGENCIES]
    if unknown:
        sys.exit("not browser-tier agencies: %s\nthis script is for: %s"
                 % (", ".join(unknown), ", ".join(sorted(BROWSER_AGENCIES))))

    from eps.sources.browser import BrowserFetcher, BrowserUnavailable

    print("Opening a browser window. Clear any challenge each site shows,")
    print("then come back here and press Enter.\n")
    fetcher = BrowserFetcher(pause=args.pause, headed=True)
    try:
        for slug in args.agencies:
            url = BROWSER_AGENCIES[slug]
            print("  %-14s %s" % (slug, url))
            try:
                fetcher.get_text(url)
                print("                 loaded cleanly")
            except BrowserUnavailable:
                raise
            except Exception as exc:                 # noqa: BLE001
                print("                 needs you: %s" % str(exc)[:70])
        input("\nPress Enter once every tab above has loaded properly... ")

        out_dir = os.path.join(tempfile.gettempdir(), "eps-desktop-harvest")
        os.makedirs(out_dir, exist_ok=True)
        rc = _run_harvest(args, out_dir, fetcher)
    finally:
        fetcher.close()

    if rc != 0 or args.no_merge:
        print("\nScratch run in %s (not merged)." % out_dir)
        return rc

    print("\nMerging into %s" % args.corpus)
    return subprocess.call([sys.executable,
                            os.path.join(HERE, "merge_harvest.py"),
                            out_dir, args.corpus])


def _run_harvest(args, out_dir, fetcher) -> int:
    """Run the ordinary harvest, but hand every adapter the browser fetcher."""
    from eps import harvest_us

    class BrowserPool:
        def for_agency(self, row):
            return fetcher

        def close(self):
            pass

    original = harvest_us.TransportPool
    harvest_us.TransportPool = lambda pause=0.0: BrowserPool()
    try:
        return harvest_us.harvest(argparse.Namespace(
            start=args.start, end=args.end, out=out_dir,
            agencies=harvest_us.DEFAULT_CONFIG,
            officeholders=args.officeholders,
            only=",".join(args.agencies), pause=args.pause,
        ))
    finally:
        harvest_us.TransportPool = original


if __name__ == "__main__":
    raise SystemExit(main())
