"""RentCast API client, scoped to the /listings/sale endpoint.

One call per target zip returns all matching listings in that zip (paginated
in batches of up to 500), which is what keeps the free tier (50 calls/month)
viable per docs/ARCHITECTURE.md. Never call this per-property.
"""

import requests

from canopy.config import RENTCAST_API_KEY

BASE_URL = "https://api.rentcast.io/v1"
PAGE_SIZE = 500


class RentCastError(RuntimeError):
    pass


def fetch_sale_listings_for_zip(zip_code: str, status: str = "Active") -> list[dict]:
    """Fetch all sale listings for a zip code, paginating until exhausted.

    Returns the raw list of listing dicts as returned by RentCast. Counts as
    one or more calls against the monthly budget (one per page, usually one
    page per zip given typical Wilmington inventory).
    """
    if not RENTCAST_API_KEY:
        raise RentCastError("RENTCAST_API_KEY is not set")

    headers = {"X-Api-Key": RENTCAST_API_KEY, "Accept": "application/json"}
    listings: list[dict] = []
    offset = 0

    while True:
        resp = requests.get(
            f"{BASE_URL}/listings/sale",
            headers=headers,
            params={
                "zipCode": zip_code,
                "status": status,
                "limit": PAGE_SIZE,
                "offset": offset,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise RentCastError(
                f"RentCast request failed ({resp.status_code}) for zip {zip_code}: {resp.text}"
            )

        page = resp.json()
        if not isinstance(page, list):
            raise RentCastError(f"Unexpected RentCast response shape for zip {zip_code}: {page!r}")

        listings.extend(page)

        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return listings
