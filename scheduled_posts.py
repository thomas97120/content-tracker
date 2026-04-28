"""
scheduled_posts.py — Stockage des posts programmés par créateur
Fichier : scheduled_posts.json  |  Env var : SCHEDULED_POSTS_JSON
"""

import json
import os
import uuid
import datetime
from pathlib import Path

POSTS_FILE = "scheduled_posts.json"

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache

    if Path(POSTS_FILE).exists():
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)
        return _cache

    env_data = os.environ.get("SCHEDULED_POSTS_JSON")
    if env_data:
        _cache = json.loads(env_data)
        _flush()
        return _cache

    _cache = {}
    return _cache


def _flush():
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, indent=2, ensure_ascii=False)


def get_scheduled_posts(creator: str) -> list:
    """Retourne les posts programmés d'un créateur, triés par date."""
    posts = _load().get(creator, [])
    return sorted(posts, key=lambda p: p.get("scheduled_at", ""))


def add_scheduled_post(creator: str, data: dict) -> dict:
    """Crée un nouveau post programmé. Retourne le post créé."""
    global _cache
    store = _load()
    post = {
        "id":           str(uuid.uuid4()),
        "creator":      creator,
        "platform":     data.get("platform", ""),
        "title":        (data.get("title") or "")[:100],
        "caption":      (data.get("caption") or "")[:2200],
        "format":       data.get("format", ""),
        "scheduled_at": data.get("scheduled_at", ""),  # ISO datetime
        "status":       "scheduled",   # scheduled | published | cancelled
        "notified":     False,
        "created_at":   datetime.datetime.utcnow().isoformat(),
        "notes":        (data.get("notes") or "")[:500],
    }
    store.setdefault(creator, []).append(post)
    _cache = store
    _flush()
    return post


def update_scheduled_post(creator: str, post_id: str, updates: dict) -> dict | None:
    """Met à jour un post. Retourne le post mis à jour ou None si introuvable."""
    global _cache
    store = _load()
    posts = store.get(creator, [])
    for p in posts:
        if p["id"] == post_id:
            allowed = {"platform", "title", "caption", "format", "scheduled_at",
                       "status", "notified", "notes", "media_path", "media_name",
                       "publish_id", "published_at"}
            for k, v in updates.items():
                if k in allowed:
                    p[k] = v
            _cache = store
            _flush()
            return p
    return None


def delete_scheduled_post(creator: str, post_id: str) -> bool:
    """Supprime un post. Retourne True si trouvé et supprimé."""
    global _cache
    store = _load()
    posts = store.get(creator, [])
    new_posts = [p for p in posts if p["id"] != post_id]
    if len(new_posts) == len(posts):
        return False
    store[creator] = new_posts
    _cache = store
    _flush()
    return True


def get_due_posts(window_minutes: int = 15) -> list:
    """
    Retourne les posts dont l'heure est dans les prochaines `window_minutes` minutes
    et qui n'ont pas encore été notifiés (status=scheduled, notified=False).
    """
    now = datetime.datetime.utcnow()
    soon = now + datetime.timedelta(minutes=window_minutes)
    due = []
    store = _load()
    for creator, posts in store.items():
        for p in posts:
            if p.get("status") != "scheduled":
                continue
            if p.get("notified"):
                continue
            try:
                sched = datetime.datetime.fromisoformat(p["scheduled_at"])
                if now <= sched <= soon:
                    due.append(p)
            except Exception:
                continue
    return due


def mark_notified(creator: str, post_id: str):
    update_scheduled_post(creator, post_id, {"notified": True})


def invalidate_cache():
    global _cache
    _cache = None
