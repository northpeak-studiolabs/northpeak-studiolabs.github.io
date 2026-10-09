"""Tell Bing, Yandex and other IndexNow search engines about this site's pages.

Usage: python indexnow.py [--all]
Without --all, sends the product pages plus H-1B pages only when H1B_CHANGED=true (new DOL data).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
BASE = 'https://northpeak-studiolabs.github.io'
KEY_FILE = next((HERE / 'static_root').glob('*.txt'))
KEY = KEY_FILE.read_text().strip()
LOC_RE = re.compile(r'<loc>([^<]+)</loc>')


def main() -> None:
    dist = HERE / 'dist'
    urls = [BASE + '/'] + [f'{BASE}/{p.parent.relative_to(dist).as_posix()}/' for p in dist.glob('*/index.html')
                           if p.parent.name != 'h1b' and (p.parent / 'privacy').exists()]
    root_map = dist / 'sitemap.xml'  # product pages and guides
    if root_map.exists():
        urls += LOC_RE.findall(root_map.read_text(encoding='utf-8'))
    if '--all' in sys.argv or os.environ.get('INDEXNOW_ALL') == 'true' or os.environ.get('H1B_CHANGED') == 'true':
        sitemap = dist / 'h1b' / 'sitemap.xml'
        if sitemap.exists():
            urls += LOC_RE.findall(sitemap.read_text(encoding='utf-8'))
    urls = list(dict.fromkeys(urls))
    print(f'Submitting {len(urls)} URL(s) to IndexNow')
    for i in range(0, len(urls), 10000):
        body = json.dumps({'host': 'northpeak-studiolabs.github.io', 'key': KEY, 'keyLocation': f'{BASE}/{KEY_FILE.name}',
                           'urlList': urls[i:i + 10000]}).encode()
        req = urllib.request.Request('https://api.indexnow.org/indexnow', data=body, method='POST',
                                     headers={'Content-Type': 'application/json; charset=utf-8'})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                print(f'  batch {i // 10000 + 1}: HTTP {resp.status}')
        except urllib.error.HTTPError as exc:
            # Never fail the deploy over this; 403 right after the first deploy means the key isn't verified yet.
            print(f'  batch {i // 10000 + 1}: HTTP {exc.code} {exc.read()[:200]!r}')


if __name__ == '__main__':
    main()
