#!/usr/bin/env python3
"""Convert `fetch_il_daycare_by_county.py` combined CSV to `Daycare Providers.csv` for build_data.py.

Sunshine export columns:
  search_county, provider_name, street, city, county, zip, phone, facility_type, status,
  day_age_range, night_age_range, day_capacity, night_capacity, language

Output matches the header expected by build_data.py (subset of the full state export format).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path


OUT_COLUMNS = [
    "ProviderID",
    "DoingBusinessAs",
    "Street",
    "City",
    "County",
    "Zip",
    "Phone",
    "FacilityType",
    "DayAgeRange",
    "NightAgeRange",
    "Languages",
    "Language1",
    "Language2",
    "Language3",
    "DayCapacity",
    "NightCapacity",
    "Status",
]


def stable_provider_id(name: str, street: str, zip_code: str) -> str:
    key = "|".join(
        [
            (name or "").strip().upper(),
            (street or "").strip().upper(),
            (zip_code or "").strip(),
        ]
    )
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return h.upper()


def map_facility_type(raw: str) -> str:
    t = (raw or "").lower()
    if "group" in t and "home" in t:
        return "GDC"
    if "day care home" in t or "daycare home" in t or t.strip() in ("dch", "home"):
        return "DCH"
    if "center" in t or t.strip() in ("dcc", "day care center"):
        return "DCC"
    if "gdc" in t:
        return "GDC"
    if "dch" in t:
        return "DCH"
    if "dcc" in t:
        return "DCC"
    return "DCC"


def digits_phone(p: str) -> str:
    return re.sub(r"\D+", "", p or "")


def main() -> None:
    ap = argparse.ArgumentParser(description="Normalize Sunshine county CSV to Daycare Providers.csv")
    ap.add_argument("--in", dest="in_path", type=Path, required=True, help="Input combined CSV from fetch script")
    ap.add_argument("--out", dest="out_path", type=Path, default=Path("Daycare Providers.csv"))
    args = ap.parse_args()

    in_path: Path = args.in_path
    if not in_path.is_file():
        print(f"Input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    rows_out: list[dict[str, str]] = []
    with in_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("provider_name") or "").strip()
            street = (row.get("street") or "").strip()
            city = (row.get("city") or "").strip() or "CHICAGO"
            county = (row.get("county") or "").strip()
            raw_zip = (row.get("zip") or "").strip()
            digits = re.sub(r"\D+", "", raw_zip)
            if len(digits) >= 5:
                z = digits[:5]
            elif len(digits) > 0:
                z = (digits + "00000")[:5]
            else:
                z = "60601"
            phone = digits_phone(row.get("phone") or "")[:15]
            lang = (row.get("language") or "").strip() or "ENGLISH"
            day_cap = re.sub(r"\D", "", row.get("day_capacity") or "0") or "0"
            night_cap = re.sub(r"\D", "", row.get("night_capacity") or "0") or "0"
            pid = stable_provider_id(name, street, z)
            rows_out.append(
                {
                    "ProviderID": pid,
                    "DoingBusinessAs": name,
                    "Street": street,
                    "City": city,
                    "County": county,
                    "Zip": z,
                    "Phone": phone,
                    "FacilityType": map_facility_type(row.get("facility_type") or ""),
                    "DayAgeRange": (row.get("day_age_range") or "").strip(),
                    "NightAgeRange": (row.get("night_age_range") or "").strip(),
                    "Languages": "",
                    "Language1": lang,
                    "Language2": "",
                    "Language3": "",
                    "DayCapacity": day_cap,
                    "NightCapacity": night_cap,
                    "Status": (row.get("status") or "").strip(),
                }
            )

    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    with args.out_path.open("w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=OUT_COLUMNS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)

    print(f"Wrote {len(rows_out)} rows to {args.out_path}")


if __name__ == "__main__":
    main()
