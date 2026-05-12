import logging
from datetime import datetime, timezone

import requests

from db.client import SupabaseClient

LOG = logging.getLogger(__name__)

SOURCE_TO_REF_COL = {
    "WTI":  "wti_reference",
    "RBOB": "rbob_reference",
    "ULSD": "ulsd_reference",
}


def recalculate_for_date(
    client: SupabaseClient,
    date_str: str,
    sources_inserted: list[str],
) -> int:
    """
    For every quincena in official_prices whose period contains date_str,
    recomputes the reference averages only for the sources that were successfully
    inserted. Returns the count of quincenas updated.
    """
    if not sources_inserted:
        return 0

    try:
        quincenas = client.select(
            "official_prices",
            params={
                "period_start": f"lte.{date_str}",
                "period_end":   f"gte.{date_str}",
                "deleted_at":   "is.null",
                "select":       "id,label,period_start,period_end",
                "order":        "period_start.asc",
            },
        )
    except requests.HTTPError as e:
        LOG.warning(f"Could not query official_prices: {e}")
        return 0

    if not quincenas:
        LOG.info(
            "  No active quincena covers today — 0 references updated "
            "(expected if DGEHM hasn't published the current period yet)"
        )
        return 0

    LOG.info(f"  Quincenas afectadas: {len(quincenas)}")

    q_date_min = min(q["period_start"] for q in quincenas)
    q_date_max = max(q["period_end"] for q in quincenas)

    try:
        intl = client.select_range(
            "international_prices",
            params={
                "date":       f"gte.{q_date_min}",
                "deleted_at": "is.null",
                "select":     "source,date,close_price",
            },
        )
        intl = [p for p in intl if p["date"] <= q_date_max]
    except requests.HTTPError as e:
        LOG.warning(f"Could not load international_prices for reference recalculation: {e}")
        return 0

    updated = 0
    for q in quincenas:
        p_start = q["period_start"]
        p_end   = q["period_end"]
        label   = q.get("label", f"{p_start}/{p_end}")

        period_prices = [p for p in intl if p_start <= p["date"] <= p_end]
        update_data: dict[str, float] = {}

        for source in sources_inserted:
            col = SOURCE_TO_REF_COL.get(source)
            if not col:
                continue
            vals = [
                float(p["close_price"])
                for p in period_prices
                if p["source"] == source
            ]
            if vals:
                avg = round(sum(vals) / len(vals), 4)
                update_data[col] = avg
                update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                LOG.info(f"  {label}: {col} = {avg} (n={len(vals)})")
            else:
                LOG.info(f"  {label}: {source} — no data in period, skipping {col}")

        if not update_data:
            continue

        try:
            client.update("official_prices", match={"id": q["id"]}, data=update_data)
            updated += 1
        except requests.HTTPError as e:
            LOG.warning(
                f"  Failed to update references for '{label}': "
                f"{e.response.status_code} {e.response.text[:200]}"
            )

    return updated
