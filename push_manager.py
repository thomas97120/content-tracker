"""
push_manager.py — Web Push notifications (VAPID / PWA)

Setup Render :
  VAPID_PUBLIC_KEY  → généré par generate_vapid_keys()
  VAPID_PRIVATE_KEY → généré par generate_vapid_keys()
  VAPID_EMAIL       → mailto:ton@email.com

pip install pywebpush
"""
from __future__ import annotations
import os
import json

VAPID_PUBLIC_KEY  = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL       = os.environ.get("VAPID_EMAIL", "mailto:admin@content-tracker.app")

# Stockage des abonnements en mémoire + fichier
_SUBS_FILE = "push_subscriptions.json"
_subscriptions: dict = {}   # { user_email: [subscription_info, ...] }


def _load_subs():
    global _subscriptions
    if os.path.exists(_SUBS_FILE):
        try:
            with open(_SUBS_FILE) as f:
                _subscriptions = json.load(f)
        except Exception:
            _subscriptions = {}


def _save_subs():
    with open(_SUBS_FILE, "w") as f:
        json.dump(_subscriptions, f)


_load_subs()


def save_subscription(user_email: str, subscription: dict):
    """Enregistre ou met à jour l'abonnement push d'un utilisateur."""
    subs = _subscriptions.setdefault(user_email, [])
    endpoint = subscription.get("endpoint", "")
    # Déduplique par endpoint
    _subscriptions[user_email] = [s for s in subs if s.get("endpoint") != endpoint]
    _subscriptions[user_email].append(subscription)
    _save_subs()


def remove_subscription(user_email: str, endpoint: str):
    subs = _subscriptions.get(user_email, [])
    _subscriptions[user_email] = [s for s in subs if s.get("endpoint") != endpoint]
    _save_subs()


def send_push(user_email: str, title: str, body: str, url: str = "/") -> dict:
    """Envoie une notification push à tous les abonnements d'un utilisateur."""
    if not VAPID_PRIVATE_KEY:
        return {"error": "VAPID_PRIVATE_KEY manquant"}

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return {"error": "pywebpush non installé (pip install pywebpush)"}

    subs    = _subscriptions.get(user_email, [])
    ok      = 0
    failed  = []
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
                # Abonnement expiré → retirer
                failed.append(sub.get("endpoint", ""))
            else:
                failed.append(str(e)[:60])

    # Nettoie les abonnements expirés
    if failed:
        _subscriptions[user_email] = [
            s for s in subs if s.get("endpoint") not in failed
        ]
        _save_subs()

    return {"sent": ok, "failed": len(failed)}


def send_push_to_all(title: str, body: str, url: str = "/") -> dict:
    """Admin : envoie à tous les abonnés."""
    results = {}
    for email in list(_subscriptions.keys()):
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
    if not _subscriptions.get(user_email):
        return  # Pas abonné → skip

    # Calcule métriques
    def _sum(stats, key):
        return sum(p.get(key, 0) or 0 for pl in stats.values() for p in pl)

    views_cur  = _sum(stats_cur,  "vues")
    views_prev = _sum(stats_prev, "vues")
    posts_cur  = sum(len(pl) for pl in stats_cur.values())
    posts_prev = sum(len(pl) for pl in stats_prev.values())

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

    # Alerte : plus de post depuis 5+ jours
    import datetime
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

    # Alerte : engagement fort (positive)
    likes  = _sum(stats_cur, "likes")
    views  = _sum(stats_cur, "vues")
    if views > 0:
        eng = (likes + _sum(stats_cur, "commentaires")) / views * 100
        if eng >= 8:
            alerts.append((
                "🔥 Engagement exceptionnel !",
                f"Ton taux d'engagement est à {eng:.1f}% — dans le top 10% des créateurs.",
                "/"
            ))

    for title, body, url in alerts[:2]:   # max 2 alertes à la fois
        send_push(user_email, title, body, url)
