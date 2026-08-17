from canopy.street_name import extract_street_name


def test_extract_street_name_rentcast_style():
    assert extract_street_name("627 Jennings Dr, Wilmington, NC 28403") == "Jennings Dr"


def test_extract_street_name_zillow_style():
    assert extract_street_name("126 Parkwood Drive, Wilmington, NC") == "Parkwood Drive"


def test_extract_street_name_letter_suffixed_house_number():
    assert extract_street_name("4B Forest Hills Dr, Wilmington, NC") == "Forest Hills Dr"


def test_extract_street_name_no_house_number():
    # a "plan" listing with no fixed street address (canopy/email_ingest.py) --
    # nothing to strip, so the first segment passes through as-is
    assert extract_street_name("Mimosa Plan, Riverlights, Wilmington, NC") == "Mimosa Plan"


def test_extract_street_name_none_input():
    assert extract_street_name(None) is None


def test_extract_street_name_empty_string():
    assert extract_street_name("") is None
