#!/usr/bin/env python3
"""Convert Sunshine export CSV to `Daycare Providers.csv` for build_data.py.

Accepts either:
1. **Native DCFS export** (from Export button): ProviderID, DoingBusinessAs, Street, …
2. **Legacy combined county scrape**: search_county + lowercase snake columns, or mixed headers.

Output matches the header expected by build_data.py.
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


def normalize_zip(raw_zip: str) -> str:
    digits = re.sub(r"\D+", "", raw_zip or "")
    if len(digits) >= 5:
        return digits[:5]
    if len(digits) > 0:
        return (digits + "00000")[:5]
    return "60601"


def row_from_native_export(row: dict[str, str]) -> dict[str, str]:
    """Map official Sunshine column names to OUT_COLUMNS."""
    name = (row.get("DoingBusinessAs") or "").strip()
    street = (row.get("Street") or "").strip()
    z = normalize_zip(row.get("Zip") or "")
    pid = (row.get("ProviderID") or "").strip()
    if not pid:
        pid = stable_provider_id(name, street, z)
    phone = digits_phone(row.get("Phone") or "")[:15]
    lang1 = (row.get("Language1") or row.get("language1") or "").strip() or "ENGLISH"
    day_cap = re.sub(r"\D", "", row.get("DayCapacity") or "0") or "0"
    night_cap = re.sub(r"\D", "", row.get("NightCapacity") or "0") or "0"
    ft = map_facility_type(row.get("FacilityType") or row.get("facility_type") or "")
    return {
        "ProviderID": pid,
        "DoingBusinessAs": name,
        "Street": street,
        "City": (row.get("City") or "").strip() or "CHICAGO",
        "County": (row.get("County") or "").strip(),
        "Zip": z,
        "Phone": phone,
        "FacilityType": ft,
        "DayAgeRange": (row.get("DayAgeRange") or "").strip(),
        "NightAgeRange": (row.get("NightAgeRange") or "").strip(),
        "Languages": (row.get("Languages") or "").strip(),
        "Language1": lang1,
        "Language2": (row.get("Language2") or "").strip(),
        "Language3": (row.get("Language3") or "").strip(),
        "DayCapacity": day_cap,
        "NightCapacity": night_cap,
        "Status": (row.get("Status") or "").strip(),
    }


def row_from_legacy(row: dict[str, str]) -> dict[str, str]:
    """Legacy combined CSV (snake_case columns)."""
    name = (row.get("provider_name") or "").strip()
    street = (row.get("street") or "").strip()
    z = normalize_zip(row.get("zip") or "")
    phone = digits_phone(row.get("phone") or "")[:15]
    lang = (row.get("language") or "").strip() or "ENGLISH"
    day_cap = re.sub(r"\D", "", row.get("day_capacity") or "0") or "0"
    night_cap = re.sub(r"\D", "", row.get("night_capacity") or "0") or "0"
    pid = stable_provider_id(name, street, z)
    return {
        "ProviderID": pid,
        "DoingBusinessAs": name,
        "Street": street,
        "City": (row.get("city") or "").strip() or "CHICAGO",
        "County": (row.get("county") or "").strip(),
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Normalize Sunshine export to Daycare Providers.csv")
    ap.add_argument("--in", dest="in_path", type=Path, required=True, help="Input CSV from fetch / Export")
    ap.add_argument("--out", dest="out_path", type=Path, default=Path("Daycare Providers.csv"))
    args = ap.parse_args()

    in_path: Path = args.in_path
    if not in_path.is_file():
        print(f"Input not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    rows_out: list[dict[str, str]] = []
    use_native = False
    with in_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        use_native = "DoingBusinessAs" in fieldnames

        for row in reader:
            if use_native:
                rows_out.append(row_from_native_export(row))
            else:
                rows_out.append(row_from_legacy(row))

    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    with args.out_path.open("w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=OUT_COLUMNS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)

    fmt = "native export" if use_native else "legacy"
    print(f"Wrote {len(rows_out)} rows to {args.out_path} ({fmt} format)")


if __name__ == "__main__":
    main()
