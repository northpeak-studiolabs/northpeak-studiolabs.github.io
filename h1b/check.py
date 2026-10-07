#!/usr/bin/env python3
"""Validate a built site: internal links, sitemap, per-page SEO basics, page/size budget.

  SITE_URL=https://northpeak-studiolabs.github.io/h1b python check.py [--out dist/h1b]
Exits non-zero on any broken internal link or failed budget.
"""
import argparse
import os
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

ROOT = Path(__file__).resolve().parent
MAX_PAGES, MAX_MB = 25_000, 600


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.assets, self.ids = [], [], set()
        self.canonical = self.title = None
        self.h1 = 0
        self.ld = False
        self.robots = False
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "link":
            if a.get("rel") == "canonical":
                self.canonical = a.get("href")
            elif a.get("href"):
                self.assets.append(a["href"])
        elif tag in ("script", "img") and a.get("src"):
            self.assets.append(a["src"])
        elif tag == "script" and a.get("type") == "application/ld+json":
            self.ld = True
        elif tag == "meta" and a.get("name") == "robots":
            self.robots = True
        elif tag == "h1":
            self.h1 += 1
        elif tag == "title":
            self._in_title = True

    def handle_data(self, d):
        if self._in_title:
            self.title = (self.title or "") + d

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "h1b"))
    args = ap.parse_args()
    out = Path(args.out)
    site_url = os.environ.get("SITE_URL", "https://northpeak-studiolabs.github.io/h1b").rstrip("/")
    base = urlparse(site_url).path.rstrip("/")
    origin = site_url[: len(site_url) - len(base)] if base else site_url

    def resolve(url_path):
        """Map a site path like /h1b/employer/x/ to a file in out, or None."""
        p = unquote(urlparse(url_path).path)
        if not (p == base or p.startswith(base + "/")):
            return None
        rel = p[len(base):].lstrip("/")
        f = out / rel
        if p.endswith("/") or rel == "":
            f = f / "index.html"
        elif f.is_dir():
            f = f / "index.html"
        return f if f.is_file() else None

    pages = sorted(out.rglob("*.html"))
    broken, external, problems = Counter(), Counter(), []
    titles = Counter()
    checked = 0
    for page in pages:
        s = Scan()
        s.feed(page.read_text(encoding="utf-8"))
        page_url = base + "/" + str(page.relative_to(out)).replace("index.html", "")
        if not s.canonical or not s.canonical.startswith(site_url):
            problems.append(f"{page_url}: missing/foreign canonical")
        elif resolve(s.canonical[len(origin):]) != page:
            problems.append(f"{page_url}: canonical {s.canonical} does not point to itself")
        if not s.title:
            problems.append(f"{page_url}: no <title>")
        titles[s.title] += 1
        if s.h1 != 1:
            problems.append(f"{page_url}: {s.h1} <h1>")
        if not s.ld:
            problems.append(f"{page_url}: no JSON-LD")
        if not s.robots:
            problems.append(f"{page_url}: no robots meta")
        for href in s.assets:
            if urlparse(href).scheme in ("http", "https"):
                problems.append(f"{page_url}: external asset {href}")
            elif resolve(urljoin(page_url, href)) is None:
                broken[href] += 1
        for href in s.links:
            if href.startswith(("#", "mailto:")):
                continue
            pu = urlparse(href)
            if pu.scheme in ("http", "https"):
                if href.startswith(site_url):
                    href = href[len(origin):]
                else:
                    external[pu.netloc] += 1
                    continue
            checked += 1
            if resolve(urljoin(page_url, href)) is None:
                broken[href] += 1

    sm = out / "sitemap.xml"
    locs = re.findall(r"<loc>([^<]+)</loc>", sm.read_text()) if sm.exists() else []
    sm_bad = [l for l in locs if not l.startswith(site_url) or resolve(l[len(origin):]) is None]
    dup_titles = [(t, n) for t, n in titles.items() if n > 1]

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    nfiles = sum(1 for f in out.rglob("*") if f.is_file())
    kinds = Counter(str(p.relative_to(out)).split("/")[0] if "/" in str(p.relative_to(out)) else "(root)" for p in pages)
    print(f"HTML pages: {len(pages):,}  ({', '.join(f'{k}: {v:,}' for k, v in kinds.most_common())})")
    print(f"files: {nfiles:,}  total size: {total/1e6:.1f} MB  largest page: "
          f"{max(p.stat().st_size for p in pages)/1e3:.0f} KB")
    print(f"internal links checked: {checked:,}  broken: {sum(broken.values())}  external link hosts: {dict(external)}")
    print(f"sitemap URLs: {len(locs):,}  bad: {len(sm_bad)}  pages missing from sitemap: {len(pages) - len(locs)}")
    print(f"duplicate <title>s: {len(dup_titles)}")
    for href, n in broken.most_common(15):
        print("  BROKEN", href, f"x{n}")
    for p in problems[:15]:
        print("  PROBLEM", p)
    for t, n in dup_titles[:5]:
        print("  DUP TITLE", n, t)
    ok = (not broken and not sm_bad and not problems and len(pages) <= MAX_PAGES and total / 1e6 <= MAX_MB)
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
