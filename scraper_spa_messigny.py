#!/usr/bin/env python3
"""
Scraper Coup de Patte - SPA Messigny (WooCommerce WordPress)
Flux complet : scraping -> creation compte Auth -> fiche Refuge -> ScrapingQueue -> email invitation
Requires: pip install requests beautifulsoup4 anthropic
"""

import requests
from bs4 import BeautifulSoup
from datetime import date
import json
import time
import os
import re

# == CONFIGURATION - toutes les cles viennent des secrets GitHub ==
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "https://mbqsaaxaglcemdxmfvkc.supabase.co")
SUPABASE_KEY         = os.environ.get("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ANTHROPIC_KEY        = os.environ.get("ANTHROPIC_API_KEY", "")
RESEND_KEY           = os.environ.get("RESEND_API_KEY", "")

# Infos du refuge - passees via workflow_dispatch inputs
REFUGE_NOM    = os.environ.get("REFUGE_NOM", "SPA Messigny")
REFUGE_EMAIL  = os.environ.get("REFUGE_EMAIL", "")
REFUGE_VILLE  = os.environ.get("REFUGE_VILLE", "Messigny-et-Vantoux")
REFUGE_SITE   = os.environ.get("REFUGE_SITE", "https://www.spa-messigny.fr")
REFUGE_TEL    = os.environ.get("REFUGE_TEL", "")

SITE_URL    = REFUGE_SITE
ANIMAUX_URL = f"{SITE_URL}/adoption-animaux/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CoupDePatte/1.0; +https://coup-de-patte.fr)"
}


# == HELPERS SUPABASE ==

def sb_headers(use_service=True):
    key = SUPABASE_SERVICE_KEY if use_service else SUPABASE_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


# == ETAPE 1 : SCRAPING ==

def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  Erreur fetch {url}: {e}")
        return None


def scraper_liste_animaux():
    soup = get_soup(ANIMAUX_URL)
    if not soup:
        return []
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/produit/" in href and href not in urls:
            urls.append(href)
    print(f"  {len(urls)} animaux trouves")
    return urls


def calculer_age(date_naissance_str):
    try:
        parts = date_naissance_str.strip().split("/")
        if len(parts) == 3:
            jour, mois, annee = int(parts[0]), int(parts[1]), int(parts[2])
            annee_complete = 2000 + annee if annee <= date.today().year - 2000 else 1900 + annee
            naissance = date(annee_complete, mois, jour)
            age = (date.today() - naissance).days // 365
            return age, naissance.isoformat()
    except:
        pass
    return None, None


def scraper_fiche_animal(url):
    soup = get_soup(url)
    if not soup:
        return None

    animal = {}
    h1 = soup.find("h1")
    animal["nom"] = h1.text.strip() if h1 else ""

    breadcrumb = soup.find_all("a", href=True)
    animal["espece"] = "chien"
    for a in breadcrumb:
        if "chats" in a.get("href", "").lower():
            animal["espece"] = "chat"
            break
        elif "chiens" in a.get("href", "").lower():
            animal["espece"] = "chien"
            break

    contenu = ""
    for elem in soup.find_all(["p", "li", "div"]):
        texte = elem.get_text(separator=" ", strip=True)
        if texte and len(texte) > 3:
            contenu += texte + "\n"

    contenu_lower = contenu.lower()
    animal["sexe"] = "femelle" if "femelle" in contenu_lower else ("male" if "male" in contenu_lower else None)

    lines = [l.strip() for l in contenu.split("\n") if l.strip()]
    race = None
    for i, line in enumerate(lines):
        if any(x in line.lower() for x in ["male", "femelle"]):
            if "castre" in line.lower() or "sterilise" in line.lower():
                if i + 1 < len(lines):
                    race = lines[i + 1]
            else:
                parts = line.split(" ", 1)
                if len(parts) > 1:
                    race = parts[1]
            break
    animal["race"] = race

    date_pattern = re.search(r"\b(\d{2}/\d{2}/\d{2,4})\b", contenu)
    if date_pattern:
        age, _ = calculer_age(date_pattern.group(1))
        animal["age_annees"] = age
    else:
        animal["age_annees"] = None

    description_lines = []
    for line in lines:
        if any(x in line for x in ["250 269", "Lundi", "Mardi", "Contact", "Refuge", "Route"]):
            continue
        if len(line) > 20 and not re.match(r"^\d{2}/\d{2}/\d{2}", line):
            description_lines.append(line)
    animal["description"] = " ".join(description_lines[:5])

    og_image = soup.find("meta", property="og:image")
    if og_image:
        animal["photo_url"] = og_image.get("content", "")
    else:
        img = soup.find("img", src=lambda s: s and "wp-content/uploads" in s)
        animal["photo_url"] = img["src"] if img else ""

    animal["source_url"] = url
    return animal


def analyser_avec_claude(animal):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""Tu es un expert en bien-etre animal. Analyse cette fiche d'adoption et extrait les informations structurees.

Animal: {animal.get('nom', '')}
Espece: {animal.get('espece', '')}
Race: {animal.get('race', '')}
Sexe: {animal.get('sexe', '')}
Age: {animal.get('age_annees', '')} ans
Description: {animal.get('description', '')}

Reponds UNIQUEMENT en JSON avec ces champs (true/false/null si inconnu):
{{
  "compat_enfants_moins13": true/false/null,
  "compat_chats": true/false/null,
  "compat_chiens": true/false/null,
  "experience_requise": "debutant"/"intermediaire"/"experimente",
  "energie": "faible"/"moyen"/"eleve",
  "vie_en_refuge": "Tres bien"/"Bien"/"Moyennement bien"/"Difficilement"/"Tres difficilement"/null,
  "besoins_medicaux": "aucun"/"legers"/"lourds",
  "gabarit": "petit"/"moyen"/"grand"/null
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"  Erreur Claude API: {e}")
        return {}


# == ETAPE 2 : CREER COMPTE SUPABASE AUTH ==

def creer_compte_auth(email):
    """Cree un compte Auth sans mot de passe (email_confirm: true)"""
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "email": email,
            "email_confirm": True,
            "password": None
        }
    )
    if r.status_code in [200, 201]:
        user_id = r.json().get("id")
        print(f"  OK Compte Auth cree - UUID : {user_id}")
        return user_id
    elif r.status_code == 422 and "already" in r.text.lower():
        # Compte existant - recuperer l'UUID
        r2 = requests.get(
            f"{SUPABASE_URL}/auth/v1/admin/users?email={email}",
            headers={
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"
            }
        )
        if r2.status_code == 200:
            users = r2.json().get("users", [])
            if users:
                print(f"  INFO Compte existant - UUID : {users[0]['id']}")
                return users[0]["id"]
    print(f"  ERREUR creation compte Auth: {r.status_code} - {r.text[:150]}")
    return None


# == ETAPE 3 : CREER FICHE REFUGE ==

def creer_fiche_refuge(user_id):
    """Cree la fiche dans la table Refuge"""
    payload = {
        "utilisateur": user_id,
        "nom": REFUGE_NOM,
        "ville": REFUGE_VILLE,
        "site_web": REFUGE_SITE,
        "valide_par_admin": True
    }
    if REFUGE_EMAIL:
        payload["email"] = REFUGE_EMAIL
    if REFUGE_TEL:
        payload["telephone"] = REFUGE_TEL

    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/Refuge",
        headers=sb_headers(),
        json=payload
    )
    if r.status_code in [200, 201]:
        data = r.json()
        refuge_id = data[0]["id"] if isinstance(data, list) else data.get("id")
        print(f"  OK Fiche refuge creee - ID : {refuge_id}")
        return refuge_id
    print(f"  ERREUR creation refuge: {r.status_code} - {r.text[:150]}")
    return None


# == ETAPE 4 : ENVOYER DANS SCRAPINGQUEUE ==

def envoyer_supabase(animal, analyse, refuge_id):
    payload = {
        "refuge_id": refuge_id,
        "nom": animal.get("nom"),
        "espece": animal.get("espece"),
        "race": animal.get("race"),
        "age_annees": animal.get("age_annees"),
        "sexe": animal.get("sexe"),
        "description": animal.get("description"),
        "photo_url": animal.get("photo_url", ""),
        "donnees_brutes": json.dumps(animal, ensure_ascii=False),
        "donnees_extraites": json.dumps({**animal, **analyse}, ensure_ascii=False),
        "statut": "en_attente"
    }
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/ScrapingQueue",
        headers=sb_headers(),
        json=payload
    )
    if r.status_code in [200, 201]:
        print(f"  OK {animal.get('nom')} -> file d'attente")
    else:
        print(f"  ERREUR ScrapingQueue: {r.status_code} - {r.text[:100]}")


# == ETAPE 5 : EMAIL D'INVITATION VIA RESEND ==
# DESACTIVE EN MODE TEST - decommenter quand pret pour la production

def envoyer_email_invitation(email, nom_refuge):
    if not RESEND_KEY or not email:
        print("  INFO Email d'invitation ignore (RESEND_KEY ou email manquant)")
        return

    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "from": "Coup de Patte <contact@coup-de-patte.fr>",
            "to": [email],
            "subject": "Vos animaux sont sur Coup de Patte !",
            "html": f"""
<div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:32px 24px;color:#2D4A3E">
  <h2 style="font-size:1.4rem;margin-bottom:16px">Vos animaux sont sur Coup de Patte !</h2>
  <p style="color:#7A6E65;margin-bottom:16px">Bonjour,</p>
  <p style="color:#7A6E65;line-height:1.7;margin-bottom:16px">
    Nous avons referencé votre refuge <strong>{nom_refuge}</strong> et vos animaux sur
    <a href="https://coup-de-patte.fr" style="color:#4A7C59">Coup de Patte</a>,
    plateforme d'adoption qui met en avant les animaux qui attendent depuis longtemps une famille.
  </p>
  <p style="color:#7A6E65;line-height:1.7;margin-bottom:24px">
    Pour acceder a votre espace et gerer vos animaux :
  </p>
  <ol style="color:#7A6E65;line-height:2;margin-bottom:28px;padding-left:20px">
    <li>Rendez-vous sur <a href="https://coup-de-patte.fr/coup-de-patte-login.html" style="color:#4A7C59">coup-de-patte.fr/coup-de-patte-login.html</a></li>
    <li>Cliquez sur Mot de passe oublie</li>
    <li>Entrez votre adresse email</li>
    <li>Suivez le lien recu pour creer votre mot de passe</li>
  </ol>
  <p style="color:#7A6E65;line-height:1.7;margin-bottom:16px">
    Votre espace vous permet de modifier les fiches animaux, ajouter des photos et mettre a jour les disponibilites.
  </p>
  <div style="background:#F4F1E8;border-radius:14px;padding:18px 22px;margin-bottom:24px">
    <p style="margin:0;color:#7A6E65;font-size:0.88rem;line-height:1.6">
      Si vous ne souhaitez pas etre reference sur Coup de Patte,
      repondez simplement a cet email - nous retirerons votre refuge immediatement.
    </p>
  </div>
  <hr style="border:none;border-top:1px solid #e0d8cf;margin:24px 0">
  <p style="color:#A89E96;font-size:0.78rem;margin:0;text-align:center">
    L'equipe Coup de Patte
  </p>
</div>"""
        }
    )
    if r.status_code in [200, 201]:
        print(f"  OK Email d'invitation envoye a {email}")
    else:
        print(f"  ERREUR Resend: {r.status_code} - {r.text[:100]}")


# == MAIN ==

def main():
    print("Coup de Patte - Scraper SPA Messigny")
    print("=" * 40)

    if not ANTHROPIC_KEY:
        print("ERREUR: ANTHROPIC_API_KEY manquant"); return
    if not SUPABASE_SERVICE_KEY:
        print("ERREUR: SUPABASE_SERVICE_ROLE_KEY manquant"); return

    # Etape 2 : Creer le compte Auth
    print(f"\nCreation du compte Auth pour {REFUGE_EMAIL or 'email non renseigne'}...")
    user_id = None
    if REFUGE_EMAIL:
        user_id = creer_compte_auth(REFUGE_EMAIL)
    else:
        print("  INFO Pas d'email - compte Auth ignore")

    # Etape 3 : Creer la fiche refuge
    print(f"\nCreation de la fiche refuge {REFUGE_NOM}...")
    refuge_id = None
    if user_id:
        refuge_id = creer_fiche_refuge(user_id)
    if not refuge_id:
        print("  ERREUR Impossible de creer le refuge - arret"); return

    # Etape 1 : Scraping
    print(f"\nRecuperation des animaux sur {ANIMAUX_URL}...")
    urls = scraper_liste_animaux()
    if not urls:
        print("Aucun animal trouve."); return

    # Etape 4 : Analyser et envoyer dans ScrapingQueue
    print(f"\nScraping de {len(urls)} fiches...")
    succes = 0
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] {url.split('/')[-2]}")
        animal = scraper_fiche_animal(url)
        if not animal or not animal.get("nom"):
            print("  INFO Fiche invalide, ignoree"); continue

        print(f"  {animal['nom']} | {animal['espece']} | {animal.get('race', '-')} | {animal.get('age_annees', '-')} ans")
        print("  Analyse Claude API...")
        analyse = analyser_avec_claude(animal)
        print(f"  Energie: {analyse.get('energie')} | Experience: {analyse.get('experience_requise')}")

        envoyer_supabase(animal, analyse, refuge_id)
        succes += 1
        time.sleep(1)

    # Etape 5 : Email d'invitation - DESACTIVE EN MODE TEST
    print(f"\nEmail d'invitation desactive (mode test)")
    # envoyer_email_invitation(REFUGE_EMAIL, REFUGE_NOM)
    # Decommenter la ligne ci-dessus quand pret pour la production

    print(f"\nTermine - {succes}/{len(urls)} animaux en file d'attente")
    print(f"Refuge ID : {refuge_id}")


if __name__ == "__main__":
    main()
