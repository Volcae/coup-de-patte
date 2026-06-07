#!/usr/bin/env python3
"""
Scraper Universel - Coup de Patte
Fonctionne pour n'importe quel site de refuge.
Claude analyse le HTML brut et extrait les données animaux.

Variables d'environnement requises :
  ANTHROPIC_API_KEY
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Variables d'environnement passées par le workflow :
  REFUGE_NOM
  REFUGE_EMAIL   (optionnel, extrait du site si absent)
  REFUGE_VILLE
  REFUGE_SITE    (URL du site du refuge)

Requires: pip install requests beautifulsoup4 anthropic
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import os
import re
import anthropic
from urllib.parse import urljoin, urlparse

# ══════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════

SUPABASE_URL         = os.environ.get("SUPABASE_URL", "https://mbqsaaxaglcemdxmfvkc.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ANTHROPIC_KEY        = os.environ.get("ANTHROPIC_API_KEY", "")
RESEND_KEY           = os.environ.get("RESEND_API_KEY", "")

REFUGE_NOM   = os.environ.get("REFUGE_NOM", "")
REFUGE_EMAIL = os.environ.get("REFUGE_EMAIL", "")
REFUGE_VILLE = os.environ.get("REFUGE_VILLE", "")
REFUGE_SITE  = os.environ.get("REFUGE_SITE", "")
REFUGE_TEL   = os.environ.get("REFUGE_TEL", "")
REFUGE_ID           = os.environ.get("REFUGE_ID", "")            # UUID Supabase — prioritaire sur recherche par nom
REFUGE_URL_ADOPTION = os.environ.get("REFUGE_URL_ADOPTION", "")  # URL directe page animaux — court-circuite la découverte

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# Mots-clés pour identifier les pages d'adoption (URL ou texte des liens)
KEYWORDS_ADOPTION = [
    "adoption", "adopter", "animaux", "chien", "chat", "animal",
    "a-adopter", "nos-animaux", "les-animaux", "en-attente",
    "trouver-famille", "famille", "produit", "fiche"
]

# Mots-clés à exclure (pages non pertinentes)
KEYWORDS_EXCLUS = [
    "contact", "don", "actualit", "blog", "news", "equipe", "team",
    "partenaire", "sponsor", "presse", "mention", "cgu", "rgpd",
    "politique", "login", "connexion", "panier", "cart", "checkout",
    "wp-admin", "wp-login", "feed", "sitemap", "tag", "categorie",
    "category", "author", "page=", "?p=", "#"
]

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


# ══════════════════════════════════════════════
# UTILITAIRES HTTP
# ══════════════════════════════════════════════

def get_soup(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  ⚠ Erreur fetch {url}: {e}")
        return None


def sb_headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


# ══════════════════════════════════════════════
# ÉTAPE 1 — DÉCOUVERTE INTELLIGENTE DES FICHES
# ══════════════════════════════════════════════

def nettoyer_html(soup):
    """Supprime scripts, styles, nav, footer pour ne garder que le contenu utile."""
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]):
        tag.decompose()
    return soup


def lien_est_fiche_animal(href, texte, domaine_base):
    """Heuristique : est-ce que ce lien pointe vers une fiche individuelle d'animal ?"""
    if not href or href.startswith("mailto:") or href.startswith("tel:"):
        return False
    # Doit être sur le même domaine
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc != domaine_base:
        return False
    # Exclure les patterns non pertinents
    href_lower = href.lower()
    for exclu in KEYWORDS_EXCLUS:
        if exclu in href_lower:
            return False
    # Doit contenir un mot-clé d'adoption OU ressembler à une fiche individuelle
    # (URL avec un slug ou un ID numérique)
    has_keyword = any(kw in href_lower for kw in KEYWORDS_ADOPTION)
    has_slug = bool(re.search(r'/[a-z0-9-]{4,}/?$', href_lower))
    return has_keyword or has_slug


def collecter_fiches_depuis_page(page_adoption_url, site_url):
    """
    Collecte les fiches animaux depuis une URL de listing connue.
    Gère la pagination automatiquement.
    """
    domaine = urlparse(site_url).netloc
    fiches_urls = set()

    def scraper_page(url):
        soup = get_soup(url)
        if not soup:
            return
        for a in soup.find_all("a", href=True):
            href = urljoin(site_url, a["href"])
            if lien_est_fiche_animal(href, a.get_text(), domaine) and href != url:
                fiches_urls.add(href)
        # Pagination
        for a in soup.find_all("a", href=True):
            href_pag = urljoin(site_url, a["href"])
            if re.search(r'[/?&]page[=/]?\d+', href_pag) and domaine in href_pag and href_pag not in fiches_urls:
                soup2 = get_soup(href_pag)
                if soup2:
                    for a2 in soup2.find_all("a", href=True):
                        href2 = urljoin(site_url, a2["href"])
                        if lien_est_fiche_animal(href2, a2.get_text(), domaine) and href2 != href_pag:
                            fiches_urls.add(href2)

    scraper_page(page_adoption_url)
    print(f"  → {len(fiches_urls)} fiche(s) trouvée(s) sur {page_adoption_url}")
    return list(fiches_urls)


def decouvrir_pages_adoption(site_url):
    """
    Stratégie en 2 temps :
    1. Cherche une page 'adoption' / 'animaux' sur le site
    2. Sur cette page, collecte tous les liens vers des fiches individuelles
    """
    print(f"\n🔍 Découverte des pages d'adoption sur {site_url}")
    domaine = urlparse(site_url).netloc
    soup_accueil = get_soup(site_url)
    if not soup_accueil:
        print("  ✗ Impossible d'accéder au site")
        return []

    # Chercher les liens d'adoption sur la page d'accueil
    pages_adoption = []
    for a in soup_accueil.find_all("a", href=True):
        href = urljoin(site_url, a["href"])
        texte = a.get_text(strip=True).lower()
        if any(kw in href.lower() or kw in texte for kw in ["adoption", "adopter", "animaux", "nos-animaux", "a-adopter"]):
            if href not in pages_adoption and domaine in href:
                pages_adoption.append(href)

    if not pages_adoption:
        # Fallback : tenter des URLs communes
        tentatives = [
            f"{site_url}/adoption/",
            f"{site_url}/adopter/",
            f"{site_url}/animaux/",
            f"{site_url}/nos-animaux/",
            f"{site_url}/a-adopter/",
            f"{site_url}/adoption-animaux/",
        ]
        for url in tentatives:
            r = requests.head(url, headers=HEADERS, timeout=8, allow_redirects=True)
            if r.status_code == 200:
                pages_adoption.append(url)
                break

    print(f"  → {len(pages_adoption)} page(s) d'adoption trouvée(s) : {pages_adoption[:3]}")

    # Collecter les fiches individuelles depuis chaque page d'adoption
    fiches_urls = set()
    for page_url in pages_adoption[:3]:  # max 3 pages de listing
        soup = get_soup(page_url)
        if not soup:
            continue
        for a in soup.find_all("a", href=True):
            href = urljoin(site_url, a["href"])
            texte = a.get_text(strip=True)
            if lien_est_fiche_animal(href, texte, domaine) and href != page_url:
                fiches_urls.add(href)
        # Gérer la pagination (page 2, 3...)
        for a in soup.find_all("a", href=True):
            href_pag = urljoin(site_url, a["href"])
            if re.search(r'[/?&]page[=/]?\d+', href_pag) and domaine in href_pag:
                soup2 = get_soup(href_pag)
                if soup2:
                    for a2 in soup2.find_all("a", href=True):
                        href2 = urljoin(site_url, a2["href"])
                        if lien_est_fiche_animal(href2, a2.get_text(), domaine) and href2 != href_pag:
                            fiches_urls.add(href2)

    # Si trop peu de fiches, laisser Claude analyser la page d'adoption
    if len(fiches_urls) < 2 and pages_adoption:
        print("  → Peu de fiches trouvées, demande à Claude d'analyser la structure...")
        fiches_claude = demander_claude_urls(pages_adoption[0], site_url)
        fiches_urls.update(fiches_claude)

    print(f"  → {len(fiches_urls)} fiche(s) individuelle(s) découverte(s)")
    return list(fiches_urls)


def demander_claude_urls(page_url, site_url):
    """Claude analyse le HTML d'une page de listing pour extraire les URLs des fiches."""
    soup = get_soup(page_url)
    if not soup:
        return []
    soup = nettoyer_html(soup)
    html_reduit = str(soup)[:8000]

    prompt = f"""Voici le HTML d'une page listant des animaux à adopter sur le site {site_url}.

{html_reduit}

Extrais UNIQUEMENT les URLs des fiches individuelles des animaux (une URL par animal).
Réponds UNIQUEMENT avec un JSON valide de ce format, sans commentaire :
{{"urls": ["url1", "url2", ...]}}

Si aucune URL de fiche individuelle n'est trouvée, réponds : {{"urls": []}}"""

    try:
        msg = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        texte = msg.content[0].text.strip()
        texte = re.sub(r'^```json\s*|\s*```$', '', texte, flags=re.MULTILINE)
        data = json.loads(texte)
        urls = data.get("urls", [])
        # Résoudre les URLs relatives
        return [urljoin(site_url, u) for u in urls if u]
    except Exception as e:
        print(f"  ⚠ Claude URLs: {e}")
        return []


# ══════════════════════════════════════════════
# ÉTAPE 2 — EXTRACTION CLAUDE POUR CHAQUE FICHE
# ══════════════════════════════════════════════

PROMPT_EXTRACTION = """Tu es un extracteur de données strict pour une plateforme d'adoption animale.

Voici le texte d'une fiche d'adoption d'un refuge :

{texte}

RÈGLE ABSOLUE : tu n'extrais QUE ce qui est écrit mot pour mot dans le texte.
- Si ce n'est pas écrit, c'est null. Sans exception.
- Tu n'interprètes pas, tu ne déduis pas, tu ne complètes pas.
- Tu ne te bases pas sur la race, la photo, l'âge ou tes connaissances pour remplir un champ.
- Un champ vaut mieux null que faux.

Réponds UNIQUEMENT en JSON valide, sans commentaire ni balise markdown :
{{
  "nom": "prénom de l'animal si écrit dans le texte, sinon null",
  "espece": "chien" si chien/canin écrit, "chat" si chat/félin écrit, "lapin" si lapin écrit, "nac" sinon. null si aucun,
  "race": "copie exacte de la race telle qu'écrite dans le texte. Accepte les variantes orthographiques (border, Border Collie, border collie → Border Collie). null si aucune race mentionnée",
  "sexe": "male" si mâle/male écrit, "femelle" si femelle écrit. null sinon,
  "sterilisation": "oui" si stérilisé/castré écrit, "non" si non stérilisé écrit. null sinon,
  "identification": "oui" si pucé/tatoué/identifié écrit, "non" si non identifié écrit. null sinon,
  "vaccination": "oui" si vacciné/à jour vaccins écrit, "non" si non vacciné écrit. null sinon,
  "antiparasitaire": "oui" si traité antiparasitaire/vermifugé écrit. null sinon,
  "age_annees": calcule l'âge en années entières si une date de naissance ou un âge est écrit. null sinon,
  "poids_kg": nombre si un poids en kg est écrit. null sinon,
  "gabarit": "petit" si petit/petite taille écrit, "moyen" si taille moyenne écrit, "grand" si grande taille/grand gabarit écrit. null sinon. NE PAS déduire depuis la race,
  "pelage": "court" si poil court écrit, "mi-long" si mi-long écrit, "long" si poil long écrit. null sinon. NE PAS déduire depuis la race,
  "couleur": couleur si écrite dans le texte. null sinon,
  "energie": null SAUF si un de ces mots exacts est présent — "faible" : calme, tranquille, peu actif, casanier. "moyen" : actif, joueur, équilibré. "eleve" : très actif, sportif, énergique, dynamique, a besoin de sport. NE PAS déduire,
  "lien_humain": null SAUF si écrit — "fort" : pot de colle, très affectueux, cherche contact, collé à son maître. "faible" : craintif, distant, indépendant, méfiant. "moyen" : affectueux sans excès. NE PAS déduire,
  "reactivite_inconnus": null SAUF si écrit — "forte" : réactif, aboie sur inconnus, méfiant. "faible" : sociable, ami avec tout le monde. "moyen" : se réchauffe progressivement,
  "supporte_solitude": null SAUF si écrit — "mal" : anxieux, destructeur seul, aboie, angoisse séparation. "bien" : autonome, calme seul. "moyen" : quelques heures ok,
  "mobilite": null SAUF si écrit — "reduite" : arthrose, problème articulaire, éviter escaliers. "tres_reduite" : paralysie, handicap locomoteur grave,
  "compat_enfants_moins13": null par défaut. true SEULEMENT si "ok enfants", "aime les enfants", "compatible enfants" écrit. false SEULEMENT si "sans enfants", "pas d'enfants", "déconseillé enfants" écrit,
  "compat_ados_plus13": null par défaut. true si "ok enfants" ou "ok ados" écrit. false si "sans enfants" sans précision d'âge écrit,
  "compat_chiens": null par défaut. true SEULEMENT si "ok congénères", "ok chiens", "vit avec chiens" écrit. false SEULEMENT si "sans congénères", "sans chien", "seul chien" écrit,
  "compat_chats": null par défaut. true SEULEMENT si "ok chats", "vit avec chats" écrit. false SEULEMENT si "sans chat", "pas de chats" écrit,
  "experience_requise": null SAUF si écrit — "experimente" : expérience obligatoire, maître expérimenté. "intermediaire" : quelques bases, pas débutant. "debutant" : convient à tous,
  "besoins_medicaux": null SAUF si écrit — "lourds" : traitement long terme, opération, suivi vétérinaire régulier. "legers" : traitement ponctuel. "aucun" : en bonne santé, aucun soin particulier,
  "vie_en_refuge": null SAUF si écrit ou clairement décrit — "Tres bien" : épanoui, heureux au refuge. "Bien" : s'adapte bien. "Moyennement bien" : peut mieux faire. "Difficilement" : stressé, mal à l'aise. "Tres difficilement" : souffre vraiment,
  "type_logement_compatible": null SAUF si écrit — "maison_uniquement" : besoin jardin, ne convient pas appartement. "appart_ok" : appartement accepté, convient en appartement. "les deux" : les deux mentionnés,
  "exterieur_requis": null SAUF si écrit — true : besoin jardin/extérieur explicitement mentionné. false : appartement ok explicitement mentionné,
  "handicap": true SEULEMENT si aveugle, sourd, amputé, paralysé ou handicap physique/sensoriel écrit. false sinon,
  "permis_requis": true SEULEMENT si "chien de catégorie", "permis obligatoire", "permis de détention", "type 1", "type 2" écrit. false sinon,
  "date_arrivee_refuge": "YYYY-MM-DD" si une date d'arrivée au refuge est écrite. null sinon,
  "histoire": une phrase MAX si l'origine est écrite (abandon, saisie, trouvé, errant). null sinon,
  "description": résumé positif du texte en 2-4 phrases MAX. Uniquement ce qui est écrit. Pas d'invention.
}}"""


def extraire_texte_fiche(url):
    """Récupère et nettoie le texte d'une fiche animal."""
    soup = get_soup(url)
    if not soup:
        return None, None

    # Photo principale
    photo_url = ""
    og_image = soup.find("meta", property="og:image")
    if og_image:
        photo_url = og_image.get("content", "")
    if not photo_url:
        for img in soup.find_all("img", src=True):
            src = img.get("src", "")
            if any(kw in src.lower() for kw in ["upload", "animal", "chien", "chat", "photo", "img"]):
                photo_url = urljoin(url, src)
                break

    # Nettoyage HTML
    soup = nettoyer_html(soup)

    # Extraire le texte principal (privilégier le contenu central)
    main = soup.find("main") or soup.find("article") or soup.find(id=re.compile(r'content|main|product', re.I))
    if not main:
        main = soup.body or soup

    lignes = []
    for elem in main.find_all(["h1", "h2", "h3", "p", "li", "td", "th", "span", "div"]):
        # Ignorer les divs qui contiennent d'autres blocs (trop de bruit)
        if elem.name == "div" and elem.find(["div", "section", "article"]):
            continue
        texte = elem.get_text(separator=" ", strip=True)
        if texte and len(texte) > 2 and texte not in lignes:
            lignes.append(texte)

    texte_brut = "\n".join(lignes)
    # Limiter à 5000 caractères pour le prompt Claude
    return texte_brut[:5000], photo_url


def analyser_fiche_claude(texte, url):
    """Envoie le texte de la fiche à Claude pour extraction structurée."""
    prompt = PROMPT_EXTRACTION.format(texte=texte)
    try:
        msg = claude_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        texte_reponse = msg.content[0].text.strip()
        texte_reponse = re.sub(r'^```json\s*|\s*```$', '', texte_reponse, flags=re.MULTILINE)
        return json.loads(texte_reponse)
    except Exception as e:
        print(f"  ⚠ Erreur Claude extraction: {e}")
        return {}


# ══════════════════════════════════════════════
# ÉTAPE 3 — GESTION REFUGE (inchangé)
# ══════════════════════════════════════════════

def extraire_email_site(site_url):
    soup = get_soup(site_url)
    if not soup:
        return None
    for a in soup.find_all("a", href=True):
        if a["href"].startswith("mailto:"):
            email = a["href"].replace("mailto:", "").strip().split("?")[0]
            if email and "@" in email:
                print(f"  → Email extrait du site : {email}")
                return email
    return None


def chercher_refuge_existant(email):
    """Cherche le refuge par email, puis par site_web, puis par nom."""
    # Par email
    if email:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/Refuge?email=eq.{requests.utils.quote(email)}&select=id",
            headers=sb_headers()
        )
        if r.status_code == 200 and r.json():
            print(f"  → Refuge trouvé par email")
            return r.json()[0]["id"]

    # Par site_web
    if REFUGE_SITE:
        site = REFUGE_SITE.rstrip('/')
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/Refuge?site_web=eq.{requests.utils.quote(site)}&select=id",
            headers=sb_headers()
        )
        if r.status_code == 200 and r.json():
            print(f"  → Refuge trouvé par site_web")
            return r.json()[0]["id"]

    # Par nom exact
    if REFUGE_NOM:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/Refuge?nom=eq.{requests.utils.quote(REFUGE_NOM)}&select=id",
            headers=sb_headers()
        )
        if r.status_code == 200 and r.json():
            print(f"  → Refuge trouvé par nom")
            return r.json()[0]["id"]

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
        print(f"  ✓ Compte Auth créé — UUID : {user_id}")
        return user_id
    elif r.status_code == 422 and "already" in r.text.lower():
        r2 = requests.get(
            f"{SUPABASE_URL}/auth/v1/admin/users?email={email}",
            headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"}
        )
        if r2.status_code == 200:
            users = r2.json().get("users", [])
            if users:
                print(f"  ℹ Compte existant — UUID : {users[0]['id']}")
                return users[0]["id"]
    print(f"  ✗ Erreur Auth: {r.status_code} — {r.text[:150]}")
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
        print(f"  ✓ Fiche refuge créée — ID : {refuge_id}")
        return refuge_id
    print(f"  ✗ Erreur Refuge: {r.status_code} — {r.text[:150]}")
    return None


def verifier_animal_existant(source_url):
    """Vérifie si l'animal existe déjà (Animal ou ScrapingQueue) via son URL source."""
    if not source_url:
        return None, None
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/Animal?source_url=eq.{requests.utils.quote(source_url)}&select=id,nom",
        headers=sb_headers()
    )
    if r.status_code == 200 and r.json():
        return "animal", r.json()[0]["id"]
    r2 = requests.get(
        f"{SUPABASE_URL}/rest/v1/ScrapingQueue?source_url=eq.{requests.utils.quote(source_url)}&select=id,nom,statut",
        headers=sb_headers()
    )
    if r2.status_code == 200 and r2.json():
        return "queue", r2.json()[0]["id"]
    return None, None


# ══════════════════════════════════════════════
# ÉTAPE 4 — ENVOI EN SCRAPINGQUEUE
# ══════════════════════════════════════════════

def envoyer_supabase(analyse, photo_url, source_url, refuge_id, existing_id=None, where=None):
    """
    Publie directement dans la table Animal.
    Les champs non trouvés par Claude restent null — pas de valeur inventée.
    """
    def clean_bool(val):
        """Convertit les strings booléennes en bool Python."""
        if val is True or val == "true": return True
        if val is False or val == "false": return False
        return None

    payload = {
        "refuge":                   refuge_id,
        "nom":                      analyse.get("nom"),
        "espece":                   analyse.get("espece"),
        "race":                     analyse.get("race"),
        "age_annees":               analyse.get("age_annees"),
        "sexe":                     analyse.get("sexe"),
        "poids_kg":                 analyse.get("poids_kg"),
        "gabarit":                  analyse.get("gabarit"),
        "pelage":                   analyse.get("pelage"),
        "couleur":                  analyse.get("couleur"),
        "description":              analyse.get("description"),
        "histoire":                 analyse.get("histoire"),
        "photo_url":                photo_url or "",
        "photo":                    photo_url or "",
        "source_url":               source_url,
        "disponible":               True,
        "statut":                   "disponible",
        "date_arrivee_refuge":      analyse.get("date_arrivee_refuge"),
        "energie":                  analyse.get("energie"),
        "lien_humain":              analyse.get("lien_humain"),
        "reactivite_inconnus":      analyse.get("reactivite_inconnus"),
        "supporte_solitude":        analyse.get("supporte_solitude"),
        "mobilite":                 analyse.get("mobilite"),
        "vie_en_refuge":            analyse.get("vie_en_refuge"),
        "experience_requise":       analyse.get("experience_requise"),
        "besoins_medicaux":         analyse.get("besoins_medicaux"),
        "compat_enfants_moins13":   clean_bool(analyse.get("compat_enfants_moins13")),
        "compat_ados_plus13":       clean_bool(analyse.get("compat_ados_plus13")),
        "compat_chiens":            clean_bool(analyse.get("compat_chiens")),
        "compat_chats":             clean_bool(analyse.get("compat_chats")),
        "vaccination":              analyse.get("vaccination"),
        "sterilisation":            analyse.get("sterilisation"),
        "identification":           analyse.get("identification"),
        "antiparasitaire":          analyse.get("antiparasitaire"),
        "handicap":                 clean_bool(analyse.get("handicap")),
        "permis_requis":            clean_bool(analyse.get("permis_requis")) or False,
        "type_logement_compatible": analyse.get("type_logement_compatible"),
        "exterieur_requis":         clean_bool(analyse.get("exterieur_requis")),
    }

    # Calcul Enfin Moi automatique
    age = analyse.get("age_annees") or 0
    espece = (analyse.get("espece") or "").lower()
    enfin_moi = False
    raison = ""
    if analyse.get("date_arrivee_refuge"):
        try:
            from datetime import date
            arrivee = date.fromisoformat(analyse["date_arrivee_refuge"])
            mois = (date.today() - arrivee).days / 30
            if mois >= 12:
                enfin_moi = True
                raison = f"{int(mois)} mois au refuge"
        except: pass
    if not enfin_moi and espece == "chien" and age >= 8:
        enfin_moi = True; raison = f"chien senior ({age} ans)"
    if not enfin_moi and espece == "chat" and age >= 10:
        enfin_moi = True; raison = f"chat senior ({age} ans)"
    if not enfin_moi and analyse.get("besoins_medicaux") == "lourds":
        enfin_moi = True; raison = "besoins médicaux lourds"
    if not enfin_moi and analyse.get("vie_en_refuge") in ["Difficilement", "Tres difficilement"]:
        enfin_moi = True; raison = "vie en refuge difficile"
    if not enfin_moi and analyse.get("handicap") is True:
        enfin_moi = True; raison = "handicap mentionné"
    payload["enfin_moi"] = enfin_moi
    if raison: payload["raison_enfin_moi"] = raison

    # Supprimer les valeurs None
    payload = {k: v for k, v in payload.items() if v is not None}

    # Mise à jour si l'animal existe déjà dans Animal
    if where == "animal" and existing_id:
        r = requests.patch(
            f"{SUPABASE_URL}/rest/v1/Animal?id=eq.{existing_id}",
            headers=sb_headers(), json=payload
        )
        if r.status_code in [200, 201, 204]:
            print(f"  ✓ {analyse.get('nom', '?')} → Animal (mis à jour)")
            return True
        else:
            print(f"  ✗ Erreur update Animal: {r.status_code} — {r.text[:100]}")
            return False

    # Insertion directe dans Animal
    r = requests.post(f"{SUPABASE_URL}/rest/v1/Animal", headers=sb_headers(), json=payload)
    if r.status_code in [200, 201]:
        print(f"  ✓ {analyse.get('nom', '?')} → Animal (publié automatiquement)")
        return True
    else:
        print(f"  ✗ Erreur Animal: {r.status_code} — {r.text[:100]}")
        return False


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════

def main():
    print("🐾 Coup de Patte — Scraper Universel")
    print("=" * 45)
    print(f"  Refuge : {REFUGE_NOM}")
    print(f"  Site   : {REFUGE_SITE}")

    # Vérifications
    if not ANTHROPIC_KEY:
        print("✗ ANTHROPIC_API_KEY manquant"); return
    if not SUPABASE_SERVICE_KEY:
        print("✗ SUPABASE_SERVICE_ROLE_KEY manquant"); return
    if not REFUGE_SITE:
        print("✗ REFUGE_SITE manquant"); return

    # ── Email du refuge
    email = REFUGE_EMAIL.strip() if REFUGE_EMAIL.strip() else None
    if not email:
        print("\nExtraction email depuis le site...")
        email = extraire_email_site(REFUGE_SITE)
    print(f"  Email : {email or '(aucun)'}")

    # ── Refuge Supabase
    print(f"\nRecherche du refuge dans Supabase...")

    # Priorité 1 : ID passé directement par le superadmin
    if REFUGE_ID:
        refuge_id = REFUGE_ID
        print(f"  ✓ Refuge ID fourni directement : {refuge_id}")
    else:
        refuge_id = chercher_refuge_existant(email)
        if refuge_id:
            print(f"  ✓ Refuge trouvé — ID : {refuge_id}")
        else:
            print(f"  Création du refuge {REFUGE_NOM}...")
            user_id = creer_compte_auth(email) if email else None
            # Si pas d'email ou échec Auth, on crée quand même la fiche refuge sans compte
            refuge_id = creer_fiche_refuge(user_id, email)
            if not refuge_id:
                print("  ✗ Impossible de créer le refuge — arrêt"); return

    # ── Découverte des fiches
    if REFUGE_URL_ADOPTION:
        print(f"\n🎯 URL adoption fournie directement : {REFUGE_URL_ADOPTION}")
        fiches_urls = collecter_fiches_depuis_page(REFUGE_URL_ADOPTION, REFUGE_SITE)
    else:
        fiches_urls = decouvrir_pages_adoption(REFUGE_SITE)
    if not fiches_urls:
        print("\n✗ Aucune fiche d'animal trouvée."); return

    # ── Scraping fiche par fiche
    print(f"\n📋 Traitement de {len(fiches_urls)} fiche(s)...")
    succes = 0
    ignores = 0

    for i, url in enumerate(fiches_urls, 1):
        print(f"\n[{i}/{len(fiches_urls)}] {url}")

        # Anti-doublon
        where, existing_id = verifier_animal_existant(url)
        if where == "queue":
            print(f"  ⏭ Déjà en file d'attente — ignoré")
            ignores += 1
            continue

        # Extraction texte + photo
        texte, photo_url = extraire_texte_fiche(url)
        if not texte or len(texte) < 50:
            print("  ⏭ Fiche vide ou inaccessible — ignorée")
            ignores += 1
            continue

        # Analyse Claude
        print("  🤖 Analyse Claude...")
        analyse = analyser_fiche_claude(texte, url)
        if not analyse.get("nom") and not analyse.get("espece"):
            print("  ⏭ Claude n'a pas trouvé d'animal dans cette page — ignorée")
            ignores += 1
            continue

        nom = analyse.get("nom", "?")
        espece = analyse.get("espece", "?")
        race = analyse.get("race", "-")
        age = analyse.get("age_annees", "-")
        print(f"  → {nom} | {espece} | {race} | {age} ans")

        # Envoi Supabase
        ok = envoyer_supabase(analyse, photo_url, url, refuge_id, existing_id, where)
        if ok:
            succes += 1

        time.sleep(1.5)  # Pause pour ne pas surcharger le site du refuge

    # ── Résumé
    print(f"\n{'=' * 45}")
    print(f"✅ Terminé — {succes} animal(aux) en file d'attente")
    print(f"   {ignores} ignoré(s) (doublons ou pages vides)")
    print(f"   Refuge ID : {refuge_id}")


if __name__ == "__main__":
    main()
