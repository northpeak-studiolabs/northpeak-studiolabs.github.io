#!/usr/bin/env python3
"""Download, stream-parse and compact DOL LCA disclosure data.

* Scrapes the OFLC performance page for LCA_Disclosure_Data_FY<yyyy>_Q<n>.xlsx links.
* Works out which files cover the latest N fiscal quarters (the newest file of the
  current fiscal year is cumulative, e.g. FY2026_Q3 = Oct 2025 - Jun 2026).
* Streams each workbook's sheet XML straight out of the zip (no openpyxl object
  model, constant memory) and keeps Certified / H-1B / full-time rows.
* Writes data/processed/<file>.csv.gz per source file (skipped next run if the
  remote file is unchanged) and a combined data/h1b.csv.gz restricted to the
  quarter window and de-duplicated by case number.

Usage: python fetch.py [--quarters 4] [--jobs 2] [--delete-raw] [--force]
"""
import argparse
import csv
import gzip
import io
import json
import os
import re
import resource
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests

from common import fy_quarter_end, fy_quarter_start, qfrom_index, qindex

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
DATA = ROOT / "data"
PROC = DATA / "processed"
PAGE = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
UA = {"User-Agent": "Mozilla/5.0 (h1b-salary-site data fetcher; +https://northpeak-studiolabs.github.io/h1b/)"}
LINK_RE = re.compile(r'href="([^"]*?LCA_Disclosure_Data_FY(\d{4})_Q([1-4])\.xlsx)"', re.I)

OUT_COLS = ["case_number", "decision_date", "begin_date", "employer", "job_title", "soc_code",
            "soc_title", "city", "state", "wage_from", "wage_to", "wage_unit", "annual_from",
            "annual_to", "prevailing_wage", "pw_unit", "pw_annual", "pw_level", "workers"]
NEED = {
    "CASE_NUMBER", "CASE_STATUS", "DECISION_DATE", "VISA_CLASS", "JOB_TITLE", "SOC_CODE",
    "SOC_TITLE", "FULL_TIME_POSITION", "BEGIN_DATE", "EMPLOYER_NAME", "WORKSITE_CITY",
    "WORKSITE_STATE", "WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_TO", "WAGE_UNIT_OF_PAY",
    "PREVAILING_WAGE", "PW_UNIT_OF_PAY", "PW_WAGE_LEVEL", "TOTAL_WORKER_POSITIONS",
}
ANNUAL = {"YEAR": 1, "HOUR": 2080, "WEEK": 52, "BI-WEEKLY": 26, "BIWEEKLY": 26, "MONTH": 12}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ discovery

def discover(session):
    html = session.get(PAGE, timeout=60, headers=UA).text
    links = {}
    for href, fy, q in LINK_RE.findall(html):
        key = (int(fy), int(q))
        links.setdefault(key, urljoin(PAGE, href.replace("//media/", "/media/")))
    if not links:
        raise SystemExit("No LCA_Disclosure_Data links found on " + PAGE)
    by_fy = {}
    for fy, q in links:
        by_fy.setdefault(fy, set()).add(q)
    files = []
    for (fy, q), url in links.items():
        # If earlier quarters of the same FY are not published separately, the file is
        # cumulative (OFLC publishes the current FY as one growing file).
        separate = all(p in by_fy[fy] for p in range(1, q))
        cover = [qindex(fy, q)] if separate else [qindex(fy, p) for p in range(1, q + 1)]
        files.append({"fy": fy, "q": q, "url": url, "cover": cover,
                      "name": f"LCA_Disclosure_Data_FY{fy}_Q{q}"})
    files.sort(key=lambda f: (f["fy"], f["q"]), reverse=True)
    return files


def choose(files, nq):
    latest = max(i for f in files for i in f["cover"])
    want = set(range(latest - nq + 1, latest + 1))
    chosen, covered = [], set()
    for f in files:
        gain = (set(f["cover"]) & want) - covered
        if gain:
            chosen.append(f)
            covered |= gain
        if covered == want:
            break
    missing = sorted(want - covered)
    return chosen, sorted(want), missing


# ------------------------------------------------------------------ download

def download(session, f):
    dest = RAW / (f["name"] + ".xlsx")
    head = session.head(f["url"], timeout=60, headers=UA, allow_redirects=True)
    size = int(head.headers.get("content-length") or 0)
    f["remote_size"] = size
    f["last_modified"] = head.headers.get("last-modified", "")
    if dest.exists() and size and dest.stat().st_size == size:
        log("raw present", dest.name)
        return dest
    tmp = dest.with_suffix(".part")
    t0 = time.time()
    with session.get(f["url"], stream=True, timeout=(30, 300), headers=UA) as r:
        r.raise_for_status()
        with open(tmp, "wb") as out:
            for chunk in r.iter_content(1 << 20):
                out.write(chunk)
    tmp.replace(dest)
    log(f"downloaded {dest.name} {dest.stat().st_size/1e6:.0f} MB in {time.time()-t0:.0f}s")
    return dest


# ------------------------------------------------------------------ parsing

CELL_RE = re.compile(rb'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
V_RE = re.compile(rb"<v>(.*?)</v>", re.S)
T_RE = re.compile(rb"<t[^>]*>(.*?)</t>", re.S)
SI_RE = re.compile(rb"<si>(.*?)</si>", re.S)
RPH_RE = re.compile(rb"<rPh.*?</rPh>", re.S)


def _unesc(b: bytes) -> str:
    s = b.decode("utf-8", "replace")
    if "&" in s:
        s = (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
             .replace("&apos;", "'").replace("&amp;", "&"))
        s = re.sub(r"_x000[dDaA]_", " ", s)
    return s


def read_shared_strings(z):
    try:
        raw = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    out = []
    for si in SI_RE.finditer(raw):
        body = RPH_RE.sub(b"", si.group(1))
        out.append(_unesc(b"".join(T_RE.findall(body))).strip())
    del raw
    return out


def iter_rows(z, sheet="xl/worksheets/sheet1.xml", chunk=8 << 20):
    """Yield {col_letter: raw_value_str, ...} dicts plus cell types, streaming."""
    with z.open(sheet) as fh:
        buf = b""
        while True:
            data = fh.read(chunk)
            if data:
                buf += data
            end = buf.rfind(b"</row>")
            if end < 0:
                if not data:
                    break
                continue
            block, buf = buf[: end + 6], buf[end + 6:]
            for row in block.split(b"</row>"):
                if b"<c " in row:
                    yield CELL_RE.findall(row)
            if not data:
                break


XL_EPOCH = date(1899, 12, 30)


def to_date(v):
    if v is None or v == "":
        return ""
    try:
        return (XL_EPOCH + timedelta(days=int(float(v)))).isoformat()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%m/%d/%y"):
        try:
            return datetime.strptime(v.strip()[:19], fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def annualise(x, unit):
    if x is None:
        return None
    k = ANNUAL.get((unit or "").strip().upper())
    return round(x * k) if k else None


def parse_file(xlsx: str, out_csv: str):
    """Runs in a worker process. Returns stats dict."""
    t0 = time.time()
    z = zipfile.ZipFile(xlsx)
    sst = read_shared_strings(z)
    rows = iter_rows(z)
    header_cells = next(rows)

    def val(attrs, inner):
        if b't="s"' in attrs:
            m = V_RE.search(inner)
            return sst[int(m.group(1))] if m else ""
        if b't="inlineStr"' in attrs:
            return _unesc(b"".join(T_RE.findall(inner))).strip()
        m = V_RE.search(inner)
        return _unesc(m.group(1)).strip() if m else ""

    col_of = {}
    for col, attrs, inner in header_cells:
        name = val(attrs, inner).upper()
        if name in NEED:
            col_of[col.decode()] = name
    missing = NEED - set(col_of.values())
    if missing:
        raise RuntimeError(f"{xlsx}: missing columns {sorted(missing)}")
    want = {c.encode(): n for c, n in col_of.items()}

    total = kept = 0
    dmin, dmax = "9999", "0000"
    tmp = out_csv + ".part"
    with gzip.open(tmp, "wt", newline="", compresslevel=6) as gz:
        w = csv.writer(gz)
        w.writerow(OUT_COLS)
        for cells in rows:
            total += 1
            r = {}
            for col, attrs, inner in cells:
                n = want.get(col)
                if n:
                    r[n] = val(attrs, inner)
            if r.get("CASE_STATUS", "").strip().lower() != "certified":
                continue
            if r.get("VISA_CLASS", "").strip().upper() != "H-1B":
                continue
            if r.get("FULL_TIME_POSITION", "").strip().upper() not in ("Y", "YES"):
                continue
            unit = r.get("WAGE_UNIT_OF_PAY", "").strip()
            wf, wt = to_num(r.get("WAGE_RATE_OF_PAY_FROM")), to_num(r.get("WAGE_RATE_OF_PAY_TO"))
            pw, pwu = to_num(r.get("PREVAILING_WAGE")), r.get("PW_UNIT_OF_PAY", "").strip()
            dd = to_date(r.get("DECISION_DATE"))
            if dd:
                dmin, dmax = min(dmin, dd), max(dmax, dd)
            w.writerow([
                r.get("CASE_NUMBER", "").strip(), dd, to_date(r.get("BEGIN_DATE")),
                r.get("EMPLOYER_NAME", "").strip(), r.get("JOB_TITLE", "").strip(),
                r.get("SOC_CODE", "").strip(), r.get("SOC_TITLE", "").strip(),
                r.get("WORKSITE_CITY", "").strip(), r.get("WORKSITE_STATE", "").strip(),
                "" if wf is None else wf, "" if wt is None or wt == 0 else wt, unit,
                annualise(wf, unit) or "", annualise(wt, unit) if wt else "",
                "" if pw is None else pw, pwu, annualise(pw, pwu) or "",
                r.get("PW_WAGE_LEVEL", "").strip(),
                (to_num(r.get("TOTAL_WORKER_POSITIONS")) and int(to_num(r.get("TOTAL_WORKER_POSITIONS")))) or 1,
            ])
            kept += 1
    os.replace(tmp, out_csv)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return {"rows_total": total, "rows_kept": kept, "decision_min": dmin if kept else "",
            "decision_max": dmax if kept else "", "parse_seconds": round(time.time() - t0, 1),
            "worker_peak_rss_mb": round(rss)}


# ------------------------------------------------------------------ combine

def combine(chosen, want_q, out_path):
    """Merge per-file outputs, newest file first, restricted to the quarter window."""
    start = fy_quarter_start(*qfrom_index(want_q[0])).isoformat()
    end = fy_quarter_end(*qfrom_index(want_q[-1])).isoformat()
    seen = set()
    n = dropped_window = dup = 0
    tmp = str(out_path) + ".part"
    with gzip.open(tmp, "wt", newline="", compresslevel=6) as gz:
        w = csv.writer(gz)
        w.writerow(OUT_COLS)
        for f in chosen:  # newest first: newer releases win on duplicates
            with gzip.open(PROC / (f["name"] + ".csv.gz"), "rt", newline="") as fh:
                rd = csv.reader(fh)
                next(rd)
                for row in rd:
                    d = row[1]
                    if not d or d < start or d > end:
                        dropped_window += 1
                        continue
                    if row[0] in seen:
                        dup += 1
                        continue
                    seen.add(row[0])
                    w.writerow(row)
                    n += 1
    os.replace(tmp, out_path)
    return {"window_start": start, "window_end": end, "rows": n,
            "dropped_outside_window": dropped_window, "duplicates": dup}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarters", type=int, default=4)
    ap.add_argument("--jobs", type=int, default=2, help="files parsed in parallel")
    ap.add_argument("--delete-raw", action="store_true", help="remove xlsx after parsing")
    ap.add_argument("--force", action="store_true", help="re-parse even if unchanged")
    args = ap.parse_args()
    t0 = time.time()
    for d in (RAW, PROC):
        d.mkdir(parents=True, exist_ok=True)
    manifest_path = DATA / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": {}}

    s = requests.Session()
    files = discover(s)
    log("found", len(files), "LCA files; newest:", files[0]["name"])
    chosen, want_q, missing = choose(files, args.quarters)
    log("quarters wanted:", ", ".join("FY%dQ%d" % qfrom_index(i) for i in want_q))
    log("files chosen:", ", ".join(f["name"] for f in chosen))
    if missing:
        log("WARNING: no file covers", ", ".join("FY%dQ%d" % qfrom_index(i) for i in missing))

    todo = []
    for f in chosen:
        out = PROC / (f["name"] + ".csv.gz")
        prev = manifest["files"].get(f["name"])
        try:
            head = s.head(f["url"], timeout=60, headers=UA, allow_redirects=True)
            size, lm = int(head.headers.get("content-length") or 0), head.headers.get("last-modified", "")
        except requests.RequestException as e:
            log("HEAD failed", f["name"], e)
            size, lm = None, None
        if (not args.force and out.exists() and prev
                and (size is None or (prev.get("remote_size") == size and prev.get("last_modified") == lm))):
            log("unchanged, skipping", f["name"])
            continue
        try:
            path = download(s, f)
        except requests.RequestException as e:
            log("DOWNLOAD FAILED", f["name"], e)
            continue
        todo.append((f, path, out))

    if todo:
        with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = [(f, path, ex.submit(parse_file, str(path), str(out))) for f, path, out in todo]
            for f, path, fut in futs:
                st = fut.result()
                log(f"parsed {f['name']}: {st}")
                manifest["files"][f["name"]] = {
                    "url": f["url"], "fy": f["fy"], "q": f["q"], "cover": f["cover"],
                    "remote_size": f.get("remote_size"), "last_modified": f.get("last_modified"),
                    "processed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", **st}
                if args.delete_raw:
                    path.unlink(missing_ok=True)

    have = [f for f in chosen if (PROC / (f["name"] + ".csv.gz")).exists()]
    if not have:
        raise SystemExit("nothing processed")
    combo = combine(have, want_q, DATA / "h1b.csv.gz")
    manifest.update({
        "source_page": PAGE,
        "quarters": ["FY%dQ%d" % qfrom_index(i) for i in want_q],
        "missing_quarters": ["FY%dQ%d" % qfrom_index(i) for i in missing],
        "used_files": [f["name"] for f in have],
        "combined": combo,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    })
    manifest_path.write_text(json.dumps(manifest, indent=2))
    peak_self = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    peak_kids = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    log(f"combined: {combo}")
    log(f"done in {time.time()-t0:.0f}s; peak RSS main {peak_self:.0f} MB, largest worker {peak_kids:.0f} MB")


if __name__ == "__main__":
    sys.exit(main())
