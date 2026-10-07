# H-1B Salary Lookup (static site)

Static site generator for H-1B salary pages built from U.S. Department of Labor (OFLC) LCA
disclosure data. Published at https://northpeak-studiolabs.github.io/h1b/.

```
pip install -r requirements.txt
python fetch.py                     # download + parse latest 4 quarters -> data/h1b.csv.gz
SITE_URL=https://northpeak-studiolabs.github.io/h1b python build.py   # -> dist/h1b/
SITE_URL=https://northpeak-studiolabs.github.io/h1b python check.py   # links, sitemap, budget
```

## fetch.py
- Scrapes https://www.dol.gov/agencies/eta/foreign-labor/performance for
  `LCA_Disclosure_Data_FY<yyyy>_Q<n>.xlsx` links (no hard-coded URLs).
- OFLC publishes the current fiscal year as one cumulative file (e.g. FY2026_Q3 covers
  1 Oct 2025 – 30 Jun 2026) and earlier years per quarter. fetch.py treats a file as
  cumulative when earlier quarters of the same FY are not linked, then picks the fewest
  files that cover the latest `--quarters` (default 4) fiscal quarters.
- Downloads to `raw/`, then stream-parses the sheet XML directly from the xlsx zip
  (regex over 8 MB chunks + shared-strings table; stdlib only, constant memory, much
  faster than openpyxl read-only). Keeps `CASE_STATUS=Certified`, `VISA_CLASS=H-1B`,
  `FULL_TIME_POSITION=Y`. Wages are annualised (Hour×2080, Week×52, Bi-Weekly×26, Month×12).
- Writes `data/processed/<file>.csv.gz` per source file and `data/manifest.json`. On the next
  run a file is skipped when its remote size and Last-Modified are unchanged (`--force` to
  redo). Then writes `data/h1b.csv.gz`: rows inside the quarter window, de-duplicated by case
  number (newer release wins). `--delete-raw` removes xlsx files after parsing (saves disk in
  CI); `--jobs` sets parallel parsing (default 2).
- In GitHub Actions, cache `data/` (actions/cache keyed on the month) so unchanged quarters
  are not re-downloaded.

## build.py
- Reads only `data/h1b.csv.gz` + `data/manifest.json`. Normalisation lives in `common.py`:
  employer names (case, punctuation, LLC/Inc/Corp/Ltd/N.A./d.b.a. stripped), job titles
  (parentheticals, req ids, trailing level numbers removed; Sr→Senior etc.), city+state.
- Pages: employers ≥10 filings, titles ≥20, cities ≥50, A–Z browse pages, home with client-side
  search (`search.json`), about/methodology, privacy, `sitemap.xml`. Thresholds are raised
  automatically if the total would exceed `--max-pages` (default 24,500).
- `SITE_URL` sets canonical URLs and the path prefix for every internal link (`/h1b`).
  `--out` is the directory served at that path (default `dist/h1b`; for the org site use
  `--out ../dist/h1b`).
- Salary stats use the lower bound of the offered wage; annual wages outside $20k–$2M are
  excluded from stats (still counted as filings).
- Ads: `templates/_ads.html` renders nothing unless `ADS_HTML` is set at build time.
- `robots.txt` only works at the host root: add `Sitemap: https://northpeak-studiolabs.github.io/h1b/sitemap.xml`
  to the org site's root robots.txt (or submit it in Search Console).

## check.py
Validates every internal `href`/`src` resolves to a built file under the base path, every
sitemap URL exists, each page has a self-canonical, one `<h1>`, robots meta and JSON-LD, there
are no external assets, and the page/size budget (25,000 pages, 600 MB). Exits 1 on failure.

Data are certified LCA filings, not actual pay. Not affiliated with DOL or USCIS.
