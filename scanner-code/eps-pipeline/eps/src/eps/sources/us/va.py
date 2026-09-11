"""Department of Veterans Affairs -- WordPress REST API on news.va.gov.

Same shape as NASA, one open question recorded rather than decided here.

VA splits its output across two post types and the split is lopsided in the
window: `news-releases` holds 46 items, the ordinary `post` type holds 522.
Only `news-releases` is collected, on the same reasoning applied to NASA -- it
is the agency's own designation for a press release, and the wider stream is
mostly VA health and benefits explainers written by staff rather than statements
by the Secretary.

Whether the wider stream is in scope is a PI decision, not a collection one
(survey note, `config/us_agencies.csv`). If the answer is yes, the change is one
line: set `post_type = "posts"` on a second adapter and union the two, exactly
as Treasury unions its categories. Nothing here forecloses that.
"""

from __future__ import annotations

from ._wordpress import WordPressAdapter


class VaAdapter(WordPressAdapter):
    institution_id = "us-va"
    agency = "Department of Veterans Affairs"
    base_url = "https://news.va.gov"
    post_type = "news-releases"
    newsroom_url = "https://news.va.gov/press-room/"
    feed_url = "https://news.va.gov/wp-json/wp/v2/news-releases"

    label_map = {
        "news-releases": "press_release",
        "post": "other",
    }
