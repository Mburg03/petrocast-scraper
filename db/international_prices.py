import logging
from datetime import date

import requests

from db.client import SupabaseClient
from utils.dates import last_n_business_days

LOG = logging.getLogger(__name__)

# (lower_bound, upper_bound) — None means no bound in that direction.
# WTI has no lower bound: negative prices are valid (April 2020 precedent).
OUTLIER_RANGES: dict[str, tuple[float | None, float | None]] = {
    "WTI":  (None, 200.0),
    "RBOB": (1.0,  10.0),
    "ULSD": (1.0,  10.0),
}


def upsert_price(
    client: SupabaseClient, source: str, date_str: str, close_price: float
) -> bool:
    """
    SELECT first; UPDATE if row exists, INSERT if not.
    Returns True on success, False on DB error.
    """
    try:
        rows = client.select(
            "international_prices",
            params={
                "source": f"eq.{source}",
                "date": f"eq.{date_str}",
                "deleted_at": "is.null",
                "select": "id",
                "limit": "1",
            },
        )
        if rows:
            client.update(
                "international_prices",
                match={"id": rows[0]["id"]},
                data={"close_price": close_price},
            )
            LOG.info(f"  {source} {date_str}: UPDATED close_price={close_price}")
        else:
            client.insert(
                "international_prices",
                [{"source": source, "date": date_str, "close_price": close_price}],
            )
            LOG.info(f"  {source} {date_str}: INSERTED close_price={close_price}")
        return True
    except requests.HTTPError as e:
        LOG.error(
            f"  {source} {date_str}: DB error — "
            f"{e.response.status_code} {e.response.text[:200]}"
        )
        return False


def detect_gaps(client: SupabaseClient, as_of_date: str) -> list[dict]:
    """
    Checks the last 5 business days before as_of_date.
    Returns list of {source, date} dicts for any missing records.
    """
    ref = date.fromisoformat(as_of_date)
    last_5 = last_n_business_days(ref, n=5)
    if not last_5:
        return []

    date_min = last_5[-1].isoformat()
    date_max = last_5[0].isoformat()

    try:
        existing = client.select_range(
            "international_prices",
            params={
                "date": f"gte.{date_min}",
                "deleted_at": "is.null",
                "select": "source,date",
            },
        )
        existing_set = {
            (r["source"], r["date"])
            for r in existing
            if r["date"] <= date_max
        }
    except requests.HTTPError as e:
        LOG.warning(f"Could not query international_prices for gap detection: {e}")
        return []

    gaps = []
    for d in last_5:
        for source in ["WTI", "RBOB", "ULSD"]:
            if (source, d.isoformat()) not in existing_set:
                gaps.append({"source": source, "date": d.isoformat()})
    return gaps
