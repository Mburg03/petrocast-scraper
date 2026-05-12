import json
import logging

from db.client import SupabaseClient

LOG = logging.getLogger(__name__)


def upload_audit(
    client: SupabaseClient,
    bucket: str,
    date_str: str,
    payload: dict,
) -> bool:
    """
    Uploads the daily audit payload as JSON to Supabase Storage.
    Path format: YYYY/MM/YYYY-MM-DD_scrape.json

    Auto-creates the bucket on first run if it doesn't exist.
    Returns True on success, False on failure (non-fatal — caller logs and continues).
    """
    yyyy_mm = date_str[:7].replace("-", "/")
    path = f"{yyyy_mm}/{date_str}_scrape.json"
    data = json.dumps(payload, indent=2, default=str).encode()

    result = client.storage_upload(bucket, path, data)
    if result["ok"]:
        LOG.info(f"  Audit uploaded → {bucket}/{path}")
        return True

    body_lower = result["body"].lower()
    bucket_missing = (
        result["status"] in (400, 404)
        or "not found" in body_lower
        or "does not exist" in body_lower
        or "no such" in body_lower
    )

    if bucket_missing:
        LOG.info(f"  Bucket '{bucket}' not found — creating...")
        created = client.storage_create_bucket(bucket, public=False)
        if created:
            result2 = client.storage_upload(bucket, path, data)
            if result2["ok"]:
                LOG.info(f"  Audit uploaded → {bucket}/{path} (after bucket creation)")
                return True
            LOG.warning(
                f"  Upload failed after bucket creation: "
                f"{result2['status']} {result2['body'][:200]}"
            )
        else:
            LOG.warning(f"  Failed to create bucket '{bucket}'")
    else:
        LOG.warning(
            f"  Storage upload failed: {result['status']} {result['body'][:200]}"
        )

    return False
