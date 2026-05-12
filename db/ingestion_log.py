import logging

import requests

from db.client import SupabaseClient

LOG = logging.getLogger(__name__)


def get_existing_log(client: SupabaseClient, source: str, date_str: str) -> dict | None:
    """Returns the existing ingestion_log row for (source, date), or None."""
    try:
        rows = client.select(
            "ingestion_log",
            params={
                "source": f"eq.{source}",
                "date": f"eq.{date_str}",
                "select": "id,status,notes",
                "limit": "1",
            },
        )
        return rows[0] if rows else None
    except requests.HTTPError as e:
        LOG.warning(f"Could not query ingestion_log for ({source}, {date_str}): {e}")
        return None


def upsert_log(
    client: SupabaseClient,
    source: str,
    date_str: str,
    status: str,
    notes: str | None = None,
) -> None:
    """
    Check-before-insert to avoid duplicates (ingestion_log has no UNIQUE constraint).
    Updates existing row if found; inserts new row otherwise.
    """
    existing = get_existing_log(client, source, date_str)
    try:
        if existing:
            client.update(
                "ingestion_log",
                match={"id": existing["id"]},
                data={"status": status, "notes": notes},
            )
            LOG.debug(f"  ingestion_log UPDATED: {source} {date_str} -> {status}")
        else:
            client.insert(
                "ingestion_log",
                [{"source": source, "date": date_str, "status": status, "notes": notes}],
            )
            LOG.debug(f"  ingestion_log INSERTED: {source} {date_str} -> {status}")
    except requests.HTTPError as e:
        LOG.warning(
            f"Failed to write ingestion_log ({source}, {date_str}, {status}): "
            f"{e.response.status_code} {e.response.text[:200]}"
        )
