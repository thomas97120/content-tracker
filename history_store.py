"""
history_store.py — Stockage historique des stats (SQLite local).

Persistence sur Render (disque éphémère) :
  - Au démarrage : restaure depuis env var HISTORY_JSON (si présente)
  - Via /api/admin/export-history : génère le JSON à coller dans Render
"""

import sqlite3
import json
import os
import datetime

DB_PATH = os.environ.get("HISTORY_DB_PATH", "history.db")


# ── Connexion ──────────────────────────────────────────────────
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


# ── Init schéma ────────────────────────────────────────────────
def init_db():
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            creator    TEXT    NOT NULL,
            platform   TEXT    NOT NULL,
            post_date  TEXT    NOT NULL,
            post_hour  INTEGER,
            title      TEXT    DEFAULT '',
            format     TEXT    DEFAULT '',
            views      INTEGER DEFAULT 0,
            likes      INTEGER DEFAULT 0,
            comments   INTEGER DEFAULT 0,
            shares     INTEGER DEFAULT 0,
            saves      INTEGER DEFAULT 0,
            followers  INTEGER DEFAULT 0,
            eng_pct    REAL    DEFAULT 0,
            fetched_at TEXT,
            UNIQUE(creator, platform, post_date, title)
        )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_creator_date "
            "ON posts(creator, post_date)"
        )


# ── Upsert ─────────────────────────────────────────────────────
def upsert_posts(creator: str, rows: list) -> int:
    """Insère ou met à jour les posts. Retourne le nombre de lignes écrites."""
    init_db()
    now = datetime.datetime.now().isoformat()
    count = 0
    with _conn() as c:
        for r in rows:
            views    = int(r.get("vues", 0) or 0)
            likes    = int(r.get("likes", 0) or 0)
            comments = int(r.get("commentaires", 0) or 0)
            shares   = int(r.get("partages", 0) or 0)
            saves    = int(r.get("sauvegardes", 0) or 0)
            eng      = (likes + comments + shares) / views * 100 if views > 0 else 0.0
            title    = (r.get("titre") or "")[:120]

            c.execute("""
            INSERT INTO posts
              (creator, platform, post_date, post_hour, title, format,
               views, likes, comments, shares, saves, followers, eng_pct, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(creator, platform, post_date, title) DO UPDATE SET
              views      = excluded.views,
              likes      = excluded.likes,
              comments   = excluded.comments,
              shares     = excluded.shares,
              saves      = excluded.saves,
              followers  = excluded.followers,
              eng_pct    = excluded.eng_pct,
              fetched_at = excluded.fetched_at
            """, (
                creator,
                r.get("plateforme", ""),
                r.get("date", ""),
                r.get("hour"),
                title,
                r.get("format", ""),
                views, likes, comments, shares, saves,
                int(r.get("abonnes", 0) or 0),
                round(eng, 2),
                now,
            ))
            count += 1
    return count


# ── Lecture ────────────────────────────────────────────────────
def get_history(creator: str, days: int = 365) -> list:
    """Tous les posts stockés d'un créateur sur `days` jours."""
    init_db()
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute("""
        SELECT platform, post_date, post_hour, title, format,
               views, likes, comments, shares, saves, followers, eng_pct
        FROM posts
        WHERE creator = ? AND post_date >= ?
        ORDER BY post_date DESC
        """, (creator, cutoff)).fetchall()
    return [dict(r) for r in rows]


def get_history_summary(creator: str) -> dict:
    """Résumé global : total posts, période couverte, stats par plateforme."""
    init_db()
    with _conn() as c:
        total  = c.execute(
            "SELECT COUNT(*) FROM posts WHERE creator=?", (creator,)
        ).fetchone()[0]
        oldest = c.execute(
            "SELECT MIN(post_date) FROM posts WHERE creator=?", (creator,)
        ).fetchone()[0]
        newest = c.execute(
            "SELECT MAX(post_date) FROM posts WHERE creator=?", (creator,)
        ).fetchone()[0]
        plat   = c.execute("""
        SELECT platform,
               COUNT(*)       AS n,
               SUM(views)     AS total_views,
               AVG(eng_pct)   AS avg_eng,
               MAX(views)     AS max_views
        FROM posts WHERE creator=? GROUP BY platform
        """, (creator,)).fetchall()

    by_platform = {}
    for r in plat:
        by_platform[r["platform"]] = {
            "posts":        r["n"],
            "total_views":  r["total_views"] or 0,
            "avg_eng":      round(r["avg_eng"] or 0, 2),
            "max_views":    r["max_views"] or 0,
        }

    return {
        "total_posts":  total,
        "oldest":       oldest,
        "newest":       newest,
        "by_platform":  by_platform,
    }


def get_monthly_breakdown(creator: str) -> list:
    """Vues + posts par mois (pour graphique long terme)."""
    init_db()
    with _conn() as c:
        rows = c.execute("""
        SELECT substr(post_date,1,7) AS month,
               platform,
               COUNT(*)              AS posts,
               SUM(views)            AS total_views,
               AVG(eng_pct)          AS avg_eng
        FROM posts
        WHERE creator = ?
        GROUP BY month, platform
        ORDER BY month ASC
        """, (creator,)).fetchall()
    return [dict(r) for r in rows]


# ── Export / Import (persistence Render) ──────────────────────
def export_all_json(creator: str) -> str:
    """Sérialise tout l'historique en JSON (à stocker dans env var Render)."""
    rows = get_history(creator, days=400)
    return json.dumps(rows, ensure_ascii=False)


def import_from_json(creator: str, json_str: str):
    """Restaure depuis JSON (env var HISTORY_JSON au démarrage)."""
    rows = json.loads(json_str)
    # Convertit depuis le format history → format collectors
    adapted = [{
        "plateforme":   r.get("platform", ""),
        "date":         r.get("post_date", ""),
        "hour":         r.get("post_hour"),
        "titre":        r.get("title", ""),
        "format":       r.get("format", ""),
        "vues":         r.get("views", 0),
        "likes":        r.get("likes", 0),
        "commentaires": r.get("comments", 0),
        "partages":     r.get("shares", 0),
        "sauvegardes":  r.get("saves", 0),
        "abonnes":      r.get("followers", 0),
    } for r in rows]
    return upsert_posts(creator, adapted)


# ── Bootstrap depuis env var au démarrage ─────────────────────
def bootstrap_from_env():
    """
    Appelé une fois au démarrage de l'app.
    Si HISTORY_JSON est défini, restaure toutes les données.
    Format: { "creator1": [...], "creator2": [...] }
    """
    raw = os.environ.get("HISTORY_JSON")
    if not raw:
        return
    try:
        data = json.loads(raw)
        for creator, rows in data.items():
            import_from_json(creator, json.dumps(rows))
        print(f"[history] Restored {sum(len(v) for v in data.values())} rows from HISTORY_JSON")
    except Exception as e:
        print(f"[history] bootstrap_from_env error: {e}")
