"""
history_store.py — Historique des stats (SQLite central via database.py)
"""

import datetime
import json
from database import db, get_conn


def upsert_posts(creator: str, rows: list) -> int:
    """Insère ou met à jour les posts. Retourne le nombre de lignes écrites."""
    now   = datetime.datetime.now().isoformat()
    count = 0
    with db() as conn:
        for r in rows:
            conn.execute("""
                INSERT INTO history
                  (creator, plateforme, date, titre, format,
                   vues, abonnes, likes, commentaires, partages, sauvegardes, synced_at, source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(creator, plateforme, date, titre) DO UPDATE SET
                  vues          = excluded.vues,
                  abonnes       = excluded.abonnes,
                  likes         = excluded.likes,
                  commentaires  = excluded.commentaires,
                  partages      = excluded.partages,
                  sauvegardes   = excluded.sauvegardes,
                  synced_at     = excluded.synced_at
            """, (
                creator,
                r.get("plateforme", ""),
                r.get("date", ""),
                (r.get("titre") or "")[:120],
                r.get("format", ""),
                int(r.get("vues", 0) or 0),
                int(r.get("abonnes", 0) or 0),
                int(r.get("likes", 0) or 0),
                int(r.get("commentaires", 0) or 0),
                int(r.get("partages", 0) or 0),
                int(r.get("sauvegardes", 0) or 0),
                now,
                r.get("source", "sync"),
            ))
            count += 1
    return count


def get_history(creator: str, days: int = 365) -> list:
    """Tous les posts d'un créateur sur `days` jours."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn   = get_conn()
    rows   = conn.execute("""
        SELECT plateforme, date, titre, format,
               vues, likes, commentaires, partages, sauvegardes, abonnes
        FROM history
        WHERE creator = ? AND date >= ?
        ORDER BY date DESC
    """, (creator, cutoff)).fetchall()
    return [dict(r) for r in rows]


def get_history_summary(creator: str) -> dict:
    """Résumé global : total posts, période couverte, stats par plateforme."""
    conn   = get_conn()
    total  = conn.execute(
        "SELECT COUNT(*) FROM history WHERE creator=?", (creator,)
    ).fetchone()[0]
    oldest = conn.execute(
        "SELECT MIN(date) FROM history WHERE creator=?", (creator,)
    ).fetchone()[0]
    newest = conn.execute(
        "SELECT MAX(date) FROM history WHERE creator=?", (creator,)
    ).fetchone()[0]
    plat   = conn.execute("""
        SELECT plateforme,
               COUNT(*)          AS n,
               SUM(vues)         AS total_views,
               MAX(vues)         AS max_views
        FROM history WHERE creator=? GROUP BY plateforme
    """, (creator,)).fetchall()

    by_platform = {}
    for r in plat:
        by_platform[r["plateforme"]] = {
            "posts":       r["n"],
            "total_views": r["total_views"] or 0,
            "max_views":   r["max_views"] or 0,
        }

    return {
        "total_posts": total,
        "oldest":      oldest,
        "newest":      newest,
        "by_platform": by_platform,
    }


def get_monthly_breakdown(creator: str) -> list:
    """Vues + posts par mois (pour graphique long terme)."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT substr(date,1,7) AS month,
               plateforme,
               COUNT(*)         AS posts,
               SUM(vues)        AS total_views
        FROM history
        WHERE creator = ?
        GROUP BY month, plateforme
        ORDER BY month ASC
    """, (creator,)).fetchall()
    return [dict(r) for r in rows]


def export_all_json(creator: str) -> str:
    """Sérialise tout l'historique en JSON."""
    return json.dumps(get_history(creator, days=400), ensure_ascii=False)


def import_from_json(creator: str, json_str: str):
    """Restaure depuis JSON."""
    rows = json.loads(json_str)
    # Adapte depuis format export (colonnes anglaises ou françaises)
    adapted = []
    for r in rows:
        adapted.append({
            "plateforme":   r.get("plateforme") or r.get("platform", ""),
            "date":         r.get("date") or r.get("post_date", ""),
            "titre":        r.get("titre") or r.get("title", ""),
            "format":       r.get("format", ""),
            "vues":         r.get("vues") or r.get("views", 0),
            "abonnes":      r.get("abonnes") or r.get("followers", 0),
            "likes":        r.get("likes", 0),
            "commentaires": r.get("commentaires") or r.get("comments", 0),
            "partages":     r.get("partages") or r.get("shares", 0),
            "sauvegardes":  r.get("sauvegardes") or r.get("saves", 0),
        })
    return upsert_posts(creator, adapted)


def bootstrap_from_env():
    """
    Appelé au démarrage — DB_BACKUP_B64 gère la persistence globale,
    mais on supporte aussi HISTORY_JSON pour compatibilité.
    Format: { "creator1": [...], "creator2": [...] }
    """
    import os
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
