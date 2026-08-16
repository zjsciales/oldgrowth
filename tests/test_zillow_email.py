from pathlib import Path

import pytest

from canopy.clients.zillow_email import ZillowParseError, parse_zillow_alert_email

FIXTURES = Path(__file__).parent / "fixtures"
RECOMMENDATIONS = FIXTURES / "zillow_alert_recommendations.eml"
SAVED_SEARCH = FIXTURES / "zillow_alert_saved_search.eml"


def test_parses_all_listings_in_recommendations_email():
    listings = parse_zillow_alert_email(RECOMMENDATIONS.read_bytes())

    assert len(listings) == 10
    zpids = {item["zpid"] for item in listings}
    assert zpids == {
        "457889881", "54343943", "54334416", "54341354", "54327931",
        "54324974", "54334168", "84698951", "337951985", "337951671",
    }


def test_photo_url_correlated_to_correct_listing_by_zpid_recommendations():
    listings = parse_zillow_alert_email(RECOMMENDATIONS.read_bytes())

    mimosa = next(item for item in listings if item["zpid"] == "457889881")
    myrtle_grove = next(item for item in listings if item["zpid"] == "54343943")

    assert mimosa["photo_url"] == (
        "https://photos.zillowstatic.com/fp/113e6e5d1d4dafa5a4b49d1b7e0d7f38-zui_propcard_md_488_392.jpg"
    )
    assert myrtle_grove["photo_url"] == (
        "https://photos.zillowstatic.com/fp/5c1dbdab335c991a115e46e69525071d-zui_propcard_md_488_392.jpg"
    )
    # every listing in this fixture has a distinct, non-null photo
    photo_urls = [item["photo_url"] for item in listings]
    assert None not in photo_urls
    assert len(set(photo_urls)) == len(photo_urls)


def test_photo_url_correlated_to_correct_listing_by_zpid_saved_search():
    listings = parse_zillow_alert_email(SAVED_SEARCH.read_bytes())

    purviance = next(item for item in listings if item["zpid"] == "54340342")
    college_acres = next(item for item in listings if item["zpid"] == "54315964")

    assert purviance["photo_url"] == "https://photos.zillowstatic.com/fp/f40683e2147210fbc7cbcfdb663e07cb-p_e.jpg"
    assert college_acres["photo_url"] == "https://photos.zillowstatic.com/fp/74b4f0d0c6cf7e2a8f9ea419e1fa770c-p_i.jpg"


def test_new_construction_listing_flagged_and_multi_segment_address_parsed():
    listings = parse_zillow_alert_email(RECOMMENDATIONS.read_bytes())
    mimosa = next(item for item in listings if item["zpid"] == "457889881")

    assert mimosa["is_new_construction"] is True
    assert mimosa["formatted_address"] == "Mimosa Plan, Riverlights, Wilmington, NC"
    assert mimosa["city"] == "Wilmington"
    assert mimosa["price"] == 618000
    assert mimosa["bedrooms"] == 3.0
    assert mimosa["bathrooms"] == 4.0
    assert mimosa["square_footage"] == 2223


def test_price_cut_detected():
    listings = parse_zillow_alert_email(RECOMMENDATIONS.read_bytes())
    myrtle_grove = next(item for item in listings if item["zpid"] == "54343943")

    assert myrtle_grove["price"] == 335000
    assert myrtle_grove["price_cut"] is True


def test_regular_listing_has_brokerage_and_no_price_cut():
    listings = parse_zillow_alert_email(RECOMMENDATIONS.read_bytes())
    kelly_road = next(item for item in listings if item["zpid"] == "54334416")

    assert kelly_road["brokerage"] == "Intracoastal Realty Corporation"
    assert kelly_road["price_cut"] is False
    assert kelly_road["is_new_construction"] is False


def test_parses_saved_search_digest_email_with_open_house():
    listings = parse_zillow_alert_email(SAVED_SEARCH.read_bytes())

    assert len(listings) == 2
    purviance = next(item for item in listings if item["zpid"] == "54340342")
    assert purviance["has_open_house"] is True
    assert purviance["price"] == 825000
    assert purviance["formatted_address"] == "4105 Purviance Court, Wilmington, NC"

    college_acres = next(item for item in listings if item["zpid"] == "54315964")
    assert college_acres["has_open_house"] is False
    assert college_acres["brokerage"] == "Keller Williams Innovate-Wilmington"


def test_photo_url_none_when_message_has_no_html_part():
    plain_only = (
        b"Content-Type: text/plain\r\n\r\n"
        b"For sale\n\n$400,000\n3 bd | 2 ba | 1,500 sqft\n\n"
        b"1 Test St, Wilmington, NC\n\nView this listing -\nhttps://example.com/homedetails/12345_zpid/"
    )
    listings = parse_zillow_alert_email(plain_only)

    assert listings[0]["zpid"] == "12345"
    assert listings[0]["photo_url"] is None


def test_raises_on_message_with_no_text_plain_part():
    html_only = (
        b"Content-Type: text/html\r\n\r\n<html><body>no plain part</body></html>"
    )
    with pytest.raises(ZillowParseError):
        parse_zillow_alert_email(html_only)


def test_raises_on_message_with_no_listing_blocks():
    empty = (
        b"Content-Type: text/plain\r\n\r\nJust a note, no listings here at all."
    )
    with pytest.raises(ZillowParseError):
        parse_zillow_alert_email(empty)
