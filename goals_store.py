"""
goals_store.py — Objectifs par créateur (SQLite)
"""

from database import db, get_conn


def get_goals(creator: str) -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT views_per_week, posts_per_week, engagement_pct FROM goals WHERE creator = ?",
        (creator,)
    ).fetchone()
    if row:
        return {
            "views_per_week":  row["views_per_week"],
            "posts_per_week":  row["posts_per_week"],
            "engagement_pct":  row["engagement_pct"],
        }
    return {"views_per_week": 0, "posts_per_week": 0, "engagement_pct": 0}


def set_goals(creator: str, goals: dict):
    with db() as conn:
        conn.execute("""
            INSERT INTO goals (creator, views_per_week, posts_per_week, engagement_pct, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(creator) DO UPDATE SET
                views_per_week = excluded.views_per_week,
                posts_per_week = excluded.posts_per_week,
                engagement_pct = excluded.engagement_pct,
                updated_at     = excluded.updated_at
        """, (
            creator,
            int(goals.get("views_per_week", 0)),
            int(goals.get("posts_per_week", 0)),
            float(goals.get("engagement_pct", 0)),
        ))
