"""Audit: extract every <a href> and <form action> from public pages
and verify each URL responds. Catches broken buttons & dead links."""
from __future__ import annotations
import os, re, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")

from app import create_app
fc = create_app().test_client()

PAGES = ["/", "/about", "/shop/", "/cart/", "/auth/login", "/auth/register", "/auth/forgot", "/auth/reset"]

LINK_RE = re.compile(r'(?:^|\s)(?:href|action)\s*=\s*"([^"]+)"', re.IGNORECASE)
seen = set()

print("=== Crawling links/buttons ===")
for page in PAGES:
    body = fc.get(page).get_data(as_text=True)
    for href in LINK_RE.findall(body):
        # skip externals and anchors
        if href.startswith(("http://", "https://", "mailto:", "tel:", "data:")):
            continue
        if href.startswith("#"):
            continue
        if href.startswith("javascript:"):
            continue
        # strip query string for the GET probe but keep what's there
        seen.add(href)

print(f"  found {len(seen)} unique internal links")

print("\n=== Probing each (GET) ===")
bad = []
for href in sorted(seen):
    try:
        r = fc.get(href, follow_redirects=False)
        ok = r.status_code in (200, 301, 302, 303)
        mark = "ok " if ok else "!!"
        print(f"  [{mark}] {r.status_code}  {href}")
        if not ok:
            bad.append((href, r.status_code))
    except Exception as exc:
        print(f"  [!!] EXC   {href}  ({exc})")
        bad.append((href, str(exc)))

if bad:
    print(f"\nBroken: {len(bad)}"); [print("  ", x) for x in bad]; sys.exit(1)
print("\nAll buttons / links respond cleanly.")
