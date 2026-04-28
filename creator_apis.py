"""
creator_apis.py — Stockage des clés API par créateur (SQLite)
"""

import os
from cryptography.fernet import Fernet, InvalidToken
from database import db, get_conn


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


# Champs autorisés (whitelist stricte)
ALLOWED_KEYS = {
    "meta_access_token",
    "meta_token_expires_at",   # ISO date — date d'expiration du token Meta (60 jours)
    "instagram_business_id",
    "facebook_page_id",
    "youtube_api_key",
    "youtube_channel_id",
    "google_token",
    "tiktok_token",
}


def get_creator_apis(creator_name: str) -> dict:
    """Retourne les vraies clés déchiffrées (usage interne serveur uniquement)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT key_name, value FROM creator_apis WHERE creator_name = ?",
        (creator_name,)
    ).fetchall()
    return {r["key_name"]: _decrypt(r["value"]) for r in rows}


def save_creator_apis(creator_name: str, apis: dict):
    """Sauvegarde les clés d'un créateur (whitelist appliquée)."""
    with db() as conn:
        for k, v in apis.items():
            if k in ALLOWED_KEYS and v:
                conn.execute("""
                    INSERT INTO creator_apis (creator_name, key_name, value)
                    VALUES (?,?,?)
                    ON CONFLICT(creator_name, key_name) DO UPDATE SET value = excluded.value
                """, (creator_name, k, _encrypt(v.strip())))


def get_masked_apis(creator_name: str) -> dict:
    """Retourne les clés masquées pour affichage côté client."""
    apis   = get_creator_apis(creator_name)
    result = {}
    TOKEN_KEYS = {"google_token", "tiktok_token"}
    # Clés affichées en clair (pas des secrets)
    PLAIN_KEYS = {"meta_token_expires_at"}
    for key in ALLOWED_KEYS:
        val = apis.get(key, "")
        if not val:
            result[key] = ""
        elif key in TOKEN_KEYS:
            result[key] = "connecté"
        elif key in PLAIN_KEYS:
            result[key] = val   # date ISO — pas un secret
        elif len(val) >= 8:
            result[key] = val[:4] + "••••" + val[-4:]
        else:
            result[key] = "••••"
    return result


def delete_creator_api(creator_name: str, key: str):
    with db() as conn:
        conn.execute(
            "DELETE FROM creator_apis WHERE creator_name = ? AND key_name = ?",
            (creator_name, key)
        )


def export_all() -> dict:
    """Export complet pour l'admin."""
    conn = get_conn()
    rows = conn.execute("SELECT creator_name, key_name, value FROM creator_apis").fetchall()
    result: dict = {}
    for r in rows:
        result.setdefault(r["creator_name"], {})[r["key_name"]] = r["value"]
    return result
