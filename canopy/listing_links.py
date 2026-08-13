"""External reference links for a listing -- no scraping, just handing
the rater a URL to click through to on Zillow/Redfin/Realtor.com/the
local MLS/etc. themselves. RentCast's sale-listings payload has no
photo or listing-detail URL field (confirmed against real ingested
data), and docs/CLAUDE.md explicitly rules out scraping those sites --
or Google Images/Search results -- to fill that gap ourselves. A plain
search link respects everyone's ToS: the rater's own browser does a
normal Google search, we never fetch or store anyone else's content."""

import urllib.parse

NHC_RECORDS_SEARCH_URL = "https://tax.nhcgov.com/436/Records-Search"


def satellite_url(latitude: float, longitude: float) -> str:
    return f"https://www.google.com/maps/@{latitude},{longitude},19z/data=!3m1!1e3"


def listing_search_url(address: str) -> str:
    """Zillow/Redfin/Realtor.com/the local MLS listing page all typically
    rank at the top of a plain Google search for a specific property
    address -- real photos and comprehensive listing details, without us
    hosting or scraping anything."""
    query = urllib.parse.quote(f'"{address}" real estate listing')
    return f"https://www.google.com/search?q={query}"
