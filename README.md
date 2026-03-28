# Illinois Daycares

Public, static map of **licensed Illinois child care providers** built from state licensing data. Explore providers on a Leaflet map, search and filter in the sidebar, and optionally drop a pin to sort by distance.

**Live site:** [illinoisdaycares.com](https://illinoisdaycares.com/) (configure DNS + GitHub Pages as below).

## License

MIT — see [LICENSE](LICENSE).

## Local development

Requirements: Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Normalize a Sunshine export, then geocode (CSV is local input only; the site loads providers.json)
python3 normalize_sunshine_csv.py --in path/to/export.csv --out /tmp/il.csv
python3 build_data.py --csv /tmp/il.csv
```

Open `index.html` with a local static server (needed to load JSON):

```bash
python3 -m http.server 8080
# visit http://127.0.0.1:8080/
```

## Public API

Static JSON (no query parameters). See **`api.html`** on the site or these URLs:

| Resource | URL |
|----------|-----|
| All providers (preferred) | `https://illinoisdaycares.com/api/v1/providers.json` |
| Same data (legacy path) | `https://illinoisdaycares.com/providers.json` |
| JSON Schema (one record) | `https://illinoisdaycares.com/api/v1/provider.schema.json` |
| OpenAPI description | `https://illinoisdaycares.com/api/openapi.yaml` |

The map tries `/api/v1/providers.json` first, then falls back to `providers.json`. GitHub Pages does not set custom CORS headers; use a server-side client or same-origin requests if browsers block cross-origin `fetch`.

## Map: favorites, saved searches, share links

- **Favorites** — Star on list cards or in the marker popup; stored in `localStorage` on this device only.
- **Saved searches** — Name the current filters + search + sort (+ optional pin) and re-apply from the list under *Saved & share*.
- **Share** — *Copy share link* puts a short URL on the clipboard using `?s=<base64url>` (UTF-8 JSON). Opening that URL restores the same filters; if a pin was set, lat/lon (4 decimal places) and label are included. Non-default filters also update the address bar (debounced) so you can bookmark. See `api.html` for plain query-parameter alternatives.

## Data pipeline

| Step | What it does |
|------|----------------|
| `build_data.py` | Geocodes a normalized CSV via the [U.S. Census Geocoder](https://geocoding.geo.census.gov/), caches in `geocode_cache.json`, writes compact `providers.json` and mirrors it to `api/v1/providers.json`. |
| `fetch_il_daycare_by_county.py` | Optional: Playwright scrape of the [DCFS Sunshine provider lookup](https://sunshine.dcfs.illinois.gov/Content/Licensing/Daycare/ProviderLookup.aspx) by county (slow; respect the site). |
| `normalize_sunshine_csv.py` | Converts combined Sunshine CSV into `Daycare Providers.csv` format for the build. |

### GitHub Actions

- **Deploy GitHub Pages** (`.github/workflows/pages.yml`): on push to `main`, uploads the static site including `api.html`, `api/v1/*`, `api/openapi.yaml`, `LICENSE`, `assets/`, `providers.json`, and related files.
- **Data pipeline** (`.github/workflows/data-pipeline.yml`): two jobs:
  1. **Fetch Sunshine CSV** — runs only on manual dispatch when **Run full IL Sunshine scrape** is enabled (Playwright + normalize).
  2. **Geocode and commit JSON** — runs after the fetch job: installs `requirements.txt`, runs `build_data.py` when `Daycare Providers.csv` is present (from the fetch artifact), and commits `providers.json`, `geocode_cache.json`, and `api/v1/providers.json`. Source CSVs are not committed; the published dataset is `providers.json`.

Triggers: push to `main` (paths listed in the workflow), weekly schedule, or manual dispatch.

**Manual workflow with optional fetch:** Actions → *Data pipeline* → *Run workflow* → enable **Run full IL Sunshine scrape** only when you intend to refresh the statewide CSV via Playwright (long-running).

**Repository settings for Pages:** *Settings → Pages → Build and deployment → Source: GitHub Actions*.

**Custom domain:** `CNAME` contains `illinoisdaycares.com`. In the same Pages settings, set the custom domain and enable HTTPS. At your DNS host, add a **CNAME** from `illinoisdaycares.com` (or `www`) to `<your-user>.github.io` per [GitHub’s docs](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site).

## Branding & SEO

- Shared styles: `assets/site.css`
- Logo / favicon: `assets/logo.svg`, `assets/favicon.svg`
- Social preview: `assets/og-image.png` (referenced in `index.html` / `about.html` meta tags)
- `robots.txt` and `sitemap.xml` use the production URL `https://illinoisdaycares.com/`

## Disclaimer

This project is not affiliated with DCFS or any provider. Data may be incomplete or outdated. Verify licenses directly with the state and providers before making decisions.
