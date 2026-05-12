"""
Telegram notification for daily scraper results.
Optional — silently skipped if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not set.
"""

import logging

import requests

LOG = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"

OUTCOME_ICON = {
    "success":  "✅",
    "partial":  "⚠️",
    "missing":  "⚠️",
    "error":    "❌",
    "critical": "🚨",
}

SOURCE_UNIT = {
    "WTI":  "bbl",
    "RBOB": "gal",
    "ULSD": "gal",
}


def _build_message(
    date_str: str,
    outcome: str,
    prices: dict,
    sources_inserted: list[str],
    gaps: list[dict],
    quincenas_updated: int,
    error_message: str | None = None,
) -> str:
    icon = OUTCOME_ICON.get(outcome, "❓")
    lines = [f"<b>{icon} PetroCast Scraper — {date_str}</b>"]

    if outcome in ("success", "partial"):
        lines.append("")
        lines.append("💰 <b>Precios del día:</b>")
        for source in ["WTI", "RBOB", "ULSD"]:
            unit = SOURCE_UNIT[source]
            if source in sources_inserted and source in prices:
                price = prices[source]["price"]
                quality = prices[source].get("data_quality", "provisional")
                flag = " ⚠️ outlier" if quality == "suspicious" else ""
                lines.append(f"  {source}:  <code>${price:.2f}/{unit}</code>{flag}")
            else:
                lines.append(f"  {source}:  <i>no encontrado</i>")

        lines.append("")
        lines.append(f"📊 Quincenas actualizadas: {quincenas_updated}")

        if gaps:
            lines.append(f"🔍 Gaps detectados: {len(gaps)}")
            for g in gaps:
                lines.append(f"   • {g['source']} — {g['date']}")
        else:
            lines.append("🔍 Gaps detectados: 0")

    elif outcome == "missing":
        lines.append("")
        lines.append("EIA no actualizó datos después del retry.")
        if error_message:
            lines.append(f"<i>{error_message}</i>")

    elif outcome == "critical":
        lines.append("")
        lines.append("La estructura de la página EIA cambió.")
        lines.append("Se requiere intervención manual.")
        if error_message:
            lines.append(f"<i>{error_message}</i>")

    else:  # generic error
        lines.append("")
        lines.append("Error de red al contactar EIA.")
        if error_message:
            lines.append(f"<i>{error_message}</i>")

    return "\n".join(lines)


def notify(
    bot_token: str,
    chat_id: str,
    date_str: str,
    outcome: str,
    prices: dict | None = None,
    sources_inserted: list[str] | None = None,
    gaps: list[dict] | None = None,
    quincenas_updated: int = 0,
    error_message: str | None = None,
) -> bool:
    """
    Sends a Telegram message with the daily scraper result.
    Returns True on success, False on failure (non-fatal).
    Silently skips if bot_token or chat_id are empty.
    """
    if not bot_token or not chat_id:
        return False

    message = _build_message(
        date_str=date_str,
        outcome=outcome,
        prices=prices or {},
        sources_inserted=sources_inserted or [],
        gaps=gaps or [],
        quincenas_updated=quincenas_updated,
        error_message=error_message,
    )

    try:
        resp = requests.post(
            API_URL.format(token=bot_token),
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if resp.ok:
            LOG.info("  Telegram notification sent")
            return True
        LOG.warning(f"  Telegram API error: {resp.status_code} {resp.text[:200]}")
        return False
    except requests.RequestException as e:
        LOG.warning(f"  Telegram notification failed: {e}")
        return False
