#!/usr/bin/env python3
"""
Download Illinois DCFS Sunshine daycare provider search results for every county.

The site is ASP.NET WebForms + DevExpress; reliable automation uses the same
client-side calls as the page (ASPxCounty.SetText + dcfssearch), then clicks
**Export** to download the full result set as CSV (equivalent to posting
ctl00$ContentPlaceHolderContent$ASPxButtonExport=Export with a valid session).

Requires: pip install playwright && playwright install chromium

Usage:
  python3 fetch_il_daycare_by_county.py --counties cook lake --out-dir ./sunshine_out
  python3 fetch_il_daycare_by_county.py --all --out-dir ./sunshine_out

Respect the site: use modest delays; do not hammer the server.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Install Playwright: pip install playwright && playwright install chromium", file=sys.stderr)
    raise

LOOKUP_URL = "https://sunshine.dcfs.illinois.gov/Content/Licensing/Daycare/ProviderLookup.aspx"
WIKI_COUNTIES_URL = "https://en.wikipedia.org/wiki/List_of_counties_in_Illinois"

# DevExpress export control (parent wraps the visible button)
EXPORT_BTN = "#ctl00_ContentPlaceHolderContent_ASPxButtonExport"


def fetch_county_names_from_wikipedia() -> list[str]:
    """Return 102 Illinois county names (title case), e.g. 'Cook', 'Jo Daviess'."""
    r = requests.get(
        WIKI_COUNTIES_URL,
        timeout=60,
        headers={"User-Agent": "DaycareCountyFetch/1.0 (educational; local script)"},
    )
    r.raise_for_status()
    names = re.findall(r'title="([^"]+ County, Illinois)"', r.text)
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        base = n.replace(", Illinois", "").replace(" County", "").strip()
        if base and base not in seen:
            seen.add(base)
            out.append(base)
    if len(out) < 100:
        raise RuntimeError(f"Expected ~102 counties from Wikipedia, got {len(out)}")
    return out


def run_search_for_county(page, county_display: str) -> None:
    q = county_display.strip().lower()
    page.evaluate(
        """(county) => {
      ASPxProviderName.SetText('');
      ASPxCity.SetText('');
      ASPxCounty.SetText(county);
      ASPxZip.SetText('');
      dcfssearch();
    }""",
        q,
    )
    page.wait_for_timeout(5500)


def download_export_csv(page, dest: Path) -> tuple[int, Optional[list[str]], list[list[str]]]:
    """
    Click Export; save CSV to dest.
    Returns (data_row_count, header_cols or None, data_rows).
    Empty search can yield a 0-byte file.
    """
    page.locator(EXPORT_BTN).scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    with page.expect_download(timeout=120000) as dl_info:
        page.locator(EXPORT_BTN).click(force=True)
    download = dl_info.value
    download.save_as(str(dest))

    if dest.stat().st_size == 0:
        return 0, None, []

    with dest.open(newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.reader(f))

    if not rows:
        return 0, None, []

    header = rows[0]
    data_rows = rows[1:]
    return len(data_rows), header, data_rows


def append_to_combined(
    combined_writer: csv.writer,
    search_key: str,
    per_file_rows: list[list[str]],
    header: list[str],
    combined_header_written: list[bool],
) -> None:
    """combined_header_written is a one-element list used as mutable flag."""
    if not header:
        return
    if not combined_header_written[0]:
        combined_writer.writerow(["search_county"] + header)
        combined_header_written[0] = True
    for row in per_file_rows:
        combined_writer.writerow([search_key] + row)


def main() -> None:
    ap = argparse.ArgumentParser(description="Export IL DCFS daycare provider lookup by county (CSV download).")
    ap.add_argument(
        "--counties",
        nargs="*",
        help="County names as on the site (e.g. cook lake dupage). Default: all 102 from Wikipedia.",
    )
    ap.add_argument("--all", action="store_true", help="Same as omitting --counties: all counties.")
    ap.add_argument("--out-dir", type=Path, default=Path("sunshine_county_exports"), help="Output directory.")
    ap.add_argument("--combined-csv", type=str, default="all_counties.csv", help="Combined CSV filename.")
    ap.add_argument("--delay", type=float, default=1.0, help="Seconds between counties.")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--no-headless", action="store_false", dest="headless", help="Show browser window.")
    args = ap.parse_args()

    if args.counties:
        counties = [c.strip() for c in args.counties if c.strip()]
    else:
        counties = fetch_county_names_from_wikipedia()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    combined_path = out_dir / args.combined_csv
    combined_f = combined_path.open("w", newline="", encoding="utf-8")
    combined_writer = csv.writer(combined_f)
    combined_header_written = [False]

    stats = {"counties": 0, "rows": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            ignore_https_errors=True,
            accept_downloads=True,
            viewport={"width": 1400, "height": 2200},
        )
        page = context.new_page()
        page.set_default_timeout(120000)
        page.goto(LOOKUP_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        for display_name in counties:
            search_key = display_name.lower()
            slug = re.sub(r"[^a-z0-9]+", "_", search_key).strip("_") or "county"
            per_path = out_dir / f"{slug}.csv"

            print(f"County: {display_name} ({search_key}) …", flush=True)
            try:
                run_search_for_county(page, display_name)
                n_data, header, data_rows = download_export_csv(page, per_path)
            except Exception as e:
                print(f"  error: {e}", flush=True)
                n_data, header, data_rows = 0, None, []

            stats["counties"] += 1
            stats["rows"] += n_data

            if per_path.stat().st_size == 0:
                print("  -> no data (empty export file)", flush=True)
            elif header:
                append_to_combined(combined_writer, search_key, data_rows, header, combined_header_written)
                print(f"  -> {n_data} data row(s) -> {per_path.name}", flush=True)
            else:
                print(f"  -> wrote {per_path.name} (could not parse CSV)", flush=True)

            time.sleep(max(0.0, args.delay))

        browser.close()

    combined_f.close()
    print(f"Done. Counties processed: {stats['counties']}, total data rows (combined): {stats['rows']}", flush=True)
    print(f"Combined: {combined_path}", flush=True)


if __name__ == "__main__":
    main()
