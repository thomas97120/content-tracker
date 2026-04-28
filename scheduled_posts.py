"""
scheduled_posts.py — Posts programmés par créateur (SQLite)
"""

import datetime
import uuid
from database import db, get_conn


def _row_to_dict(r) -> dict:
    d = dict(r)
    d["notified"] = bool(d.get("notified", 0))
    return d


def get_scheduled_posts(creator: str) -> list:
    """Retourne les posts programmés d'un créateur, triés par date."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scheduled_posts WHERE creator = ? ORDER BY scheduled_at ASC",
        (creator,)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def add_scheduled_post(creator: str, data: dict) -> dict:
    """Crée un nouveau post programmé. Retourne le post créé."""
    post_id    = str(uuid.uuid4())
    created_at = datetime.datetime.utcnow().isoformat()
    with db() as conn:
        conn.execute("""
            INSERT INTO scheduled_posts
            (id, creator, platform, title, caption, format, scheduled_at,
             status, notified, created_at, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            post_id,
            creator,
            data.get("platform", ""),
            (data.get("title") or "")[:100],
            (data.get("caption") or "")[:2200],
            data.get("format", ""),
            data.get("scheduled_at", ""),
            "scheduled",
            0,
            created_at,
            (data.get("notes") or "")[:500],
        ))
    return {
        "id":           post_id,
        "creator":      creator,
        "platform":     data.get("platform", ""),
        "title":        (data.get("title") or "")[:100],
        "caption":      (data.get("caption") or "")[:2200],
        "format":       data.get("format", ""),
        "scheduled_at": data.get("scheduled_at", ""),
        "status":       "scheduled",
        "notified":     False,
        "created_at":   created_at,
        "notes":        (data.get("notes") or "")[:500],
    }


def update_scheduled_post(creator: str, post_id: str, updates: dict) -> dict | None:
    """Met à jour un post. Retourne le post mis à jour ou None si introuvable."""
    allowed = {"platform", "title", "caption", "format", "scheduled_at",
               "status", "notified", "notes", "media_path", "media_name",
               "publish_id", "published_at"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return _get_post(creator, post_id)

    set_clause = ", ".join(f"{k} = ?" for k in filtered)
    values     = list(filtered.values()) + [creator, post_id]
    with db() as conn:
        conn.execute(
            f"UPDATE scheduled_posts SET {set_clause} WHERE creator = ? AND id = ?",
            values
        )
    return _get_post(creator, post_id)


def _get_post(creator: str, post_id: str) -> dict | None:
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM scheduled_posts WHERE creator = ? AND id = ?",
        (creator, post_id)
    ).fetchone()
    return _row_to_dict(row) if row else None


def delete_scheduled_post(creator: str, post_id: str) -> bool:
    """Supprime un post. Retourne True si trouvé et supprimé."""
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM scheduled_posts WHERE creator = ? AND id = ?",
            (creator, post_id)
        )
    return cur.rowcount > 0


def get_due_posts(window_minutes: int = 15) -> list:
    """
    Retourne les posts dont l'heure est dans les prochaines window_minutes minutes
    et qui n'ont pas encore été notifiés.
    """
    now  = datetime.datetime.utcnow()
    soon = now + datetime.timedelta(minutes=window_minutes)
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM scheduled_posts
        WHERE status = 'scheduled'
          AND notified = 0
          AND scheduled_at BETWEEN ? AND ?
    """, (now.isoformat(), soon.isoformat())).fetchall()
    return [_row_to_dict(r) for r in rows]


def mark_notified(creator: str, post_id: str):
    update_scheduled_post(creator, post_id, {"notified": 1})


def invalidate_cache():
    pass  # no-op — SQLite has no in-memory cache
