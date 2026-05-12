import datetime as dt
from datetime import date, timedelta, timezone


def today_utc() -> date:
    return dt.datetime.now(timezone.utc).date()


def prev_business_day(d: date) -> date:
    """Returns the most recent weekday strictly before d."""
    d = d - timedelta(days=1)
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d -= timedelta(days=1)
    return d


def is_stale(scraped_date_str: str | None, reference_date: date) -> bool:
    """
    EIA publishes prices with a 1-business-day lag (e.g. Monday shows Friday).
    Data is stale only if it's older than the most recent business day before today.
    """
    if not scraped_date_str:
        return True
    try:
        scraped = date.fromisoformat(scraped_date_str)
        expected = prev_business_day(reference_date)
        return scraped < expected
    except (ValueError, TypeError):
        return True


def last_n_business_days(reference_date: date, n: int = 5) -> list[date]:
    """Returns the last n weekdays strictly before reference_date, most recent first."""
    result = []
    d = reference_date - timedelta(days=1)
    while len(result) < n:
        if d.weekday() < 5:  # Mon=0 ... Fri=4
            result.append(d)
        d -= timedelta(days=1)
    return result
