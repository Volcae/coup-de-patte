#!/usr/bin/env python3
"""
Normalisateur de races — Coup de Patte
Normalise les races en texte libre vers les valeurs standardisées.
Usage : python normaliser_races.py
"""

import requests
import json
import time
import os
import anthropic

SUPABASE_URL         = os.environ.get("SUPABASE_URL", "https://mbqsaaxaglcemdxmfvkc.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
ANTHROPIC_KEY        = os.environ.get("ANTHROPIC_API_KEY", "")

RACES_CHIEN = ["Affenpinscher", "Airedale Terrier", "Akita Américain", "Akita Inu", "Alaskan Malamute", "American Staffordshire Terrier", "Apparence Loup (Saarloos / Tchécoslovaque)", "Azawakh", "Barbet", "Basenji", "Basset Artésien Normand", "Basset Fauve de Bretagne", "Basset Hound", "Beagle", "Beagle Harrier", "Berger Allemand", "Berger Australien", "Berger Belge Groenendael", "Berger Belge Laekenois", "Berger Belge Malinois", "Berger Belge Tervueren", "Berger Blanc Suisse", "Berger de Brie (Briard)", "Berger de Picardie", "Berger des Pyrénées", "Berger des Shetland", "Bichon Frisé", "Bichon Havanais", "Bloodhound (Chien de Saint-Hubert)", "Bobtail (Old English Sheepdog)", "Bolonais", "Border Collie", "Border Terrier", "Bouledogue Français", "Bouvier Australien", "Bouvier Bernois", "Bouvier des Flandres", "Boxer", "Braque Allemand", "Braque de Weimar (Weimaraner)", "Braque du Bourbonnais", "Braque Français", "Braque Hongrois (Vizsla)", "Bull Terrier", "Bulldog Anglais", "Bullmastiff", "Cairn Terrier", "Caniche (Toy)", "Caniche (Nain)", "Caniche (Moyen)", "Caniche (Grand)", "Cane Corso", "Cavalier King Charles", "Chien Courant Suisse", "Chien d\\", "Chien d\\", "Chien de Berger Corse", "Chien de Berger Yougoslave", "Chien de Montagne des Pyrénées (Patou)", "Chien de Rhodésie (Ridgeback)", "Chihuahua (poil court)", "Chihuahua (poil long)", "Chow-Chow", "Clumber Spaniel", "Cocker Américain", "Cocker Anglais", "Colley Rough (à poil long)", "Colley Smooth (à poil court)", "Dalmatien", "Dobermann", "Dogue Allemand (Great Dane)", "Dogue Argentin", "Dogue de Bordeaux", "Épagneul Bleu de Picardie", "Épagneul Breton", "Épagneul Japonais", "Épagneul Papillon", "Eurasier", "Field Spaniel", "Flat Coated Retriever", "Fox Terrier (poil dur)", "Fox Terrier (poil lisse)", "Golden Retriever", "Grand Basset Griffon Vendéen", "Grand Bleu de Gascogne", "Grand Danois", "Greyhound", "Griffon Belge", "Griffon Bruxellois", "Griffon Fauve de Bretagne", "Griffon Korthals", "Husky Sibérien", "Irish Setter", "Irish Terrier", "Irish Water Spaniel", "Jack Russell Terrier", "Jack Russell (poil dur)", "Jagdterrier", "Kai Ken", "Keeshond (Loulou de Poméranie Grand)", "Kerry Blue Terrier", "King Charles Spaniel", "Labrador Retriever", "Lagotto Romagnolo", "Lakeland Terrier", "Leonberg", "Lévrier Afghan", "Lévrier Écossais (Deerhound)", "Lévrier Irlandais (Irish Wolfhound)", "Lévrier Italien", "Lévrier Persan (Saluki)", "Lhassa Apso", "Löwchen (Petit Chien Lion)", "Malinois", "Maltais", "Manchester Terrier", "Mastiff", "Mâtin de Naples", "Mâtin Espagnol", "Mudi", "Norwich Terrier", "Pékinois", "Petit Basset Griffon Vendéen", "Petit Chien Courant Suisse", "Pinscher Moyen", "Pinscher Nain", "Pointer", "Pomeranian (Spitz Nain)", "Porcelaine", "Puli", "Pumi", "Retriever de la Baie de Chesapeake", "Rottweiler", "Saint-Bernard", "Samoyède", "Schipperke", "Schnauzer Géant", "Schnauzer Moyen", "Schnauzer Nain", "Scottish Terrier", "Sealyham Terrier", "Setter Anglais", "Setter Gordon", "Setter Irlandais Rouge et Blanc", "Shiba Inu", "Shih Tzu", "Siberian Husky", "Skye Terrier", "Sloughi", "Soft Coated Wheaten Terrier", "Spitz Finlandais", "Spitz Japonais", "Springer Anglais", "Staffordshire Bull Terrier", "Sussex Spaniel", "Teckel (poil court)", "Teckel (poil dur)", "Teckel (poil long)", "Terre-Neuve", "Terrier Noir Russe", "Tervueren", "Tibetan Mastiff (Dogue du Tibet)", "Tibetan Spaniel", "Tibetan Terrier", "Tosa", "Welsh Corgi Cardigan", "Welsh Corgi Pembroke", "Welsh Springer Spaniel", "Welsh Terrier", "West Highland White Terrier", "Whippet", "Yorkshire Terrier"]
RACES_CHAT  = ["Abyssin", "Balinais", "Bengal", "Birman", "Bleu Russe", "Bombay", "British Longhair", "British Shorthair", "Burmese", "Burmilla", "Californian Spangled", "Chantilly Tiffany", "Chartreux", "Chausie", "Cornish Rex", "Cymric", "Devon Rex", "Donskoy (Chat Nu Russe)", "Européen (chat européen)", "Exotic Shorthair", "Havana", "Highland Fold", "Khao Manee", "Korat", "Laperm", "Maine Coon", "Manx", "Mau Égyptien", "Munchkin", "Nebelung", "Norvégien", "Ocicat", "Oriental Longhair", "Oriental Shorthair", "Persan", "Peterbald", "Pixie-Bob", "Ragamuffin", "Ragdoll", "Sacré de Birmanie", "Savannah", "Scottish Fold", "Selkirk Rex", "Serengeti", "Siamois", "Sibérien", "Singapura", "Snowshoe", "Somali", "Sphynx", "Thai", "Tiffanie", "Tonkinois", "Turc de Van", "Turkish Angora", "York Chocolat"]
# Races génériques acceptées quand la race exacte n'est pas précisée
RACES_GENERIQUES = [
    "Spitz", "Berger", "Terrier", "Épagneul", "Griffon", "Pinscher",
    "Retriever", "Setter", "Pointer", "Braque", "Lévrier",
    "Dogue", "Bouledogue", "Mastiff",
    "Européen",  # Chat générique
]

# Aliases — noms alternatifs courants en refuge → nom officiel dans la liste
ALIASES = {
    "Malinois":               "Berger Belge Malinois",
    "Tervueren":              "Berger Belge Tervueren",
    "Groenendael":            "Berger Belge Groenendael",
    "Husky de Sibérie":       "Siberian Husky",
    "Husky":                  "Siberian Husky",
    "Pinsher":                "Pinscher",
    "Eurasier":               "Eurasier",   # à ajouter dans la liste officielle
    "Dogue de Bordeaux":      "Dogue de Bordeaux",
    "Croisé Dogue":           "Croisé",     # trop vague → Croisé générique
    "Border croisé Dalmatien": "Croisé Border Collie / Dalmatien",
    "Labrador croisé Braque": "Croisé Labrador / Braque",
    "Croisé Berger":          "Croisé Berger",   # race générique acceptée
    "Croisé Berger Australien": "Croisé Berger Australien",
    "Croisé Border Collie":   "Croisé Border Collie",
    "Croisé Setter":          "Croisé Setter",
    "Croisé Labrador":        "Croisé Labrador",
    "Croisé Springer Spaniel": "Croisé Springer Spaniel",
    "Croisé Beauceron":       "Croisé Beauceron",
}
TOUTES_RACES = RACES_CHIEN + RACES_CHAT + RACES_GENERIQUES + ["Croisé", "Inconnu"]
TOUTES_RACES_ETENDUES = TOUTES_RACES + list(ALIASES.keys())

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


def charger_animaux_a_normaliser():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/Animal?select=id,nom,espece,race&race=not.is.null&disponible=eq.true",
        headers=sb_headers()
    )
    if r.status_code != 200:
        print(f"✗ Erreur chargement: {r.status_code}")
        return []
    animaux = r.json()
    a_normaliser = [a for a in animaux if a.get("race") and a["race"] not in TOUTES_RACES_ETENDUES]
    print(f"→ {len(animaux)} animaux au total, {len(a_normaliser)} à normaliser")
    return a_normaliser


def normaliser_race(nom, espece, race_brute):
    # Vérifier d'abord les aliases directs — pas besoin de Claude
    if race_brute in ALIASES:
        return ALIASES[race_brute]
    # Si déjà dans la liste étendue, pas besoin de normaliser
    if race_brute in TOUTES_RACES_ETENDUES:
        return race_brute

    if espece == "chat":
        liste = "\n".join(f"- {r}" for r in RACES_CHAT + RACES_GENERIQUES + ["Croisé", "Inconnu"])
    else:
        liste = "\n".join(f"- {r}" for r in RACES_CHIEN + RACES_GENERIQUES + ["Croisé", "Inconnu"])

    prompt = f"""Tu normalises des races d'animaux pour une plateforme d'adoption.

Race brute : "{race_brute}"
Animal : {nom} ({espece})

Liste des races officielles :
{liste}

Règles :
- Choisis la race officielle la plus proche dans la liste
- Si "Spitz" sans précision → réponds "Spitz" (race générique acceptée)
- Si "Berger" sans précision → réponds "Berger"
- Si "Européen" pour un chat → réponds "Européen"
- Si croisé identifiable avec 2 races : "Croisé Race1 / Race2" en utilisant les noms de la liste
- Si croisé avec 1 seule race identifiable : "Croisé Race1"
- Si vraiment impossible à identifier : "Inconnu"
- Réponds UNIQUEMENT avec la race normalisée, rien d'autre"""

    try:
        msg = get_claude().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip().strip('"').strip("'")
    except Exception as e:
        print(f"  ⚠ Claude: {e}")
        return None


def mettre_a_jour_race(animal_id, race_normalisee):
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/Animal?id=eq.{animal_id}",
        headers=sb_headers(),
        json={"race": race_normalisee}
    )
    return r.status_code in [200, 201, 204]


def main():
    print("🐾 Normalisateur de races — Coup de Patte")
    print("=" * 45)

    if not ANTHROPIC_KEY:
        print("✗ ANTHROPIC_API_KEY manquant"); return
    if not SUPABASE_SERVICE_KEY:
        print("✗ SUPABASE_SERVICE_ROLE_KEY manquant"); return

    animaux = charger_animaux_a_normaliser()
    if not animaux:
        print("✓ Toutes les races sont déjà normalisées")
        return

    succes = 0
    erreurs = 0

    for a in animaux:
        race_brute = a["race"]
        nom        = a.get("nom") or "?"
        espece     = a.get("espece") or "chien"

        print(f"\n  {nom} ({espece}) | brute: \"{race_brute}\"")

        race_norm = normaliser_race(nom, espece, race_brute)
        if not race_norm:
            erreurs += 1
            continue

        if race_norm == race_brute:
            print(f"  → Déjà correcte")
            succes += 1
            continue

        print(f"  → Normalisée: \"{race_norm}\"")

        if mettre_a_jour_race(a["id"], race_norm):
            print(f"  ✓ OK")
            succes += 1
        else:
            print(f"  ✗ Erreur mise à jour")
            erreurs += 1

        time.sleep(0.5)

    print(f"\n{'=' * 45}")
    print(f"✅ {succes} race(s) normalisée(s), {erreurs} erreur(s)")


if __name__ == "__main__":
    main()
