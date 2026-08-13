from canopy.listing_links import NHC_RECORDS_SEARCH_URL, listing_search_url, satellite_url


def test_listing_search_url_quotes_the_address():
    url = listing_search_url("109 And 113 Clay St, Wilmington, NC 28405")

    assert url.startswith("https://www.google.com/search?q=")
    assert "109%20And%20113%20Clay%20St" in url


def test_satellite_url_embeds_coordinates():
    url = satellite_url(34.165672, -77.927776)

    assert url == "https://www.google.com/maps/@34.165672,-77.927776,19z/data=!3m1!1e3"


def test_nhc_records_search_url_is_a_real_working_link():
    assert NHC_RECORDS_SEARCH_URL == "https://tax.nhcgov.com/436/Records-Search"
