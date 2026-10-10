"""Build the Northpeak Studio Labs site: product pages and privacy policies -> dist/.

Each folder in products/ holds product.json, privacy.md and images. To start selling, set
"checkout_url" in product.json to the checkout link and "license" to
{"provider": "gumroad", "product_id": "...", "max_uses": 3} or
{"provider": "polar", "organization_id": "...", "benefit_id": "..."}; the extensions' Buy buttons
open <slug>/#pricing, so the link can change here without a new browser-store review.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / 'dist'
SITE = 'Northpeak Studio Labs'
BASE = 'https://northpeak-studiolabs.github.io'
SITEMAPS = ['sitemap.xml', 'h1b/sitemap.xml', 'recallflag/sitemap.xml']

CSS = """
:root{--bg:#fff;--fg:#1d2330;--muted:#5b6475;--line:#e3e6ec;--accent:#2457d6;--accent-ink:#fff;--card:#f6f7fa}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--fg:#e8ebf1;--muted:#a3abba;--line:#2a303b;--accent:#6b93ff;--accent-ink:#0b0e14;--card:#1a1e26}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:0 16px}header{border-bottom:1px solid var(--line)}header .wrap{display:flex;align-items:center;gap:10px;height:56px}
header a{color:var(--fg);text-decoration:none;font-weight:700}a{color:var(--accent)}h1{font-size:2rem;line-height:1.2;margin:32px 0 8px}
.lead{font-size:1.15rem;color:var(--muted);margin:0 0 20px}.hero{display:flex;gap:16px;align-items:center}.hero img{width:72px;height:72px;border-radius:16px}
.shots{display:grid;gap:12px;margin:24px 0}.shots img{width:100%;border:1px solid var(--line);border-radius:10px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:640px){.cols{grid-template-columns:1fr}h1{font-size:1.6rem}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px}.card h3{margin:0 0 8px}
.btn{display:inline-block;background:var(--accent);color:var(--accent-ink);padding:12px 20px;border-radius:10px;font-weight:700;text-decoration:none}
.btn.off{background:var(--line);color:var(--muted);cursor:default}.price{font-size:1.6rem;font-weight:800}
footer{border-top:1px solid var(--line);margin-top:48px;padding:20px 0;color:var(--muted);font-size:.9rem}ul{padding-left:20px}
.products{display:grid;gap:16px;margin:24px 0}.products a.card{display:flex;gap:16px;align-items:center;color:var(--fg);text-decoration:none}.products img{width:56px;height:56px;border-radius:12px}
"""


def page(title: str, desc: str, body: str, depth: int) -> str:
    root = '../' * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><meta name="description" content="{html.escape(desc)}"><style>{CSS}</style></head>
<body><header><div class="wrap"><a href="{root}">{SITE}</a></div></header><main class="wrap">{body}</main>
<footer><div class="wrap">© 2026 {SITE} · <a href="{root}">All products</a></div></footer></body></html>"""


def md_to_html(md: str) -> str:
    out = []
    for block in md.strip().split('\n\n'):
        b = html.escape(block.strip())
        b = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', b)
        b = re.sub(r'`(.+?)`', r'<code>\1</code>', b)
        if b.startswith('# '):
            out.append(f'<h1>{b[2:]}</h1>')
        else:
            out.append(f'<p>{b}</p>')
    return '\n'.join(out)


def li(items: list[str]) -> str:
    return '<ul>' + ''.join(f'<li>{html.escape(i)}</li>' for i in items) + '</ul>'


def product(slug: str, src: Path, related: list[dict] = ()) -> dict:
    p = json.loads((src / 'product.json').read_text())
    dst = OUT / slug
    (dst / 'privacy').mkdir(parents=True, exist_ok=True)
    for img in src.glob('*.png'):
        shutil.copy(img, dst / img.name)
    shots = ''.join(f'<img src="{s.name}" alt="{html.escape(p["name"])} screenshot {i + 1}" loading="lazy">'
                    for i, s in enumerate(sorted(src.glob('screenshot-*.png'))))
    if p.get('checkout_url'):
        buy = f'<a class="btn" href="{html.escape(p["checkout_url"])}">Buy {html.escape(p["pro_name"])}, {p["price"]} once</a>'
    else:
        buy = '<span class="btn off">Pro checkout opens soon</span>'
    links = p.get('store_links', {})
    stores = ' '.join(f'<a class="btn" href="{html.escape(u)}">Add to {html.escape(n.split()[0])}, free</a>' for n, u in links.items())
    body = f"""<div class="hero"><img src="icon-128.png" alt=""><div><h1>{html.escape(p['name'])}</h1><p class="lead">{html.escape(p['tagline'])}</p></div></div>
{('<p>' + stores + ' <a href="#pricing">See Pro</a></p>') if stores else '<p><small>Coming soon to the browser stores.</small></p>'}
<div class="shots">{shots}</div>
<h2>How it works</h2><ol>{''.join(f'<li>{html.escape(s)}</li>' for s in p['how'])}</ol>
<h2>What you get</h2><p>{html.escape(p['fields'])}</p>
<h2 id="pricing">Pricing</h2>
<div class="cols"><div class="card"><h3>Free</h3>{li(p['free'])}</div>
<div class="card"><h3>Pro</h3><p class="price">{p['price']} <small>once, no subscription</small></p>{li(p['pro'])}<p>{buy}</p>
<p><small>After paying, your license key appears on the receipt and in your email. Open the extension, paste it into "Paste license key" and click Activate. Works on up to 3 browsers.</small></p></div></div>
<h2>Who uses it</h2><p>{html.escape(p['who'])}</p>
<h2>Privacy</h2><p>Everything runs in your browser. No account, no tracking, and your data never passes through our servers. <a href="privacy/">Read the privacy policy</a>.</p>
{('<h2>Guides</h2><ul>' + ''.join(f'<li><a href="../guides/{g["slug"]}/">{html.escape(g["title"])}</a></li>' for g in related) + '</ul>') if related else ''}
<p><small>{html.escape(p['note'])}</small></p>"""
    if p.get('license'):  # read by the extension: which payment provider and product a key must belong to
        (dst / 'license.json').write_text(json.dumps(p['license']))
    (dst / 'index.html').write_text(page(f"{p['name']}: {p['tagline']}", p['tagline'], body, 1), encoding='utf-8')
    priv = md_to_html((src / 'privacy.md').read_text())
    (dst / 'privacy' / 'index.html').write_text(page(f"{p['name']} privacy policy", f"Privacy policy for {p['name']}.", priv, 2), encoding='utf-8')
    return p


def guides() -> list[dict]:
    """guides/<slug>/guide.json + body.html -> how-to articles that send search traffic to the products."""
    out = []
    for src in sorted((HERE / 'guides').glob('*/guide.json')):
        g = json.loads(src.read_text()); g['slug'] = src.parent.name
        body = (src.parent / 'body.html').read_text(encoding='utf-8')
        body += f'<p><small>Updated {g["updated"]}.</small></p>'
        dst = OUT / 'guides' / g['slug']
        dst.mkdir(parents=True, exist_ok=True)
        (dst / 'index.html').write_text(page(g['title'], g['description'], body, 2), encoding='utf-8')
        out.append(g)
    if out:
        items = ''.join(f'<a class="card" href="{g["slug"]}/"><div><strong>{html.escape(g["title"])}</strong><br>'
                        f'<span>{html.escape(g["description"])}</span></div></a>' for g in out)
        (OUT / 'guides' / 'index.html').write_text(page(f'Guides | {SITE}', 'How-to guides for exporting data from the web to spreadsheets.',
                                                       f'<h1>Guides</h1><div class="products">{items}</div>', 1), encoding='utf-8')
    return out


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    cards = []
    gs = guides()
    for src in sorted((HERE / 'products').iterdir()):
        if (src / 'product.json').exists():
            p = product(src.name, src, [g for g in gs if g.get('product') == src.name])
            cards.append(f'<a class="card" href="{src.name}/"><img src="{src.name}/icon-128.png" alt=""><div><strong>{html.escape(p["name"])}</strong><br>'
                         f'<span>{html.escape(p["tagline"])}</span></div></a>')
    body = f'<h1>{SITE}</h1><p class="lead">Small, private browser tools that export the data you need. Pay once, no subscriptions.</p><div class="products">{"".join(cards)}</div>'
    body += ('<h2>Free data sites</h2><div class="products">'
             '<a class="card" href="h1b/"><div><strong>H-1B Salary Lookup</strong><br><span>Offered salaries from 485,000+ certified H-1B filings, by employer, job title and city.</span></div></a>'
             '<a class="card" href="recallflag/"><div><strong>RecallFlag</strong><br><span>Search U.S. vehicle, food, drug and product recalls, updated daily.</span></div></a></div>')
    if gs:
        body += '<h2>Guides</h2><div class="products">' + ''.join(
            f'<a class="card" href="guides/{g["slug"]}/"><div><strong>{html.escape(g["title"])}</strong></div></a>' for g in gs) + '</div>'
    (OUT / 'index.html').write_text(page(SITE, 'Small, private browser tools. Pay once, no subscriptions.', body, 0), encoding='utf-8')
    (OUT / '.nojekyll').write_text('')
    for f in (HERE / 'static_root').rglob('*'):  # IndexNow key file, pinleads/license.json
        if f.is_file():
            dst = OUT / f.relative_to(HERE / 'static_root')
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dst)
    urls = [BASE + '/'] + [f'{BASE}/{d.parent.relative_to(OUT).as_posix()}/' for d in sorted(OUT.glob('*/index.html'))
                           if (d.parent / 'privacy').exists()]
    urls += [f'{BASE}/guides/'] + [f'{BASE}/guides/{g["slug"]}/' for g in gs] if gs else []
    (OUT / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                     + ''.join(f'<url><loc>{u}</loc></url>' for u in urls) + '</urlset>\n')
    (OUT / 'robots.txt').write_text('User-agent: *\nAllow: /\nDisallow: /recallflag/search/\n\n' + ''.join(f'Sitemap: {BASE}/{m}\n' for m in SITEMAPS))
    print('Built', len(cards), 'product page(s)')


if __name__ == '__main__':
    main()
