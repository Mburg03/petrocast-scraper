"""
EIA Today in Energy — Daily Price Scraper
==========================================
Fetches WTI, RBOB Gulf Coast, and Low-Sulfur Diesel Gulf Coast
from https://www.eia.gov/todayinenergy/prices.php

Returns a ScrapeResult dataclass. No CLI logic, no CSV, no DB writes.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

URL = "https://www.eia.gov/todayinenergy/prices.php"

HEADERS = {
    "User-Agent": "PetroCast/1.0 (Fuel Price Analysis; petrocastservices@outlook.com)"
}

PRODUCT_MAP = {
    "crude oil": "crude_oil",
    "gasoline (rbob)": "rbob",
    "gasoline(rbob)": "rbob",
    "low-sulfur diesel": "ulsd",
    "low sulfur diesel": "ulsd",
    "heating oil": "heating_oil",
    "crack spread": "crack_spread",
    "propane": "propane",
}


@dataclass
class ScrapeResult:
    date: str | None          # "YYYY-MM-DD" or None
    wti: float | None
    rbob_gc: float | None
    ulsd_gc: float | None
    scraped_at: str           # ISO 8601 UTC
    status: str               # "success" | "partial" | "error"
    error_type: str | None    # "network" | "structure_change" | None
    error_message: str | None


def fetch_page() -> str:
    resp = requests.get(URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse_date(date_str: str) -> str | None:
    """'3/16/26' -> '2026-03-16'"""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
            y = y + 2000 if y < 50 else y + 1900
            return f"{y:04d}-{m:02d}-{d:02d}"
    except (ValueError, IndexError):
        pass
    return date_str


def detect_product(text: str) -> str | None:
    t = text.lower().strip()
    for keyword, pid in PRODUCT_MAP.items():
        if keyword in t:
            return pid
    return None


def parse_prices(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    target_table = None
    date_label = None

    for table in soup.find_all("table"):
        if table.get("summary", "").lower().startswith("spot petroleum"):
            target_table = table
            break
        header = table.find("b")
        if header and "Wholesale Spot Petroleum Prices" in header.get_text():
            target_table = table
            break

    if not target_table:
        raise ValueError("Tabla 'Wholesale Spot Petroleum Prices' no encontrada")

    header_b = target_table.find("b")
    if header_b:
        header_text = header_b.get_text()
        if "," in header_text:
            date_part = header_text.split(",")[1].strip()
            date_label = date_part.replace("Close", "").strip()

    current_product = None
    all_prices: dict[str, float] = {}

    for row in target_table.find_all("tr"):
        if not row.find_all("td"):
            continue

        s1_cell = row.find("td", class_="s1")
        s2_cell = row.find("td", class_="s2")
        d1_cell = row.find("td", class_="d1")

        if s1_cell:
            detected = detect_product(s1_cell.get_text(strip=True))
            if detected:
                current_product = detected

        if s2_cell and d1_cell and current_product:
            area = s2_cell.get_text(strip=True)
            price_str = d1_cell.get_text(strip=True)
            if area and price_str and price_str != "NA":
                try:
                    all_prices[f"{current_product}|{area}"] = float(price_str)
                except ValueError:
                    pass

    return {
        "date": parse_date(date_label),
        "wti": all_prices.get("crude_oil|WTI"),
        "rbob_gc": all_prices.get("rbob|Gulf Coast"),
        "ulsd_gc": all_prices.get("ulsd|Gulf Coast"),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def scrape() -> ScrapeResult:
    now = datetime.now(timezone.utc).isoformat()
    try:
        html = fetch_page()
        data = parse_prices(html)
        all_present = all(
            v is not None for v in [data["wti"], data["rbob_gc"], data["ulsd_gc"]]
        )
        return ScrapeResult(
            date=data["date"],
            wti=data["wti"],
            rbob_gc=data["rbob_gc"],
            ulsd_gc=data["ulsd_gc"],
            scraped_at=data["scraped_at"],
            status="success" if all_present else "partial",
            error_type=None,
            error_message=None,
        )
    except requests.RequestException as e:
        return ScrapeResult(
            date=None, wti=None, rbob_gc=None, ulsd_gc=None,
            scraped_at=now, status="error",
            error_type="network", error_message=str(e),
        )
    except ValueError as e:
        msg = str(e)
        etype = "structure_change" if "no encontrada" in msg else "network"
        return ScrapeResult(
            date=None, wti=None, rbob_gc=None, ulsd_gc=None,
            scraped_at=now, status="error",
            error_type=etype, error_message=msg,
        )
