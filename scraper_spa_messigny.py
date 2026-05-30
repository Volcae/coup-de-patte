#!/usr/bin/env python3
"""
Scraper Coup de Patte - SPA Messigny (WooCommerce WordPress)
Flux : scraping -> creation compte Auth -> fiche Refuge -> ScrapingQueue
Requires: pip install requests beautifulsoup4 anthropic
"""

import requests
from bs4 import BeautifulSoup
from datetime import date
import json
import time
import os
import re

# == CONFIGURATION ==
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "https://mbqsaaxaglcemdxmfvkc.supabase.co")
SUPABASE_KEY         = os.environ.get("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ANTHROPIC_KEY        = os.environ.get("ANTHROPIC_API_KEY", "")
RESEND_KEY           = os.environ.get("RESEND_API_KEY", "")

REFUGE_NOM    = os.environ.get("REFUGE_NOM", "SPA Messigny")
REFUGE_EMAIL  = os.environ.get("REFUGE_EMAIL", "")  # passé via input ou extrait du site
REFUGE_VILLE  = os.environ.get("REFUGE_VILLE", "Messigny-et-Vantoux")
REFUGE_SITE   = os.environ.get("REFUGE_SITE", "https://www.spa-messigny.fr")
REFUGE_TEL    = os.environ.get("REFUGE_TEL", "")

SITE_URL    = REFUGE_SITE
ANIMAUX_URL = f"{SITE_URL}/adoption-animaux/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CoupDePatte/1.0; +https://coup-de-patte.fr)"
}


def sb_headers(use_service=True):
    key = SUPABASE_SERVICE_KEY if use_service else SUPABASE_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  Erreur fetch {url}: {e}")
        return None


# == EXTRACTION EMAIL DEPUIS LE SITE ==

def extraire_email_site():
    """Cherche un lien mailto: sur la page d'accueil du refuge"""
    soup = get_soup(SITE_URL)
    if not soup:
        return None
    for a in soup.find_all("a", href=True):
        if a["href"].startswith("mailto:"):
            email = a["href"].replace("mailto:", "").strip().split("?")[0]
            if email and "@" in email:
                print(f"  Email extrait du site : {email}")
                return email
    return None


# == SCRAPING ANIMAUX ==

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

    # Mots-clés qui signalent la fin de la description utile
    STOP_WORDS = [
        "Contact", "Refuge de Jouvence", "Route du Val", "Messigny",
        "horaires", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche",
        "Mentions légales", "Conseil d'administration", "Tout droits", "Création Agence",
        "Plan du site", "MagicWeb", "Suivre", "250 26", "250 27", "refugedejouvence",
        "03 80", "@gmail", "Retour", "Animaux >"
    ]
    description_lines = []
    for line in lines:
        # Arrêter dès qu'on rencontre un mot-clé de fin
        if any(stop in line for stop in STOP_WORDS):
            break
        # Ignorer les lignes trop courtes ou techniques
        if len(line) < 20:
            continue
        if re.match(r"^\d{2}/\d{2}/\d{2}", line):
            continue
        # Ignorer le nom de l'animal en majuscules
        if line == line.upper() and len(line) < 30:
            continue
        description_lines.append(line)
    # Garder uniquement les lignes de description réelle (max 800 caractères)
    description = " ".join(description_lines)
    animal["description"] = description[:800].strip()

    og_image = soup.find("meta", property="og:image")
    if og_image:
        animal["photo_url"] = og_image.get("content", "")
    else:
        img = soup.find("img", src=lambda s: s and "wp-content/uploads" in s)
        animal["photo_url"] = img["src"] if img else ""

    animal["source_url"] = url
    # Stocker le texte brut complet (filtré des infos refuge) pour Claude
    animal["texte_brut"] = " ".join(description_lines)[:3000]
    return animal


def analyser_avec_claude(animal):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""Tu es un expert en bien-etre animal. Lis attentivement ce texte brut extrait d'une fiche d'adoption et extrais UNIQUEMENT les informations utiles.

TEXTE BRUT:
{animal.get('texte_brut', animal.get('description', ''))}

Reponds UNIQUEMENT en JSON valide, sans commentaire, avec exactement ces champs:
{{
  "description_propre": "description courte et claire de l'animal en 2-3 phrases maximum, sans adresse ni horaires ni mentions legales",
  "sexe": "male"/"femelle"/null,
  "sterilise": true/false/null,
  "race": "race exacte ou null",
  "age_annees": nombre entier ou null,
  "gabarit": "petit"/"moyen"/"grand"/null,
  "energie": "faible"/"moyen"/"eleve"/null,
  "compat_enfants_moins13": true/false/null,
  "compat_chats": true/false/null,
  "compat_chiens": true/false/null,
  "experience_requise": "debutant"/"intermediaire"/"experimente"/null,
  "besoins_medicaux": "aucun"/"legers"/"lourds"/null,
  "vie_en_refuge": "Tres bien"/"Bien"/"Moyennement bien"/"Difficilement"/"Tres difficilement"/null,
  "origine": "abandon"/"trouve"/"saisie"/"sauvetage_elevage"/"transfert"/null
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"  Erreur Claude API: {e}")
        return {}


# == SUPABASE AUTH ==

def chercher_refuge_existant(email):
    """Cherche un refuge existant par email dans Supabase"""
    if not email:
        return None
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/Refuge?email=eq.{email}&select=id",
        headers=sb_headers()
    )
    if r.status_code == 200:
        data = r.json()
        if data and len(data) > 0:
            return data[0]['id']
    # Chercher aussi par nom
    nom_encode = REFUGE_NOM.replace(' ', '%20')
    r2 = requests.get(
        f"{SUPABASE_URL}/rest/v1/Refuge?nom=eq.{nom_encode}&select=id",
        headers=sb_headers()
    )
    if r2.status_code == 200:
        data2 = r2.json()
        if data2 and len(data2) > 0:
            return data2[0]['id']
    return None


def creer_compte_auth(email):
    r = requests.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json"
        },
        json={"email": email, "email_confirm": True, "password": None}
    )
    if r.status_code in [200, 201]:
        user_id = r.json().get("id")
        print(f"  OK Compte Auth cree - UUID : {user_id}")
        return user_id
    elif r.status_code == 422 and "already" in r.text.lower():
        r2 = requests.get(
            f"{SUPABASE_URL}/auth/v1/admin/users?email={email}",
            headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"}
        )
        if r2.status_code == 200:
            users = r2.json().get("users", [])
            if users:
                print(f"  INFO Compte existant - UUID : {users[0]['id']}")
                return users[0]["id"]
    print(f"  ERREUR Auth: {r.status_code} - {r.text[:150]}")
    return None


def creer_fiche_refuge(user_id, email):
    payload = {
        "utilisateur": user_id,
        "nom": REFUGE_NOM,
        "ville": REFUGE_VILLE,
        "site_web": REFUGE_SITE,
        "valide_par_admin": True
    }
    if email:
        payload["email"] = email
    if REFUGE_TEL:
        payload["telephone"] = REFUGE_TEL

    r = requests.post(f"{SUPABASE_URL}/rest/v1/Refuge", headers=sb_headers(), json=payload)
    if r.status_code in [200, 201]:
        data = r.json()
        refuge_id = data[0]["id"] if isinstance(data, list) else data.get("id")
        print(f"  OK Fiche refuge creee - ID : {refuge_id}")
        return refuge_id
    print(f"  ERREUR Refuge: {r.status_code} - {r.text[:150]}")
    return None


def envoyer_supabase(animal, analyse, refuge_id):
    payload = {
        "refuge": refuge_id,
        "nom": animal.get("nom"),
        "espece": animal.get("espece"),
        "race": animal.get("race"),
        "age_annees": animal.get("age_annees"),
        "sexe": animal.get("sexe"),
        "description": animal.get("description"),
        "photo_url": animal.get("photo_url", ""),
        "donnees_brutes": json.dumps(animal, ensure_ascii=False),
        "donnees_extraites": json.dumps({**animal, **analyse}, ensure_ascii=False),
        "nom": analyse.get("nom") or animal.get("nom"),
        "sexe": analyse.get("sexe") or animal.get("sexe"),
        "race": analyse.get("race") or animal.get("race"),
        "age_annees": analyse.get("age_annees") or animal.get("age_annees"),
        "description": analyse.get("description_propre") or animal.get("description"),
        "statut": "en_attente"
    }
    r = requests.post(f"{SUPABASE_URL}/rest/v1/ScrapingQueue", headers=sb_headers(), json=payload)
    if r.status_code in [200, 201]:
        print(f"  OK {animal.get('nom')} -> ScrapingQueue")
    else:
        print(f"  ERREUR ScrapingQueue: {r.status_code} - {r.text[:100]}")


def envoyer_email_invitation(email, nom_refuge):
    if not RESEND_KEY or not email:
        print("  INFO Email ignore (RESEND_KEY ou email manquant)")
        return
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
        json={
            "from": "Coup de Patte <contact@coup-de-patte.fr>",
            "to": [email],
            "subject": "Vos animaux sont sur Coup de Patte !",
            "html": f"<p>Bonjour,</p><p>Votre refuge <strong>{nom_refuge}</strong> est maintenant sur Coup de Patte.</p><p>Connectez-vous sur <a href='https://coup-de-patte.fr/coup-de-patte-login.html'>coup-de-patte.fr</a> via Mot de passe oublie pour acceder a votre espace.</p><p>L'equipe Coup de Patte</p>"
        }
    )
    if r.status_code in [200, 201]:
        print(f"  OK Email envoye a {email}")
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

    # Determiner l'email : input > extraction depuis le site
    email = REFUGE_EMAIL.strip() if REFUGE_EMAIL.strip() else None
    if not email:
        print("\nAucun email fourni - extraction depuis le site...")
        email = extraire_email_site()
    if email:
        print(f"Email refuge : {email}")
    else:
        print("Aucun email trouve - compte Auth ignore")

    # Chercher si le refuge existe deja dans Supabase
    print(f"\nRecherche du refuge existant...")
    refuge_id = chercher_refuge_existant(email)

    if refuge_id:
        print(f"  Refuge existant trouve - ID : {refuge_id}")
    else:
        # Creer le compte Auth
        print(f"\nCreation du compte Auth...")
        user_id = creer_compte_auth(email) if email else None

        # Creer la fiche refuge
        print(f"\nCreation de la fiche refuge {REFUGE_NOM}...")
        refuge_id = creer_fiche_refuge(user_id, email) if user_id else None
        if not refuge_id:
            print("ERREUR: Impossible de creer le refuge - arret"); return

    # Scraping
    print(f"\nRecuperation des animaux sur {ANIMAUX_URL}...")
    urls = scraper_liste_animaux()
    if not urls:
        print("Aucun animal trouve."); return

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
        # Enrichir l'animal avec les données extraites par Claude
        if analyse.get('description_propre'):
            animal['description'] = analyse.get('description_propre')
        if analyse.get('sexe') and not animal.get('sexe'):
            animal['sexe'] = analyse.get('sexe')
        if analyse.get('race') and not animal.get('race'):
            animal['race'] = analyse.get('race')
        if analyse.get('age_annees') and not animal.get('age_annees'):
            animal['age_annees'] = analyse.get('age_annees')
        envoyer_supabase(animal, analyse, refuge_id)
        succes += 1
        time.sleep(1)

    # Email invitation - DESACTIVE EN MODE TEST
    print(f"\nEmail d'invitation desactive (mode test)")
    # envoyer_email_invitation(email, REFUGE_NOM)
    # Decommenter quand pret pour la production

    print(f"\nTermine - {succes}/{len(urls)} animaux en file d'attente")
    print(f"Refuge ID : {refuge_id}")


if __name__ == "__main__":
    main()
