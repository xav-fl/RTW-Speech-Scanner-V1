"""NASA -- an open WordPress REST API with a working date window.

The `press-release` post type is the Administrator-level stream. The ordinary
`post` type is far larger (9,287 against 776 in an unfiltered count) and is
mostly mission and science features, so it is deliberately not collected: this
project wants what the agency head said, not everything the agency published.

Verified against a control query: `after`/`before` reduce `press-release` from
9,287 items to the 153 published between 2026-01-01 and 2026-07-31, returned in
date order. See `_wordpress.WordPressAdapter._verify_window`.
"""

from __future__ import annotations

from ._wordpress import WordPressAdapter


class NasaAdapter(WordPressAdapter):
    institution_id = "us-nasa"
    agency = "National Aeronautics and Space Administration"
    base_url = "https://www.nasa.gov"
    post_type = "press-release"
    newsroom_url = "https://www.nasa.gov/news-release/"
    feed_url = "https://www.nasa.gov/wp-json/wp/v2/press-release"

    label_map = {
        "press-release": "press_release",
        "post": "other",
        "feature": "other",
    }
