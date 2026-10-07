#!/usr/bin/env python3
"""Build the static H-1B salary site from data/h1b.csv.gz.

  SITE_URL=https://northpeak-studiolabs.github.io/h1b python build.py [--out dist/h1b]

Files are written directly into --out, which is served at SITE_URL's path
(default /h1b/). All internal links are absolute paths under that prefix.
"""
import argparse
import csv
import gzip
import json
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from common import US_STATES, city_key, employer_display, employer_key, slugify, smart_title, title_key

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SITE_NAME = "H-1B Salary Lookup"
MIN_WAGE, MAX_WAGE = 20_000, 2_000_000   # sanity bounds for annualised offered wage
RECENT_ROWS = 100

# ------------------------------------------------------------------ helpers


def pct(sorted_vals, q):
    """Linear-interpolated percentile of an already sorted list."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo))


def stats(wages):
    w = sorted(x for x in wages if x is not None)
    if not w:
        return {"n_wage": 0, "median": None, "p25": None, "p75": None, "min": None, "max": None}
    return {"n_wage": len(w), "median": pct(w, .5), "p25": pct(w, .25), "p75": pct(w, .75),
            "min": w[0], "max": w[-1]}


def money(v):
    return "—" if v is None else "${:,.0f}".format(v)


def num(v):
    return "{:,}".format(v)


def fmt_date(iso):
    if not iso:
        return ""
    y, m, d = iso.split("-")
    return f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m)-1]} {int(d)}, {y}"


LEVELS = {"I": "Level I", "II": "Level II", "III": "Level III", "IV": "Level IV"}


def level_short(v):
    v = (v or "").strip().upper()
    return v if v in LEVELS else ""


class Row:
    __slots__ = ("case", "dd", "begin", "emp", "ekey", "title", "tkey", "soc", "city", "ckey",
                 "wfrom", "wto", "wage", "level", "pw")


# ------------------------------------------------------------------ load


def load(path):
    rows = []
    bad_wage = 0
    ek, tk = {}, {}
    with gzip.open(path, "rt", newline="") as fh:
        rd = csv.DictReader(fh)
        for r in rd:
            o = Row()
            o.case = r["case_number"]
            o.dd = r["decision_date"]
            o.begin = r["begin_date"]
            o.emp = r["employer"]
            o.ekey = ek.get(o.emp)
            if o.ekey is None:
                o.ekey = ek[o.emp] = employer_key(o.emp)
            o.title = r["job_title"]
            o.tkey = tk.get(o.title)
            if o.tkey is None:
                o.tkey = tk[o.title] = title_key(o.title)
            o.soc = r["soc_title"].strip()
            ck = city_key(r["city"], r["state"])
            o.ckey = ck if ck and ck[1] in US_STATES else None
            o.city = r["city"].strip()
            af = float(r["annual_from"]) if r["annual_from"] else None
            at = float(r["annual_to"]) if r["annual_to"] else None
            if af is not None and not (MIN_WAGE <= af <= MAX_WAGE):
                af, at = None, None
                bad_wage += 1
            elif af is None:
                bad_wage += 1
            if at is not None and (at < (af or 0) or at > MAX_WAGE):
                at = None
            o.wfrom, o.wto = af, at
            o.wage = af
            o.level = level_short(r["pw_level"])
            o.pw = float(r["pw_annual"]) if r["pw_annual"] else None
            rows.append(o)
    return rows, bad_wage


# ------------------------------------------------------------------ aggregation


def group(rows, attr):
    g = defaultdict(list)
    for r in rows:
        k = getattr(r, attr)
        if k:
            g[k].append(r)
    return g


def top_counter(rows, attr, n):
    return Counter(getattr(r, attr) for r in rows if getattr(r, attr)).most_common(n)


def assign_slugs(keys_by_count, name_of):
    used, out = set(), {}
    for k in keys_by_count:
        base = slugify(name_of(k))
        s, i = base, 2
        while s in used:
            s = f"{base}-{i}"
            i += 1
        used.add(s)
        out[k] = s
    return out


def level_mix(rows):
    c = Counter(r.level for r in rows if r.level)
    tot = sum(c.values())
    return [{"label": LEVELS[l], "n": c[l], "pct": round(100 * c[l] / tot) if tot else 0} for l in ("I", "II", "III", "IV")] if tot else []


# ------------------------------------------------------------------ build


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "h1b"))
    ap.add_argument("--data", default=str(DATA / "h1b.csv.gz"))
    ap.add_argument("--min-employer", type=int, default=10)
    ap.add_argument("--min-title", type=int, default=20)
    ap.add_argument("--min-city", type=int, default=50)
    ap.add_argument("--max-pages", type=int, default=24_500, help="raise thresholds until under this")
    args = ap.parse_args()
    t0 = time.time()

    site_url = os.environ.get("SITE_URL", "https://northpeak-studiolabs.github.io/h1b").rstrip("/")
    base = urlparse(site_url).path.rstrip("/")          # '/h1b' or ''
    origin = site_url[: len(site_url) - len(base)] if base else site_url
    ads_html = os.environ.get("ADS_HTML", "")

    manifest = json.loads((DATA / "manifest.json").read_text()) if (DATA / "manifest.json").exists() else {}
    rows, bad_wage = load(args.data)
    print(f"loaded {len(rows):,} rows ({bad_wage:,} without a usable wage) in {time.time()-t0:.1f}s")
    if not rows:
        sys.exit("no data")

    dates = sorted(r.dd for r in rows if r.dd)
    d_min, d_max = dates[0], dates[-1]
    year = int(d_max[:4])
    combined = manifest.get("combined", {})
    win_start = combined.get("window_start", d_min)
    win_end = combined.get("window_end", d_max)

    by_emp, by_title, by_city = group(rows, "ekey"), group(rows, "tkey"), group(rows, "ckey")

    # thresholds, raised automatically to respect the page budget
    me, mt, mc = args.min_employer, args.min_title, args.min_city
    while True:
        ne = sum(1 for v in by_emp.values() if len(v) >= me)
        nt = sum(1 for v in by_title.values() if len(v) >= mt)
        nc = sum(1 for v in by_city.values() if len(v) >= mc)
        if ne + nt + nc + 100 <= args.max_pages:
            break
        if ne >= nt:
            me += 2
        else:
            mt += 5
        print(f"page budget: raising thresholds to employer>={me}, title>={mt}")

    emp_keys = sorted((k for k, v in by_emp.items() if len(v) >= me), key=lambda k: (-len(by_emp[k]), k))
    title_keys = sorted((k for k, v in by_title.items() if len(v) >= mt), key=lambda k: (-len(by_title[k]), k))
    city_keys = sorted((k for k, v in by_city.items() if len(v) >= mc), key=lambda k: (-len(by_city[k]), k))

    emp_name = {k: employer_display(Counter(r.emp for r in by_emp[k]).most_common(1)[0][0]) for k in emp_keys}
    title_name = {k: smart_title(k) for k in title_keys}
    city_name = {k: f"{smart_title(k[0])}, {k[1]}" for k in city_keys}
    emp_slug = assign_slugs(emp_keys, emp_name.get)
    title_slug = assign_slugs(title_keys, title_name.get)
    city_slug = assign_slugs(city_keys, lambda k: f"{k[0]} {k[1]}")

    def u(path=""):
        return f"{base}/{path}"

    def emp_url(k):
        return u(f"employer/{emp_slug[k]}/") if k in emp_slug else None

    def title_url(k):
        return u(f"title/{title_slug[k]}/") if k in title_slug else None

    def city_url(k):
        return u(f"city/{city_slug[k]}/") if k in city_slug else None

    # ---------------------------------------------------------------- output setup
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    shutil.copy(ROOT / "templates" / "style.css", out / "assets" / "style.css")
    shutil.copy(ROOT / "templates" / "search.js", out / "assets" / "search.js")

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters.update(money=money, num=num, date=fmt_date)
    env.globals.update(base=base, u=u, site_name=SITE_NAME, site_url=site_url, year=year,
                       ads_html=ads_html, d_min=d_min, d_max=d_max, win_start=win_start, win_end=win_end,
                       build_date=date.today().isoformat())
    sitemap = []
    page_count = 0

    def render(tpl, path, crumbs, **ctx):
        nonlocal page_count
        canonical = origin + u(path)
        crumbs = [("Home", u())] + crumbs
        ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": origin + href}
            for i, (n, href) in enumerate(crumbs)]}
        html = env.get_template(tpl).render(canonical=canonical, crumbs=crumbs,
                                           breadcrumb_ld=json.dumps(ld, separators=(",", ":")), **ctx)
        dest = out / path / "index.html" if (path == "" or path.endswith("/")) else out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")
        sitemap.append(canonical)
        page_count += 1

    def title_rows(rs, n=15):
        g = group(rs, "tkey")
        res = []
        for k, lst in sorted(g.items(), key=lambda kv: -len(kv[1]))[:n]:
            s = stats(r.wage for r in lst)
            res.append({"name": title_name.get(k) or smart_title(k), "url": title_url(k), "n": len(lst), **s})
        return res

    def city_rows(rs, n=10):
        g = group(rs, "ckey")
        res = []
        for k, lst in sorted(g.items(), key=lambda kv: -len(kv[1]))[:n]:
            s = stats(r.wage for r in lst)
            res.append({"name": city_name.get(k) or f"{smart_title(k[0])}, {k[1]}", "url": city_url(k), "n": len(lst), **s})
        return res

    def emp_rows(rs, n=15, by="count", min_n=1):
        g = group(rs, "ekey")
        items = []
        for k, lst in g.items():
            if len(lst) < min_n:
                continue
            s = stats(r.wage for r in lst)
            if by == "median" and s["median"] is None:
                continue
            items.append({"name": emp_name.get(k) or employer_display(lst[0].emp), "url": emp_url(k), "n": len(lst), **s})
        key = (lambda x: (-x["n"], x["name"])) if by == "count" else (lambda x: (-x["median"], -x["n"]))
        return sorted(items, key=key)[:n]

    def recent(rs, show_employer=False):
        rs = sorted(rs, key=lambda r: (r.dd, r.case), reverse=True)[:RECENT_ROWS]
        return [{"dd": r.dd, "begin": r.begin, "title": smart_title(r.title), "turl": title_url(r.tkey),
                 "city": (f"{smart_title(r.ckey[0])}, {r.ckey[1]}" if r.ckey else smart_title(r.city)),
                 "curl": city_url(r.ckey) if r.ckey else None,
                 "emp": emp_name.get(r.ekey) or employer_display(r.emp) if show_employer else None,
                 "eurl": emp_url(r.ekey) if show_employer else None,
                 "wfrom": r.wfrom, "wto": r.wto, "level": r.level} for r in rs]

    # ---------------------------------------------------------------- employer pages
    t1 = time.time()
    for k in emp_keys:
        rs = by_emp[k]
        s = stats(r.wage for r in rs)
        name = emp_name[k]
        pw = stats(r.pw for r in rs)
        variants = [v for v, _ in Counter(r.emp for r in rs).most_common(6)]
        render("employer.html", f"employer/{emp_slug[k]}/", [("Employers", u("employers/")), (name, emp_url(k))],
               name=name, n=len(rs), s=s, pw_median=pw["median"], titles=title_rows(rs), cities=city_rows(rs),
               recent=recent(rs), levels=level_mix(rs), variants=variants)
    print(f"{len(emp_keys):,} employer pages in {time.time()-t1:.1f}s")

    # ---------------------------------------------------------------- title pages
    t1 = time.time()
    for k in title_keys:
        rs = by_title[k]
        s = stats(r.wage for r in rs)
        name = title_name[k]
        socs = [x for x, _ in top_counter(rs, "soc", 3)]
        render("title.html", f"title/{title_slug[k]}/", [("Job titles", u("titles/")), (name, title_url(k))],
               name=name, n=len(rs), s=s, socs=socs, top_paying=emp_rows(rs, 25, "median", 3),
               top_emps=emp_rows(rs, 15), cities=city_rows(rs, 15), levels=level_mix(rs))
    print(f"{len(title_keys):,} title pages in {time.time()-t1:.1f}s")

    # ---------------------------------------------------------------- city pages
    t1 = time.time()
    for k in city_keys:
        rs = by_city[k]
        s = stats(r.wage for r in rs)
        name = city_name[k]
        render("city.html", f"city/{city_slug[k]}/", [("Cities", u("cities/")), (name, city_url(k))],
               name=name, state=US_STATES.get(k[1], k[1]), n=len(rs), s=s, emps=emp_rows(rs, 20),
               top_paying=emp_rows(rs, 15, "median", 5), titles=title_rows(rs, 20), levels=level_mix(rs))
    print(f"{len(city_keys):,} city pages in {time.time()-t1:.1f}s")

    # ---------------------------------------------------------------- browse indexes
    def letter_of(name):
        c = name[:1].upper()
        return c if c.isalpha() else "0-9"

    def letter_pages(kind, label, keys, name_of, url_of, count_of):
        buckets = defaultdict(list)
        for k in keys:
            buckets[letter_of(name_of(k))].append(k)
        letters = sorted(buckets, key=lambda x: (x == "0-9", x))
        slug_of = {L: ("0-9" if L == "0-9" else L.lower()) for L in letters}
        nav = [{"L": L, "url": u(f"{kind}/{slug_of[L]}/")} for L in letters]
        for L in letters:
            items = sorted(({"name": name_of(k), "url": url_of(k), "n": count_of(k)} for k in buckets[L]),
                           key=lambda x: x["name"].lower())
            render("browse.html", f"{kind}/{slug_of[L]}/", [(label, u(f"{kind}/")), (L, u(f"{kind}/{slug_of[L]}/"))],
                   kind=kind, label=label, letter=L, nav=nav, items=items)
        return nav

    emp_nav = letter_pages("employers", "Employers", emp_keys, emp_name.get, emp_url, lambda k: len(by_emp[k]))
    title_nav = letter_pages("titles", "Job titles", title_keys, title_name.get, title_url, lambda k: len(by_title[k]))
    top_emps_all = [{"name": emp_name[k], "url": emp_url(k), "n": len(by_emp[k]),
                     "median": stats(r.wage for r in by_emp[k])["median"]} for k in emp_keys[:100]]
    top_titles_all = [{"name": title_name[k], "url": title_url(k), "n": len(by_title[k]),
                       "median": stats(r.wage for r in by_title[k])["median"]} for k in title_keys[:100]]
    render("browse_root.html", "employers/", [("Employers", u("employers/"))], kind="employers",
           label="Employers", nav=emp_nav, items=top_emps_all, total=len(emp_keys), threshold=me)
    render("browse_root.html", "titles/", [("Job titles", u("titles/"))], kind="titles",
           label="Job titles", nav=title_nav, items=top_titles_all, total=len(title_keys), threshold=mt)
    states = defaultdict(list)
    for k in city_keys:
        states[k[1]].append({"name": city_name[k], "url": city_url(k), "n": len(by_city[k])})
    state_list = [{"code": st, "name": US_STATES.get(st, st), "cities": sorted(v, key=lambda x: -x["n"])}
                  for st, v in sorted(states.items(), key=lambda kv: US_STATES.get(kv[0], kv[0]))]
    render("cities.html", "cities/", [("Cities", u("cities/"))], states=state_list, threshold=mc)

    # ---------------------------------------------------------------- home, about, privacy
    overall = stats(r.wage for r in rows)
    render("home.html", "", [], n=len(rows), s=overall, n_emp=len(by_emp), top_emps=top_emps_all[:30],
           top_titles=top_titles_all[:20],
           top_cities=[{"name": city_name[k], "url": city_url(k), "n": len(by_city[k])} for k in city_keys[:20]])
    render("about.html", "about/", [("About & methodology", u("about/"))], n=len(rows), bad_wage=bad_wage,
           manifest=manifest, me=me, mt=mt, mc=mc, min_wage=MIN_WAGE, max_wage=MAX_WAGE)
    render("privacy.html", "privacy/", [("Privacy", u("privacy/"))])

    # ---------------------------------------------------------------- search index + sitemap
    idx = {"e": [[emp_name[k], emp_slug[k], len(by_emp[k])] for k in emp_keys],
           "t": [[title_name[k], title_slug[k], len(by_title[k])] for k in title_keys],
           "c": [[city_name[k], city_slug[k], len(by_city[k])] for k in city_keys]}
    (out / "search.json").write_text(json.dumps(idx, separators=(",", ":")), encoding="utf-8")
    today = date.today().isoformat()
    with open(out / "sitemap.xml", "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for loc in sitemap:
            fh.write(f"<url><loc>{loc}</loc><lastmod>{today}</lastmod></url>\n")
        fh.write("</urlset>\n")
    # robots.txt is only honoured at the host root; this copy documents the sitemap for the org site.
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site_url}/sitemap.xml\n")

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"pages: {page_count:,} (employers {len(emp_keys):,} >= {me}, titles {len(title_keys):,} >= {mt}, "
          f"cities {len(city_keys):,} >= {mc})")
    print(f"size: {total/1e6:.1f} MB, search.json {(out/'search.json').stat().st_size/1e3:.0f} KB")
    print(f"build time: {time.time()-t0:.1f}s -> {out}")


if __name__ == "__main__":
    main()
