#!/usr/bin/env python3
"""
Générateur de sitemap — Coup de Patte
Génère un sitemap.xml avec toutes les pages statiques + fiches animaux + pages refuges.

Usage : python generer_sitemap.py
Variables d'env : SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""

import requests
import os
from datetime import date

SUPABASE_URL         = os.environ.get("SUPABASE_URL", "https://mbqsaaxaglcemdxmfvkc.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BASE_URL             = "https://coup-de-patte.fr"
TODAY                = date.today().isoformat()

def sb_headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }

def url_entry(loc, priority="0.5", changefreq="weekly", lastmod=None):
    lm = f"\n    <lastmod>{lastmod or TODAY}</lastmod>" if lastmod else ""
    return f"""  <url>
    <loc>{loc}</loc>{lm}
    <changefreq>{changefreq}</changefreq>
    <priority>{priority}</priority>
  </url>"""

def main():
    print("🐾 Générateur de sitemap — Coup de Patte")
    print("=" * 45)

    urls = []

    # ── Pages statiques ──────────────────────────────
    pages_statiques = [
        ("",                                "1.0",  "daily"),
        ("coup-de-patte-refuges.html",      "0.9",  "daily"),
        ("coup-de-patte-enfin-moi.html",    "0.8",  "daily"),
        ("coup-de-patte-apropos.html",      "0.6",  "monthly"),
        ("coup-de-patte-contact.html",      "0.5",  "monthly"),
        ("coup-de-patte-cgu.html",          "0.3",  "monthly"),
    ]
    for path, priority, changefreq in pages_statiques:
        loc = BASE_URL + ("/" if not path else "/" + path)
        urls.append(url_entry(loc, priority, changefreq, TODAY))
    print(f"✓ {len(pages_statiques)} pages statiques")

    # ── Fiches animaux ──────────────────────────────
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/Animal?select=id,nom,updated_at&disponible=eq.true",
        headers=sb_headers()
    )
    animaux = r.json() if r.status_code == 200 else []
    for a in animaux:
        lastmod = (a.get("updated_at") or TODAY)[:10]
        loc = f"{BASE_URL}/coup-de-patte-fiche.html?id={a['id']}"
        urls.append(url_entry(loc, "0.8", "weekly", lastmod))
    print(f"✓ {len(animaux)} fiches animaux")

    # ── Pages refuges ──────────────────────────────
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/Refuge?select=id,updated_at",
        headers=sb_headers()
    )
    refuges = r.json() if r.status_code == 200 else []
    for ref in refuges:
        lastmod = (ref.get("updated_at") or TODAY)[:10]
        loc = f"{BASE_URL}/coup-de-patte-refuge.html?id={ref['id']}"
        urls.append(url_entry(loc, "0.7", "weekly", lastmod))
    print(f"✓ {len(refuges)} pages refuges")

    # ── Générer le XML ──────────────────────────────
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += '\n'.join(urls)
    xml += '\n</urlset>'

    with open("sitemap.xml", "w", encoding="utf-8") as f:
        f.write(xml)

    total = len(urls)
    print(f"\n{'=' * 45}")
    print(f"✅ sitemap.xml généré — {total} URL(s)")
    print(f"   → {BASE_URL}/sitemap.xml")

if __name__ == "__main__":
    main()
