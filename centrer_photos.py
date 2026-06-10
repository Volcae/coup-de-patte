#!/usr/bin/env python3
"""
Centreur de photos — Coup de Patte
Analyse chaque photo d'animal avec Claude Vision pour détecter
les yeux et calculer le meilleur cadrage automatiquement.

Usage : python centrer_photos.py
Variables d'env : ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""

import requests
import base64
import json
import time
import os
import anthropic
from io import BytesIO

SUPABASE_URL         = os.environ.get("SUPABASE_URL", "https://mbqsaaxaglcemdxmfvkc.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ANTHROPIC_KEY        = os.environ.get("ANTHROPIC_API_KEY", "")

claude_client = None

def get_claude():
    global claude_client
    if not claude_client:
        claude_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    return claude_client


def sb_headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


def charger_animaux_sans_cadrage():
    """Charge les animaux avec photo_url mais sans photo_position personnalisée."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/Animal"
        f"?select=id,nom,espece,photo_url,photo_position,photo_position_vignette"
        f"&photo_url=not.is.null"
        f"&photo_url=not.eq."
        f"&disponible=eq.true"
        f"&or=(photo_position.is.null,photo_position.eq.center center)",
        headers=sb_headers()
    )
    if r.status_code != 200:
        print(f"✗ Erreur chargement: {r.status_code} — {r.text[:100]}")
        return []
    animaux = r.json()
    print(f"→ {len(animaux)} animal(aux) à analyser")
    return animaux


def telecharger_image(url):
    """Télécharge l'image et la convertit en base64."""
    try:
        r = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; CoupDePatte/1.0)"
        })
        if r.status_code != 200:
            return None, None
        content_type = r.headers.get("Content-Type", "image/jpeg")
        if "jpeg" in content_type or "jpg" in content_type:
            media_type = "image/jpeg"
        elif "png" in content_type:
            media_type = "image/png"
        elif "webp" in content_type:
            media_type = "image/webp"
        else:
            media_type = "image/jpeg"
        image_data = base64.standard_b64encode(r.content).decode("utf-8")
        return image_data, media_type
    except Exception as e:
        print(f"  ⚠ Erreur téléchargement: {e}")
        return None, None


def analyser_cadrage(nom, espece, image_data, media_type):
    """Demande à Claude de localiser les yeux et calculer le cadrage optimal."""
    prompt = f"""Cette photo montre {nom or 'un animal'} ({espece or 'animal'}) dans un refuge.

Analyse l'image et détermine le point focal optimal pour centrer la photo sur le visage/les yeux de l'animal.

Réponds UNIQUEMENT en JSON valide :
{{
  "position_x": nombre entre 0 et 100 (% horizontal, 0=gauche, 50=centre, 100=droite),
  "position_y": nombre entre 0 et 100 (% vertical, 0=haut, 50=centre, 100=bas),
  "confiance": "haute" ou "moyenne" ou "faible",
  "description": "une courte phrase expliquant où sont les yeux"
}}

Si l'animal est de dos, dormant ou le visage n'est pas visible, mets position_x=50 et position_y=40 avec confiance "faible"."""

    try:
        msg = get_claude().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        text = msg.content[0].text.strip()
        # Nettoyer les balises markdown si présentes
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"  ⚠ Erreur Claude: {e}")
        return None


def convertir_en_css_position(x, y):
    """Convertit les % en valeur CSS object-position."""
    # Arrondir à 5% près pour avoir des valeurs propres
    x_rounded = round(x / 5) * 5
    y_rounded = round(y / 5) * 5
    
    # Utiliser des mots-clés CSS quand possible
    x_css = "left" if x_rounded <= 10 else "right" if x_rounded >= 90 else "center" if x_rounded == 50 else f"{x_rounded}%"
    y_css = "top" if y_rounded <= 10 else "bottom" if y_rounded >= 90 else "center" if y_rounded == 50 else f"{y_rounded}%"
    
    return f"{x_css} {y_css}"


def mettre_a_jour_cadrage(animal_id, photo_position, photo_position_vignette):
    """Met à jour les positions de cadrage dans Supabase."""
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/Animal?id=eq.{animal_id}",
        headers=sb_headers(),
        json={
            "photo_position": photo_position,
            "photo_position_vignette": photo_position_vignette
        }
    )
    return r.status_code in [200, 201, 204]


def main():
    print("🐾 Centreur de photos — Coup de Patte")
    print("=" * 45)

    if not ANTHROPIC_KEY:
        print("✗ ANTHROPIC_API_KEY manquant"); return
    if not SUPABASE_SERVICE_KEY:
        print("✗ SUPABASE_SERVICE_ROLE_KEY manquant"); return

    animaux = charger_animaux_sans_cadrage()
    if not animaux:
        print("✓ Toutes les photos sont déjà cadrées")
        return

    succes = 0
    ignores = 0
    erreurs = 0

    for a in animaux:
        nom       = a.get("nom") or "?"
        espece    = a.get("espece") or "animal"
        photo_url = a.get("photo_url", "")

        if not photo_url or not photo_url.startswith("http"):
            ignores += 1
            continue

        print(f"\n  {nom} ({espece})")
        print(f"  📸 {photo_url[:60]}...")

        # Télécharger l'image
        image_data, media_type = telecharger_image(photo_url)
        if not image_data:
            print(f"  ✗ Impossible de télécharger la photo")
            erreurs += 1
            time.sleep(1)
            continue

        # Analyser avec Claude Vision
        resultat = analyser_cadrage(nom, espece, image_data, media_type)
        if not resultat:
            erreurs += 1
            time.sleep(1)
            continue

        x = resultat.get("position_x", 50)
        y = resultat.get("position_y", 40)
        confiance = resultat.get("confiance", "faible")
        description = resultat.get("description", "")

        print(f"  👁 Position: {x}% / {y}% — {confiance} — {description}")

        # Ne pas mettre à jour si confiance faible (laisser center center)
        if confiance == "faible":
            print(f"  ⏭ Confiance faible — cadrage par défaut conservé")
            ignores += 1
            time.sleep(0.5)
            continue

        # Calculer les positions CSS
        # Grande photo : légèrement plus haute que la vignette (inclure plus du corps)
        pos_hero    = convertir_en_css_position(x, max(0, y - 10))  # un peu plus haut pour le hero
        pos_vignette = convertir_en_css_position(x, y)              # centré sur les yeux pour vignette

        print(f"  → Hero: {pos_hero} | Vignette: {pos_vignette}")

        if mettre_a_jour_cadrage(a["id"], pos_hero, pos_vignette):
            print(f"  ✓ Cadrage mis à jour")
            succes += 1
        else:
            print(f"  ✗ Erreur mise à jour Supabase")
            erreurs += 1

        time.sleep(1)  # Pause pour ne pas surcharger l'API

    print(f"\n{'=' * 45}")
    print(f"✅ {succes} photo(s) cadrée(s) automatiquement")
    print(f"   {ignores} ignorée(s) (confiance faible ou pas de photo)")
    print(f"   {erreurs} erreur(s)")


if __name__ == "__main__":
    main()
