"""
push_manager.py — Web Push notifications (VAPID / PWA) — SQLite storage
"""
from __future__ import annotations
import os
import json
import datetime

VAPID_PUBLIC_KEY  = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL       = os.environ.get("VAPID_EMAIL", "mailto:admin@content-tracker.app")


def save_subscription(user_email: str, subscription: dict):
    """Enregistre ou met à jour l'abonnement push d'un utilisateur."""
    from database import db
    endpoint = subscription.get("endpoint", "")
    keys     = subscription.get("keys", {})
    p256dh   = keys.get("p256dh", "")
    auth_key = keys.get("auth", "")
    with db() as conn:
        conn.execute("""
            INSERT INTO push_subscriptions (email, endpoint, p256dh, auth_key)
            VALUES (?,?,?,?)
            ON CONFLICT(email, endpoint) DO UPDATE SET
                p256dh   = excluded.p256dh,
                auth_key = excluded.auth_key
        """, (user_email, endpoint, p256dh, auth_key))


def remove_subscription(user_email: str, endpoint: str):
    from database import db
    with db() as conn:
        conn.execute(
            "DELETE FROM push_subscriptions WHERE email = ? AND endpoint = ?",
            (user_email, endpoint)
        )


def _get_subs(user_email: str) -> list:
    from database import get_conn
    rows = get_conn().execute(
        "SELECT endpoint, p256dh, auth_key FROM push_subscriptions WHERE email = ?",
        (user_email,)
    ).fetchall()
    return [
        {"endpoint": r["endpoint"], "keys": {"p256dh": r["p256dh"], "auth": r["auth_key"]}}
        for r in rows
    ]


def _get_all_emails() -> list:
    from database import get_conn
    rows = get_conn().execute(
        "SELECT DISTINCT email FROM push_subscriptions"
    ).fetchall()
    return [r["email"] for r in rows]


def send_push(user_email: str, title: str, body: str, url: str = "/") -> dict:
    """Envoie une notification push à tous les abonnements d'un utilisateur."""
    if not VAPID_PRIVATE_KEY:
        return {"error": "VAPID_PRIVATE_KEY manquant"}

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return {"error": "pywebpush non installé (pip install pywebpush)"}

    subs    = _get_subs(user_email)
    ok      = 0
    expired = []
    payload = json.dumps({"title": title, "body": body, "url": url})

    for sub in subs:
        try:
            webpush(
                subscription_info = sub,
                data              = payload,
                vapid_private_key = VAPID_PRIVATE_KEY,
                vapid_claims      = {"sub": VAPID_EMAIL},
            )
            ok += 1
        except WebPushException as e:
            if "410" in str(e) or "404" in str(e):
                expired.append(sub["endpoint"])
            # else: log but keep

    # Nettoie abonnements expirés
    for ep in expired:
        remove_subscription(user_email, ep)

    return {"sent": ok, "failed": len(expired)}


def send_push_to_all(title: str, body: str, url: str = "/") -> dict:
    """Admin : envoie à tous les abonnés."""
    results = {}
    for email in _get_all_emails():
        results[email] = send_push(email, title, body, url)
    return results


def generate_vapid_keys() -> dict:
    """Génère une paire VAPID. Appeler une seule fois, stocker dans Render."""
    try:
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        return {
            "VAPID_PUBLIC_KEY":  v.public_key.public_bytes(
                __import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding","PublicFormat"]).Encoding.X962,
                __import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding","PublicFormat"]).PublicFormat.UncompressedPoint,
            ).hex(),
            "VAPID_PRIVATE_KEY": v.private_key.private_bytes(
                __import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding","PrivateFormat","NoEncryption"]).Encoding.PEM,
                __import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding","PrivateFormat","NoEncryption"]).PrivateFormat.TraditionalOpenSSL,
                __import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding","PrivateFormat","NoEncryption"]).NoEncryption(),
            ).decode(),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Alertes automatiques ──────────────────────────────────────

def check_and_alert(user_email: str, stats_cur: dict, stats_prev: dict, days: int):
    """
    Appelé après chaque rechargement de stats.
    Envoie des push si conditions critiques détectées.
    """
    if not _get_subs(user_email):
        return

    def _sum(stats, key):
        return sum(p.get(key, 0) or 0 for pl in stats.values() for p in pl)

    views_cur  = _sum(stats_cur,  "vues")
    views_prev = _sum(stats_prev, "vues")

    alerts = []

    # Alerte : chute vues > 40%
    if views_prev > 0:
        delta = (views_cur - views_prev) / views_prev * 100
        if delta <= -40:
            alerts.append((
                "📉 Chute de vues détectée",
                f"Tes vues ont baissé de {delta:.0f}% par rapport à la période précédente.",
                "/"
            ))

    # Alerte : inactivité 5+ jours
    all_dates = [p.get("date","") for pl in stats_cur.values() for p in pl if p.get("date")]
    if all_dates:
        latest = max(all_dates)
        try:
            days_since = (datetime.date.today() - datetime.date.fromisoformat(latest)).days
            if days_since >= 5:
                alerts.append((
                    "⏰ Inactivité détectée",
                    f"Aucun post publié depuis {days_since} jours — l'algorithme te pénalise.",
                    "/"
                ))
        except Exception:
            pass

    # Alerte : engagement fort
    likes = _sum(stats_cur, "likes")
    views = _sum(stats_cur, "vues")
    if views > 0:
        eng = (likes + _sum(stats_cur, "commentaires")) / views * 100
        if eng >= 8:
            alerts.append((
                "🔥 Engagement exceptionnel !",
                f"Ton taux d'engagement est à {eng:.1f}% — dans le top 10% des créateurs.",
                "/"
            ))

    # Alerte : spike
    all_posts = [p for pl in stats_cur.values() for p in pl]
    if len(all_posts) >= 3:
        all_views = [p.get("vues", 0) or 0 for p in all_posts]
        avg_v = sum(all_views) / len(all_views)
        for p in sorted(all_posts, key=lambda x: x.get("vues", 0), reverse=True)[:1]:
            v = p.get("vues", 0) or 0
            if avg_v > 0 and v >= avg_v * 3 and v >= 50_000:
                titre = (p.get("titre") or "")[:40] or "Une vidéo"
                def _fmt_v(n):
                    return f"{n/1_000_000:.1f}M" if n >= 1_000_000 else f"{n/1_000:.0f}K"
                alerts.append((
                    "🚀 Vidéo en train d'exploser !",
                    f'"{titre}" — {_fmt_v(v)} vues ({v/avg_v:.1f}x la moyenne). Réponds aux commentaires maintenant.',
                    "/"
                ))

    for title, body, url in alerts[:2]:
        send_push(user_email, title, body, url)
