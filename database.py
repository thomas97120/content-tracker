"""
database.py — SQLite central pour Content Tracker
Remplace tous les JSON stores (users, creator_apis, history, goals, ideas,
scheduled_posts, push_subscriptions).

Persistence Render : DB_BACKUP_B64 env var → bootstrap au démarrage.
Export via /api/admin/export pour mettre à jour l'env var.
"""

import os
import sqlite3
import threading
import base64
import json
from pathlib import Path
from contextlib import contextmanager

DB_FILE   = os.environ.get("DB_FILE", "app.db")
_local    = threading.local()

# ──────────────────────────────────────────────────────────────
# Connexion thread-local
# ──────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return _local.conn


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ──────────────────────────────────────────────────────────────
# Bootstrap depuis env var (Render persistence)
# ──────────────────────────────────────────────────────────────

def bootstrap_from_env():
    """Restaure app.db depuis DB_BACKUP_B64 si le fichier n'existe pas."""
    if Path(DB_FILE).exists():
        return False  # déjà là
    b64 = os.environ.get("DB_BACKUP_B64", "")
    if b64:
        try:
            Path(DB_FILE).write_bytes(base64.b64decode(b64))
            print(f"[db] Restored from DB_BACKUP_B64 ({Path(DB_FILE).stat().st_size} bytes)")
            return True
        except Exception as e:
            print(f"[db] Bootstrap failed: {e}")
    return False


def export_b64() -> str:
    """Retourne la DB encodée en base64 pour l'env var Render."""
    return base64.b64encode(Path(DB_FILE).read_bytes()).decode()


# ──────────────────────────────────────────────────────────────
# Schéma
# ──────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email           TEXT PRIMARY KEY COLLATE NOCASE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'creator',
    creator_name    TEXT,
    verified        INTEGER NOT NULL DEFAULT 0,
    verify_token    TEXT,
    reset_token     TEXT,
    reset_expires   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_creator ON users(creator_name);

CREATE TABLE IF NOT EXISTS creator_apis (
    creator_name    TEXT NOT NULL,
    key_name        TEXT NOT NULL,
    value           TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (creator_name, key_name)
);
CREATE INDEX IF NOT EXISTS idx_apis_creator ON creator_apis(creator_name);

CREATE TABLE IF NOT EXISTS history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    creator         TEXT NOT NULL,
    plateforme      TEXT,
    date            TEXT,
    titre           TEXT,
    format          TEXT,
    vues            INTEGER DEFAULT 0,
    reach           INTEGER DEFAULT 0,
    abonnes         INTEGER DEFAULT 0,
    likes           INTEGER DEFAULT 0,
    commentaires    INTEGER DEFAULT 0,
    partages        INTEGER DEFAULT 0,
    sauvegardes     INTEGER DEFAULT 0,
    channel_name    TEXT,
    synced_at       TEXT DEFAULT (datetime('now')),
    source          TEXT DEFAULT 'sync',
    UNIQUE(creator, plateforme, date, titre)
);
CREATE INDEX IF NOT EXISTS idx_history_creator      ON history(creator);
CREATE INDEX IF NOT EXISTS idx_history_creator_date ON history(creator, date);
CREATE INDEX IF NOT EXISTS idx_history_date         ON history(date);

CREATE TABLE IF NOT EXISTS goals (
    creator         TEXT PRIMARY KEY,
    views_per_week  INTEGER DEFAULT 0,
    posts_per_week  INTEGER DEFAULT 0,
    engagement_pct  REAL    DEFAULT 0,
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ideas (
    id          TEXT PRIMARY KEY,
    creator     TEXT NOT NULL,
    titre       TEXT,
    description TEXT,
    plateforme  TEXT,
    format      TEXT,
    status      TEXT DEFAULT 'pending',
    created_at  TEXT DEFAULT (datetime('now')),
    decision_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ideas_creator ON ideas(creator, status);

CREATE TABLE IF NOT EXISTS scheduled_posts (
    id           TEXT PRIMARY KEY,
    creator      TEXT NOT NULL,
    platform     TEXT,
    title        TEXT,
    caption      TEXT,
    format       TEXT,
    scheduled_at TEXT,
    status       TEXT DEFAULT 'scheduled',
    notified     INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now')),
    notes        TEXT,
    media_path   TEXT,
    media_name   TEXT,
    publish_id   TEXT,
    published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sched_creator ON scheduled_posts(creator, status);
CREATE INDEX IF NOT EXISTS idx_sched_time    ON scheduled_posts(scheduled_at, status);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    email       TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    p256dh      TEXT,
    auth_key    TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (email, endpoint)
);
CREATE INDEX IF NOT EXISTS idx_push_email ON push_subscriptions(email);
"""


def init_db():
    """Crée les tables si elles n'existent pas."""
    bootstrap_from_env()
    with db() as conn:
        conn.executescript(SCHEMA)
    print(f"[db] Initialized: {DB_FILE}")


# ──────────────────────────────────────────────────────────────
# Migration depuis les anciens JSON stores
# ──────────────────────────────────────────────────────────────

def migrate_from_json():
    """
    Importe les données des anciens fichiers JSON dans SQLite.
    Idempotent — ne réimporte pas si les données existent déjà.
    """
    with db() as conn:
        migrated = []

        # 1. users.json
        if Path("users.json").exists():
            existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if existing == 0:
                users = json.loads(Path("users.json").read_text())
                for u in users:
                    conn.execute("""
                        INSERT OR IGNORE INTO users
                        (email, password_hash, role, creator_name, verified, verify_token, reset_token)
                        VALUES (?,?,?,?,?,?,?)
                    """, (u.get("email"), u.get("password_hash", ""), u.get("role","creator"),
                          u.get("creator_name"), int(u.get("verified", 1)),
                          u.get("verify_token"), u.get("reset_token")))
                migrated.append(f"users ({len(users)})")

        # 2. creator_apis.json
        if Path("creator_apis.json").exists():
            existing = conn.execute("SELECT COUNT(*) FROM creator_apis").fetchone()[0]
            if existing == 0:
                apis = json.loads(Path("creator_apis.json").read_text())
                for creator, keys in apis.items():
                    for k, v in keys.items():
                        conn.execute("""
                            INSERT OR IGNORE INTO creator_apis (creator_name, key_name, value)
                            VALUES (?,?,?)
                        """, (creator, k, v or ""))
                migrated.append(f"creator_apis ({sum(len(v) for v in apis.values())} keys)")

        # 3. scheduled_posts.json
        if Path("scheduled_posts.json").exists():
            existing = conn.execute("SELECT COUNT(*) FROM scheduled_posts").fetchone()[0]
            if existing == 0:
                sched = json.loads(Path("scheduled_posts.json").read_text())
                count = 0
                for creator, posts in sched.items():
                    for p in posts:
                        conn.execute("""
                            INSERT OR IGNORE INTO scheduled_posts
                            (id, creator, platform, title, caption, format,
                             scheduled_at, status, notified, created_at, notes,
                             media_path, media_name, publish_id, published_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (p.get("id"), creator, p.get("platform"), p.get("title"),
                              p.get("caption"), p.get("format"), p.get("scheduled_at"),
                              p.get("status","scheduled"), int(p.get("notified",0)),
                              p.get("created_at"), p.get("notes"), p.get("media_path"),
                              p.get("media_name"), p.get("publish_id"), p.get("published_at")))
                        count += 1
                migrated.append(f"scheduled_posts ({count})")

        # 4. goals (goals_store.json ou goals.json)
        for fname in ("goals_store.json", "goals.json"):
            if Path(fname).exists():
                existing = conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
                if existing == 0:
                    data = json.loads(Path(fname).read_text())
                    for creator, g in data.items():
                        conn.execute("""
                            INSERT OR IGNORE INTO goals
                            (creator, views_per_week, posts_per_week, engagement_pct)
                            VALUES (?,?,?,?)
                        """, (creator, g.get("views_per_week",0),
                              g.get("posts_per_week",0), g.get("engagement_pct",0)))
                    migrated.append(f"goals ({len(data)})")
                break

        # 5. ideas (ideas_store.json ou ideas.json)
        for fname in ("ideas_store.json", "ideas.json"):
            if Path(fname).exists():
                existing = conn.execute("SELECT COUNT(*) FROM ideas").fetchone()[0]
                if existing == 0:
                    data = json.loads(Path(fname).read_text())
                    count = 0
                    for creator, ideas_list in data.items():
                        if not isinstance(ideas_list, list):
                            continue
                        for idea in ideas_list:
                            conn.execute("""
                                INSERT OR IGNORE INTO ideas
                                (id, creator, titre, description, plateforme, format, status, created_at, decision_at)
                                VALUES (?,?,?,?,?,?,?,?,?)
                            """, (idea.get("id"), creator, idea.get("titre"),
                                  idea.get("description"), idea.get("plateforme"),
                                  idea.get("format"), idea.get("status") or idea.get("decided","pending"),
                                  idea.get("created_at"), idea.get("decision_at")))
                            count += 1
                    migrated.append(f"ideas ({count})")
                break

        # 6. push_subscriptions.json
        if Path("push_subscriptions.json").exists():
            existing = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
            if existing == 0:
                data = json.loads(Path("push_subscriptions.json").read_text())
                count = 0
                for email, subs in data.items():
                    for sub in subs:
                        keys = sub.get("keys", {})
                        conn.execute("""
                            INSERT OR IGNORE INTO push_subscriptions
                            (email, endpoint, p256dh, auth_key)
                            VALUES (?,?,?,?)
                        """, (email, sub.get("endpoint",""), keys.get("p256dh",""), keys.get("auth","")))
                        count += 1
                migrated.append(f"push_subscriptions ({count})")

        if migrated:
            print(f"[db] Migrated from JSON: {', '.join(migrated)}")
        else:
            print("[db] No JSON migration needed (tables already populated or files missing)")
