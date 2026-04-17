"""
creator_apis.py — Stockage des clés API par créateur
Fichier : creator_apis.json (jamais exposé en clair côté client)
"""

import json
from pathlib import Path

APIS_FILE = "creator_apis.json"

# Champs autorisés (whitelist stricte)
ALLOWED_KEYS = {
    "meta_access_token",
    "instagram_business_id",
    "facebook_page_id",
}


def _load() -> dict:
    if not Path(APIS_FILE).exists():
        return {}
    with open(APIS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    with open(APIS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_creator_apis(creator_name: str) -> dict:
    """Retourne les vraies clés (usage interne serveur uniquement)."""
    return _load().get(creator_name, {})


def save_creator_apis(creator_name: str, apis: dict):
    """Sauvegarde les clés d'un créateur (whitelist appliquée)."""
    filtered = {k: v.strip() for k, v in apis.items() if k in ALLOWED_KEYS and v}
    all_apis = _load()
    # Merge : ne pas écraser les clés existantes si non envoyées
    all_apis.setdefault(creator_name, {}).update(filtered)
    _save(all_apis)


def get_masked_apis(creator_name: str) -> dict:
    """Retourne les clés masquées pour affichage côté client."""
    apis = get_creator_apis(creator_name)
    result = {}
    for key in ALLOWED_KEYS:
        val = apis.get(key, "")
        if val and len(val) >= 8:
            result[key] = val[:4] + "••••" + val[-4:]
        elif val:
            result[key] = "••••"
        else:
            result[key] = ""
    return result


def delete_creator_api(creator_name: str, key: str):
    """Supprime une clé spécifique."""
    all_apis = _load()
    all_apis.get(creator_name, {}).pop(key, None)
    _save(all_apis)
