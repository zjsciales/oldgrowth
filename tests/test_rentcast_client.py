import json
from pathlib import Path

import pytest
import responses

from canopy.clients.rentcast import RentCastError, fetch_sale_listings_for_zip

FIXTURE = Path(__file__).parent / "fixtures" / "rentcast_sale_listings_28409.json"


@responses.activate
def test_fetch_sale_listings_for_zip_single_page(monkeypatch):
    monkeypatch.setattr("canopy.clients.rentcast.RENTCAST_API_KEY", "test-key")
    data = json.loads(FIXTURE.read_text())
    responses.add(
        responses.GET,
        "https://api.rentcast.io/v1/listings/sale",
        json=data,
        status=200,
    )

    result = fetch_sale_listings_for_zip("28409")

    assert len(result) == 2
    assert result[0]["zipCode"] == "28409"
    assert len(responses.calls) == 1


@responses.activate
def test_fetch_sale_listings_paginates_until_short_page(monkeypatch):
    monkeypatch.setattr("canopy.clients.rentcast.RENTCAST_API_KEY", "test-key")
    monkeypatch.setattr("canopy.clients.rentcast.PAGE_SIZE", 2)
    data = json.loads(FIXTURE.read_text())

    responses.add(responses.GET, "https://api.rentcast.io/v1/listings/sale", json=data, status=200)
    responses.add(responses.GET, "https://api.rentcast.io/v1/listings/sale", json=[], status=200)

    result = fetch_sale_listings_for_zip("28409")

    assert len(result) == 2
    assert len(responses.calls) == 2


def test_fetch_sale_listings_requires_api_key(monkeypatch):
    monkeypatch.setattr("canopy.clients.rentcast.RENTCAST_API_KEY", "")
    with pytest.raises(RentCastError):
        fetch_sale_listings_for_zip("28409")


@responses.activate
def test_fetch_sale_listings_raises_on_error_status(monkeypatch):
    monkeypatch.setattr("canopy.clients.rentcast.RENTCAST_API_KEY", "test-key")
    responses.add(
        responses.GET,
        "https://api.rentcast.io/v1/listings/sale",
        json={"error": "rate limited"},
        status=429,
    )
    with pytest.raises(RentCastError):
        fetch_sale_listings_for_zip("28409")
