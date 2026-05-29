#!/usr/bin/env python3
"""
Scraper Coup de Patte - SPA Messigny (WooCommerce WordPress)
Usage: python3 scraper_spa_messigny.py
Requires: pip install requests beautifulsoup4 anthropic supabase
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
import json
import time
import os

# ══ CONFIGURATION ══
SUPABASE_URL = "https://mbqsaaxaglcemdxmfvkc.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1icXNhYXhhZ2xjZW1keG1mdmtjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc5MjAwMTQsImV4cCI6MjA5MzQ5NjAxNH0.lGK0LL5h-4N4DqMVy2Q_SKJgnzuy7BPQJEtSsc8plfk"
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
REFUGE_ID = "6d191cc1-d38f-4a0a-afb5-9ca7086ff896"

SITE_URL = "https://www.spa-messigny.fr"
ANIMAUX_URL = f"{SITE_URL}/adoption-animaux/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CoupDePatte/1.0; +https://coup-de-patte.fr)"
}

def get_soup(url):
    """Récupère et parse une page HTML"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"Erreur fetch {url}: {e}")
        return None

def scraper_liste_animaux():
    """Récupère toutes les URLs des fiches animaux"""
    soup = get_soup(ANIMAUX_URL)
    if not soup:
        return []
    
    urls = []
    # Les animaux sont des liens vers /produit/NOM/
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/produit/" in href and href not in urls:
            urls.append(href)
    
    print(f"  {len(urls)} animaux trouvés")
    return urls

def calculer_age(date_naissance_str):
    """Calcule l'âge en années depuis une date au format DD/MM/YY"""
    try:
        # Format 07/03/15 = 07 mars 2015
        parts = date_naissance_str.strip().split("/")
        if len(parts) == 3:
            jour, mois, annee = int(parts[0]), int(parts[1]), int(parts[2])
            # Si l'année est < 100, ajouter 2000 (ou 1900 si > année courante)
            annee_complete = 2000 + annee if annee <= date.today().year - 2000 else 1900 + annee
            naissance = date(annee_complete, mois, jour)
            age = (date.today() - naissance).days // 365
            return age, naissance.isoformat()
    except:
        pass
    return None, None

def scraper_fiche_animal(url):
    """Scrape une fiche animal individuelle"""
    soup = get_soup(url)
    if not soup:
        return None
    
    animal = {}
    
    # Nom (titre h1)
    h1 = soup.find("h1")
    animal["nom"] = h1.text.strip() if h1 else ""
    
    # Déterminer l'espèce depuis le fil d'Ariane
    breadcrumb = soup.find_all("a", href=True)
    animal["espece"] = "chien"  # par défaut
    for a in breadcrumb:
        if "chats" in a.get("href", "").lower():
            animal["espece"] = "chat"
            break
        elif "chiens" in a.get("href", "").lower():
            animal["espece"] = "chien"
            break
    
    # Contenu principal de la fiche
    contenu = ""
    for elem in soup.find_all(["p", "li", "div"]):
        texte = elem.get_text(separator=" ", strip=True)
        if texte and len(texte) > 3:
            contenu += texte + "\n"
    
    # Sexe (chercher "Mâle" ou "Femelle" dans le contenu)
    contenu_lower = contenu.lower()
    if "femelle" in contenu_lower:
        animal["sexe"] = "femelle"
    elif "mâle" in contenu_lower or "male" in contenu_lower:
        animal["sexe"] = "male"
    else:
        animal["sexe"] = None
    
    # Race (ligne après le sexe, avant la date)
    lines = [l.strip() for l in contenu.split("\n") if l.strip()]
    race = None
    for i, line in enumerate(lines):
        if any(x in line.lower() for x in ["mâle", "femelle", "male"]):
            # La race est souvent la ligne suivante ou sur la même ligne
            if "castré" in line.lower() or "stérilisé" in line.lower():
                # Format: "Mâle castré\nCroisé Epagneul"
                if i + 1 < len(lines):
                    race = lines[i + 1]
            else:
                parts = line.split(" ", 1)
                if len(parts) > 1:
                    race = parts[1]
            break
    animal["race"] = race
    
    # Date de naissance (format DD/MM/YY ou DD/MM/YYYY)
    import re
    date_pattern = re.search(r"\b(\d{2}/\d{2}/\d{2,4})\b", contenu)
    if date_pattern:
        age, date_iso = calculer_age(date_pattern.group(1))
        animal["age_annees"] = age
    else:
        animal["age_annees"] = None
    
    # Description (texte libre)
    description_lines = []
    for line in lines:
        # Ignorer les lignes techniques
        if any(x in line for x in ["250 269", "©", "Lundi", "Mardi", "Contact", "Refuge", "Route"]):
            continue
        if len(line) > 20 and not re.match(r"^\d{2}/\d{2}/\d{2}", line):
            description_lines.append(line)
    animal["description"] = " ".join(description_lines[:5])  # Max 5 lignes
    
    # Photo principale (og:image ou première img dans le contenu)
    og_image = soup.find("meta", property="og:image")
    if og_image:
        animal["photo_url"] = og_image.get("content", "")
    else:
        img = soup.find("img", src=lambda s: s and "wp-content/uploads" in s)
        animal["photo_url"] = img["src"] if img else ""
    
    # URL source
    animal["source_url"] = url
    
    return animal

def analyser_avec_claude(animal):
    """Utilise Claude API pour extraire les données structurées de la description"""
    import anthropic
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    
    prompt = f"""Tu es un expert en bien-être animal. Analyse cette fiche d'adoption et extrait les informations structurées.

Animal: {animal.get('nom', '')}
Espèce: {animal.get('espece', '')}
Race: {animal.get('race', '')}
Sexe: {animal.get('sexe', '')}
Age: {animal.get('age_annees', '')} ans
Description: {animal.get('description', '')}

Réponds UNIQUEMENT en JSON avec ces champs (true/false/null si inconnu):
{{
  "compat_enfants_moins13": true/false/null,
  "compat_chats": true/false/null,
  "compat_chiens": true/false/null,
  "experience_requise": "debutant"/"intermediaire"/"experimente",
  "energie": "faible"/"moyen"/"eleve",
  "vie_en_refuge": "Très bien"/"Bien"/"Moyennement bien"/"Difficilement"/"Très difficilement"/null,
  "besoins_medicaux": "aucun"/"legers"/"lourds",
  "gabarit": "petit"/"moyen"/"grand"/null,
  "enfin_moi_raison": "liste des raisons séparées par virgule ou null"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        # Nettoyer les backticks si présents
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"  Erreur Claude API: {e}")
        return {}

def envoyer_supabase(animal, analyse):
    """Envoie les données dans ScrapingQueue pour validation"""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "refuge": REFUGE_ID,
        "donnees_brutes": json.dumps(animal, ensure_ascii=False),
        "donnees_extraites": json.dumps({**animal, **analyse}, ensure_ascii=False),
        "photo_url": animal.get("photo_url", ""),
        "statut": "en_attente"
    }
    
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/ScrapingQueue",
        headers=headers,
        json=payload
    )
    
    if r.status_code in [200, 201]:
        print(f"  ✅ {animal.get('nom')} envoyé en file d'attente")
    else:
        print(f"  ❌ Erreur Supabase: {r.status_code} - {r.text[:100]}")

def main():
    print("🐾 Coup de Patte - Scraper SPA Messigny")
    print("=" * 40)
    
    print("\n📋 Récupération de la liste des animaux...")
    urls = scraper_liste_animaux()
    
    if not urls:
        print("Aucun animal trouvé.")
        return
    
    print(f"\n🔍 Scraping de {len(urls)} fiches...")
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] {url.split('/')[-2]}")
        
        # Scraper la fiche
        animal = scraper_fiche_animal(url)
        if not animal or not animal.get("nom"):
            print("  ⚠️ Fiche invalide, ignorée")
            continue
        
        print(f"  Nom: {animal['nom']} | Espèce: {animal['espece']} | Race: {animal['race']} | Age: {animal['age_annees']} ans")
        
        # Analyser avec Claude
        print("  🤖 Analyse Claude API...")
        analyse = analyser_avec_claude(animal)
        print(f"  Énergie: {analyse.get('energie')} | Expérience: {analyse.get('experience_requise')} | Enfants: {analyse.get('compat_enfants_moins13')}")
        
        # Envoyer dans Supabase
        envoyer_supabase(animal, analyse)
        
        # Pause pour ne pas surcharger les serveurs
        time.sleep(1)
    
    print(f"\n✅ Scraping terminé — {len(urls)} animaux en file d'attente dans le superadmin")

if __name__ == "__main__":
    main()
