"""
creator_apis.py — Stockage des clés API par créateur
Fichier : creator_apis.json  |  Env var Render : CREATOR_APIS_JSON
"""

import json
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet():
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        return None


def _encrypt(value: str) -> str:
    f = _get_fernet()
    if not f or not value:
        return value
    return "enc:" + f.encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    f = _get_fernet()
    if not f or not value:
        return value
    if not value.startswith("enc:"):
        return value  # plain text (rétrocompatible)
    try:
        return f.decrypt(value[4:].encode()).decode()
    except (InvalidToken, Exception):
        return value

APIS_FILE = "creator_apis.json"

# Champs autorisés (whitelist stricte)
ALLOWED_KEYS = {
    "meta_access_token",
    "instagram_business_id",
    "facebook_page_id",
    "youtube_api_key",
    "youtube_channel_id",
}

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache

    # 1. Fichier local
    if Path(APIS_FILE).exists():
        with open(APIS_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)
        return _cache

    # 2. Env var Render (CREATOR_APIS_JSON) → bootstrap
    env_data = os.environ.get("CREATOR_APIS_JSON")
    if env_data:
        _cache = json.loads(env_data)
        _flush()
        return _cache

    _cache = {}
    return _cache


def _flush():
    with open(APIS_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, indent=2, ensure_ascii=False)


def get_creator_apis(creator_name: str) -> dict:
    """Retourne les vraies clés déchiffrées (usage interne serveur uniquement)."""
    raw = _load().get(creator_name, {})
    return {k: _decrypt(v) for k, v in raw.items()}


def save_creator_apis(creator_name: str, apis: dict):
    """Sauvegarde les clés d'un créateur (whitelist appliquée)."""
    global _cache
    data     = _load()
    filtered = {k: _encrypt(v.strip()) for k, v in apis.items() if k in ALLOWED_KEYS and v}
    data.setdefault(creator_name, {}).update(filtered)
    _cache = data
    _flush()


def get_masked_apis(creator_name: str) -> dict:
    """Retourne les clés masquées pour affichage côté client."""
    apis   = get_creator_apis(creator_name)
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
    global _cache
    data = _load()
    data.get(creator_name, {}).pop(key, None)
    _cache = data
    _flush()


def export_all() -> dict:
    """Export complet pour l'admin (pour mettre à jour l'env var Render)."""
    return _load()
