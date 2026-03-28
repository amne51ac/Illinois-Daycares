#!/usr/bin/env python3
"""
Download Illinois DCFS Sunshine daycare provider lookup as CSV.

Default (fast): one search on **ZIP partial match** with "6". Illinois ZIP codes
are in the 600xx–629xx range, so every licensed site’s ZIP contains the digit 6;
the site treats this as a partial match and returns the full statewide list in
one grid + Export.

Optional: ``--by-county`` loops all Wikipedia counties (slow; legacy).

The page uses ASP.NET + DevExpress; we call ASPx* SetText + dcfssearch(), then
Export (same as ctl00$ContentPlaceHolderContent$ASPxButtonExport in the browser).

Requires: pip install playwright && playwright install chromium
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


def run_search_zip_partial(page, zip_substring: str) -> None:
    s = (zip_substring or "6").strip()
    page.evaluate(
        """(z) => {
      ASPxProviderName.SetText('');
      ASPxCity.SetText('');
      ASPxCounty.SetText('');
      ASPxZip.SetText(z);
      dcfssearch();
    }""",
        s,
    )
    page.wait_for_timeout(8000)


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
    page.locator(EXPORT_BTN).scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    with page.expect_download(timeout=180000) as dl_info:
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
    if not header:
        return
    if not combined_header_written[0]:
        combined_writer.writerow(["search_county"] + header)
        combined_header_written[0] = True
    for row in per_file_rows:
        combined_writer.writerow([search_key] + row)


def run_zip_export(args, pw_page) -> None:
    """Single statewide export via ZIP partial match."""
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / args.output

    print(f"ZIP partial search: {args.zip_partial!r} → export to {dest} …", flush=True)
    run_search_zip_partial(pw_page, args.zip_partial)
    n_data, header, _ = download_export_csv(pw_page, dest)
    if dest.stat().st_size == 0:
        print("No data (empty export).", flush=True)
        sys.exit(1)
    print(f"Done. {n_data} data row(s) → {dest}", flush=True)


def run_county_loop(args, page) -> None:
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

    combined_f.close()
    print(f"Done. Counties processed: {stats['counties']}, total data rows (combined): {stats['rows']}", flush=True)
    print(f"Combined: {combined_path}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Export IL DCFS daycare provider lookup (default: one ZIP partial search for statewide CSV)."
    )
    ap.add_argument(
        "--by-county",
        action="store_true",
        help="Scrape every county via Wikipedia list (slow). Default is single ZIP partial search.",
    )
    ap.add_argument(
        "--zip-partial",
        default="6",
        help='ZIP field substring (partial match). Default "6" matches IL ZIPs 600xx–629xx.',
    )
    ap.add_argument("--out-dir", type=Path, default=Path("sunshine_county_exports"), help="Output directory.")
    ap.add_argument(
        "--output",
        "-o",
        default="illinois_sunshine_export.csv",
        help="Output filename for ZIP mode (written under --out-dir).",
    )
    ap.add_argument(
        "--counties",
        nargs="*",
        help="With --by-county: county names only (e.g. cook lake). Omit for all 102.",
    )
    ap.add_argument("--combined-csv", type=str, default="all_counties.csv", help="--by-county only: combined file name.")
    ap.add_argument("--delay", type=float, default=1.0, help="--by-county only: seconds between counties.")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--no-headless", action="store_false", dest="headless", help="Show browser window.")
    args = ap.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            ignore_https_errors=True,
            accept_downloads=True,
            viewport={"width": 1400, "height": 2200},
        )
        page = context.new_page()
        page.set_default_timeout(180000)
        page.goto(LOOKUP_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        try:
            if args.by_county:
                run_county_loop(args, page)
            else:
                run_zip_export(args, page)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
