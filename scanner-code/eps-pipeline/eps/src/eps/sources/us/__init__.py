"""US agency adapters.

Twelve of the 24. The two originals -- Treasury and Education -- were written to
prove the interface against a JSON feed and an HTML listing. The other ten come
from the 22-agency survey (H-46 to H-52) and cover every agency reachable over
plain HTTP:

  feed     us-nasa, us-va, us-treasury
             an API that honours a date window server-side. NASA and VA share
             `_wordpress.WordPressAdapter`, which re-verifies that the window
             was actually applied -- see the warning in `state.py`.

  listing  us-dhs, us-education, us-gsa, us-hud, us-interior, us-opm,
           us-sba, us-state, us-usaid
             an HTML index, walked. `date_filter` is `server` where the site
             exposes a year facet (Interior, GSA) and `client` otherwise.

The twelve absent divide into three groups, and the reason differs:

  browser   us-agriculture, us-defense, us-hhs, us-labor, us-nrc, us-ssa
              well-formed listings that 403 every HTTP client. They need a
              browser-backed `Fetcher`, not a different adapter shape.
  awkward   us-energy, us-justice, us-nsf
              reachable, but paging over AJAX or behind an interstitial.
  blocked   us-commerce, us-epa, us-transportation
              see H-47 and H-52.

An agency with no entry here is still written to the screening log, as an
explicit `adapter_not_implemented` zero rather than a silent absence.
"""

from .agriculture import AgricultureAdapter
from .commerce import CommerceAdapter
from .defense import DefenseAdapter
from .dhs import DhsAdapter
from .education import EducationAdapter
from .energy import EnergyAdapter
from .epa import EpaAdapter
from .gsa import GsaAdapter
from .hhs import HhsAdapter
from .hud import HudAdapter
from .interior import InteriorAdapter
from .justice import JusticeAdapter
from .labor import LaborAdapter
from .nasa import NasaAdapter
from .nsf import NsfAdapter
from .opm import OpmAdapter
from .sba import SbaAdapter
from .ssa import SsaAdapter
from .state import StateAdapter
from .transportation import TransportationAdapter
from .treasury import TreasuryAdapter
from .usaid import UsaidAdapter
from .va import VaAdapter

_CLASSES = (
    TreasuryAdapter, EducationAdapter,
    NasaAdapter, VaAdapter,
    DhsAdapter, GsaAdapter, HudAdapter, InteriorAdapter, OpmAdapter,
    SbaAdapter, StateAdapter, UsaidAdapter,
    # transport: needs ImpersonatingFetcher (see sources/transport.py)
    AgricultureAdapter, HhsAdapter, LaborAdapter,
    SsaAdapter, TransportationAdapter,
    # transport: needs BrowserFetcher and a person to clear a challenge.
    # Registered so `scripts/desktop_harvest.py` can run them; a normal
    # harvest logs them as listing_unreachable, which is accurate.
    CommerceAdapter, EpaAdapter,
    # transport: index from archived captures, bodies live (see epa.py).
    NsfAdapter, JusticeAdapter, EnergyAdapter,
    # from the Archive, but energy.gov article pages are client-rendered: the
    # prose appears only inside <meta> description tags, and the one
    # ield--name-body div on the page is a 288-byte sidebar promo reading
    # "Funding Opportunities". A run collected 102 documents of exactly that.
    # Needs BrowserFetcher; see H-81.
    # DefenseAdapter is written and still NOT registered. H-67 refused it
    # because the LIVE listing is Vue-rendered; the archived captures turn out
    # to be the same shell. Across 181 captures it enumerates 69 documents and
    # ZERO press releases, from the page that IS the press-release listing.
    # An agency present with the wrong 69 documents is worse than one absent.
)

#: institution_id -> adapter class. `harvest_us.py` reads this.
ADAPTERS = {cls.institution_id: cls for cls in _CLASSES}

__all__ = ["ADAPTERS"] + [c.__name__ for c in _CLASSES]
