"""
ideas_store.py — Stockage des idées de contenu par créateur (SQLite)
"""

import datetime
from database import db, get_conn


def get_ideas(creator: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, titre, description, plateforme, format, status, created_at, decision_at "
        "FROM ideas WHERE creator = ? ORDER BY created_at DESC",
        (creator,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_idea(creator: str, idea: dict):
    with db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO ideas
            (id, creator, titre, description, plateforme, format, status, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            idea.get("id"),
            creator,
            idea.get("titre"),
            idea.get("description"),
            idea.get("plateforme"),
            idea.get("format"),
            idea.get("status", "pending"),
            idea.get("created_at", datetime.datetime.utcnow().isoformat()),
        ))


def update_idea_decision(creator: str, idea_id: str, decision: str):
    """Met à jour le statut (decided) d'une idée."""
    with db() as conn:
        conn.execute("""
            UPDATE ideas SET status = ?, decision_at = datetime('now')
            WHERE creator = ? AND id = ?
        """, (decision, creator, idea_id))


def export_all() -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT creator, id, titre, description, plateforme, format, status, created_at, decision_at "
        "FROM ideas"
    ).fetchall()
    result: dict = {}
    for r in rows:
        result.setdefault(r["creator"], []).append(dict(r))
    return result
