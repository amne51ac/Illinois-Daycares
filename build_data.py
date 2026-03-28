#!/usr/bin/env python3
"""Regenerate providers.json from a normalized Sunshine CSV.

Uses the U.S. Census Bureau Geocoder for street-level coordinates (free, no API key).
Falls back to zip-code centroid (+ tiny offset) only when the address does not match.

The site ships only providers.json (and api mirror); CSV is a local / CI build input.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import time
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

import pgeocode

CACHE_FILE = "geocode_cache.json"
OUT_NAME = "providers.json"

nomi = pgeocode.Nominatim("us")


def jitter(lat: float, lon: float, key: str, scale: float = 0.004) -> tuple[float, float]:
    h = hashlib.sha256(key.encode()).digest()
    dx = (h[0] / 255.0 - 0.5) * 2 * scale
    dy = (h[1] / 255.0 - 0.5) * 2 * scale
    return lat + dx, lon + dy


def load_cache() -> dict[str, tuple[float, float]]:
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        return {k: (float(v[0]), float(v[1])) for k, v in raw.items()}
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {}


def save_cache(cache: dict[str, tuple[float, float]]) -> None:
    serializable = {k: [round(lat, 6), round(lon, 6)] for k, (lat, lon) in cache.items()}
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=0)


def census_geocode_one_line(address: str) -> tuple[float, float] | None:
    """Return (lat, lon) or None if no match."""
    q = urllib.parse.urlencode(
        {
            "address": address,
            "benchmark": "2020",
            "format": "json",
        }
    )
    url = f"https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?{q}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DaycaresMap/1.0 (educational; local data build)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None
    matches = (data.get("result") or {}).get("addressMatches") or []
    if not matches:
        return None
    c = matches[0]["coordinates"]
    lon, lat = float(c["x"]), float(c["y"])
    return lat, lon


def zip_fallback(zip_code: str, provider_id: str) -> tuple[float, float]:
    loc = nomi.query_postal_code(zip_code.strip())
    lat, lon = float(loc.latitude), float(loc.longitude)
    if lat != lat:
        lat, lon = 41.8781, -87.6298
    return jitter(lat, lon, provider_id)


def main() -> None:
    ap = argparse.ArgumentParser(description="Geocode normalized CSV → providers.json")
    ap.add_argument(
        "--csv",
        type=Path,
        default=Path("Daycare Providers.csv"),
        help="Normalized CSV (from normalize_sunshine_csv.py). Default: Daycare Providers.csv",
    )
    args = ap.parse_args()
    csv_path: Path = args.csv
    if not csv_path.is_file():
        raise SystemExit(f"CSV not found: {csv_path}")

    cache = load_cache()
    rows_out: list[dict] = []
    stats = {"census_hit": 0, "cache_hit": 0, "fallback": 0}
    n = 0

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    total = len(all_rows)
    for row in all_rows:
        n += 1
        if n % 400 == 0 or n == total:
            print(f"  {n}/{total} …", flush=True)

        z = row["Zip"].strip().strip('"')
        street = row["Street"].strip().strip('"')
        city = (row.get("City") or "").strip().strip('"') or "CHICAGO"
        one_line = f"{street}, {city}, IL {z}"
        pid = row["ProviderID"].strip().strip('"')

        lat: float | None = None
        lon: float | None = None

        if one_line in cache:
            lat, lon = cache[one_line]
            stats["cache_hit"] += 1
        else:
            time.sleep(0.06)
            coords = census_geocode_one_line(one_line)
            if coords:
                lat, lon = coords
                cache[one_line] = (lat, lon)
                stats["census_hit"] += 1
            else:
                lat, lon = zip_fallback(z, pid)
                stats["fallback"] += 1
                cache[one_line] = (lat, lon)

        rows_out.append(
            {
                "id": pid,
                "name": row["DoingBusinessAs"].strip().strip('"'),
                "street": street,
                "city": city,
                "zip": z,
                "phone": row["Phone"].strip().strip('"'),
                "facilityType": row["FacilityType"].strip().strip('"'),
                "dayAge": row["DayAgeRange"].strip().strip('"'),
                "nightAge": row["NightAgeRange"].strip().strip('"'),
                "lang1": row["Language1"].strip().strip('"'),
                "dayCap": int(row["DayCapacity"] or 0),
                "nightCap": int(row["NightCapacity"] or 0),
                "status": row["Status"].strip().strip('"'),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
            }
        )

    save_cache(cache)
    with open(OUT_NAME, "w", encoding="utf-8") as out:
        json.dump(rows_out, out, ensure_ascii=False, separators=(",", ":"))

    api_path = Path("api/v1/providers.json")
    api_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT_NAME, api_path)

    print(f"Wrote {len(rows_out)} records to {OUT_NAME}")
    print(f"Copied to {api_path} (public API mirror)")
    print(
        f"Geocode: {stats['cache_hit']} from cache, "
        f"{stats['census_hit']} new Census matches, "
        f"{stats['fallback']} zip fallbacks"
    )


if __name__ == "__main__":
    main()
