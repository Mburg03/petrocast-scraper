"""
PetroCast — EIA Daily Scraper
==============================
Railway Cron service. Runs Mon–Fri at 17:00 UTC.

Pipeline:
  1. Scrape EIA prices (WTI, RBOB GC, ULSD GC)
  2. Stale-date detection with one retry (30 min wait)
  3. Upsert each source into international_prices
  4. Log each source in ingestion_log (check-before-insert)
  5. Recalculate wti/rbob/ulsd_reference in official_prices for active quincena
  6. Gap detection — warn on missing records in last 5 business days
  7. Upload daily JSON audit to Supabase Storage (non-fatal)

Exit codes:
  0 — all handled outcomes (success, partial, holiday, missing, network error)
  1 — EIA page structure changed; human intervention required
"""

import logging
import sys
import time

from db.client import SupabaseClient
from db.ingestion_log import upsert_log
from db.international_prices import detect_gaps, upsert_price
from db.official_prices import recalculate_for_date
from notifier.telegram import notify
from scraper.eia import ScrapeResult, scrape
from scraper.storage import upload_audit
from utils.config import load_config
from utils.dates import is_stale, prev_business_day, today_utc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
LOG = logging.getLogger(__name__)

# Maps ScrapeResult field names to Supabase price_source_enum values
SOURCE_MAP: dict[str, str] = {
    "wti":     "WTI",
    "rbob_gc": "RBOB",
    "ulsd_gc": "ULSD",
}

# Soft-warning price ranges. None means no bound in that direction.
# WTI has no lower bound — negative prices are valid (April 2020: -$36.98).
PRICE_RANGES: dict[str, tuple[float | None, float | None]] = {
    "WTI":  (None, 200.0),
    "RBOB": (1.0,  10.0),
    "ULSD": (1.0,  10.0),
}


def validate_price(source: str, price: float) -> tuple[bool, str | None]:
    """
    Returns (is_suspicious, message).
    is_suspicious=True triggers data_quality="suspicious" in the audit.
    Negative WTI is flagged informatively but not treated as suspicious.
    """
    if source == "WTI" and price < 0:
        return False, f"WTI negativo ({price}) — válido (precedente abril 2020)"

    lo, hi = PRICE_RANGES.get(source, (None, None))
    if lo is not None and price < lo:
        return True, f"${price} below expected minimum ${lo} for {source}"
    if hi is not None and price > hi:
        return True, f"${price} above expected maximum ${hi} for {source}"

    return False, None


def _log_all_sources_error(
    client: SupabaseClient,
    date_str: str,
    message: str,
    dry_run: bool,
) -> None:
    for source in ["WTI", "RBOB", "ULSD"]:
        if not dry_run:
            upsert_log(client, source, date_str, "error", message)


def run(dry_run: bool = False) -> int:
    cfg = load_config()
    run_date = today_utc()
    run_date_str = run_date.isoformat()

    LOG.info(f"=== PetroCast EIA Scraper — {run_date_str} ===")
    if dry_run:
        LOG.info("DRY RUN MODE — no DB writes will be made")

    client = SupabaseClient(cfg.supabase_url, cfg.supabase_service_role_key)

    # ── Step 1: Scrape ────────────────────────────────────────────────────────
    LOG.info("Scraping EIA Today in Energy...")
    result = scrape()

    # ── Step 2: Hard errors ───────────────────────────────────────────────────
    if result.status == "error":
        if result.error_type == "structure_change":
            LOG.error(
                f"EIA page structure changed — code fix required: {result.error_message}"
            )
            _log_all_sources_error(
                client, run_date_str,
                f"EIA page structure changed: {result.error_message}",
                dry_run,
            )
            notify(
                cfg.telegram_bot_token, cfg.telegram_chat_id,
                date_str=run_date_str, outcome="critical",
                error_message=result.error_message,
            )
            return 1  # Non-zero exit: Railway signals that human attention is needed

        LOG.warning(f"Network error scraping EIA: {result.error_message}")
        _log_all_sources_error(client, run_date_str, result.error_message or "network error", dry_run)
        notify(
            cfg.telegram_bot_token, cfg.telegram_chat_id,
            date_str=run_date_str, outcome="error",
            error_message=result.error_message,
        )
        return 0

    # ── Step 3: Stale-date detection with one retry ───────────────────────────
    # EIA lags 1 business day (Monday shows Friday). is_stale only triggers
    # when data is older than the previous business day (e.g. EIA missed an update).
    if is_stale(result.date, run_date):
        expected = prev_business_day(run_date).isoformat()
        LOG.warning(
            f"EIA shows {result.date}, expected >= {expected} — data is stale. "
            f"Waiting {cfg.retry_wait_seconds}s before retry..."
        )
        if not dry_run:
            time.sleep(cfg.retry_wait_seconds)
        else:
            LOG.info("[DRY RUN] Skipping sleep")

        LOG.info("Retrying scrape...")
        result = scrape()

        still_stale = result.status == "error" or is_stale(result.date, run_date)
        if still_stale:
            LOG.warning(
                f"Still stale/error after retry — logging as 'missing' for {run_date_str}"
            )
            for source in ["WTI", "RBOB", "ULSD"]:
                if not dry_run:
                    upsert_log(
                        client, source, run_date_str, "missing",
                        f"EIA data not updated after retry (showed {result.date or 'error'})",
                    )
            audit_payload = {
                "run_date": run_date_str,
                "outcome": "missing",
                "scraped_date": result.date,
                "prices": {},
                "sources_inserted": [],
                "gaps_detected": [],
            }
            if not dry_run:
                upload_audit(client, cfg.storage_bucket, run_date_str, audit_payload)
            notify(
                cfg.telegram_bot_token, cfg.telegram_chat_id,
                date_str=run_date_str, outcome="missing",
                error_message=f"EIA data not updated after retry (showed {result.date or 'error'})",
            )
            return 0

    LOG.info(
        f"EIA date: {result.date} | "
        f"WTI={result.wti} RBOB={result.rbob_gc} ULSD={result.ulsd_gc}"
    )

    # ── Step 4: Upsert each source ────────────────────────────────────────────
    sources_inserted: list[str] = []
    audit_prices: dict[str, dict] = {}

    for field, source in SOURCE_MAP.items():
        price: float | None = getattr(result, field)

        if price is None:
            LOG.warning(f"  {source}: not found in EIA table — logging as error")
            if not dry_run:
                upsert_log(client, source, result.date, "error", "Price not found in EIA table")
            continue

        is_suspicious, warning_msg = validate_price(source, price)

        if warning_msg:
            if is_suspicious:
                LOG.warning(f"  {source}: OUTLIER WARNING — {warning_msg}")
            else:
                LOG.info(f"  {source}: NOTE — {warning_msg}")

        data_quality = "suspicious" if is_suspicious else "provisional"

        if dry_run:
            LOG.info(
                f"  [DRY RUN] Would upsert {source} {result.date} = {price} "
                f"({data_quality})"
            )
            sources_inserted.append(source)
            audit_prices[source] = {"price": price, "data_quality": data_quality}
            continue

        success = upsert_price(client, source, result.date, price)
        if success:
            upsert_log(
                client, source, result.date, "received",
                notes=warning_msg,
            )
            sources_inserted.append(source)
            audit_prices[source] = {"price": price, "data_quality": data_quality}
        else:
            upsert_log(
                client, source, result.date, "error",
                notes="DB insert/update failed",
            )

    # ── Step 5: Recalculate official_prices references ────────────────────────
    quincenas_updated = 0
    if sources_inserted:
        LOG.info(
            f"Recalculating official_prices references for {result.date} "
            f"(sources: {sources_inserted})..."
        )
        if not dry_run:
            quincenas_updated = recalculate_for_date(client, result.date, sources_inserted)
            LOG.info(f"  Quincenas updated: {quincenas_updated}")
        else:
            LOG.info(f"  [DRY RUN] Would recalculate for: {sources_inserted}")
    else:
        LOG.warning("No sources inserted — skipping reference recalculation")

    # ── Step 6: Gap detection ─────────────────────────────────────────────────
    LOG.info("Running gap detection (last 5 business days)...")
    gaps = detect_gaps(client, run_date_str)
    if gaps:
        for g in gaps:
            LOG.warning(
                f"  GAP DETECTED: {g['source']} missing for {g['date']} — manual fill required"
            )
    else:
        LOG.info("  No gaps detected")

    # ── Step 7: Upload audit JSON ─────────────────────────────────────────────
    outcome = (
        "success" if len(sources_inserted) == 3
        else "partial" if sources_inserted
        else "error"
    )
    audit_payload = {
        "run_date": run_date_str,
        "scraped_date": result.date,
        "outcome": outcome,
        "prices": audit_prices,
        "sources_inserted": sources_inserted,
        "gaps_detected": gaps,
        "scraped_at": result.scraped_at,
    }

    if not dry_run:
        LOG.info("Uploading audit to Supabase Storage...")
        upload_audit(client, cfg.storage_bucket, run_date_str, audit_payload)
    else:
        import json
        LOG.info(f"  [DRY RUN] Audit payload:\n{json.dumps(audit_payload, indent=2)}")

    notify(
        cfg.telegram_bot_token, cfg.telegram_chat_id,
        date_str=run_date_str,
        outcome=outcome,
        prices=audit_prices,
        sources_inserted=sources_inserted,
        gaps=gaps,
        quincenas_updated=quincenas_updated,
    )

    LOG.info(f"=== Done — outcome: {outcome} | sources inserted: {sources_inserted} ===")
    return 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    sys.exit(run(dry_run=dry_run))
