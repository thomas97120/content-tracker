"""
app.py — version 3.1
Démarre avec : python app.py
"""

from flask import Flask, jsonify, request, send_file, session
from flask_cors import CORS
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
import json
import os
import secrets
import datetime as dt

from collectors import get_youtube_stats, get_instagram_stats, get_facebook_stats
from sheets import (
    get_creator_stats, add_manual_stats,
    get_dashboard_data, save_content_decision
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-render")
CORS(app, supports_credentials=True)


# ──────────────────────────────────────────────────────────────
# USERS — cache mémoire + env var Render comme source initiale
# ──────────────────────────────────────────────────────────────
USERS_FILE = "users.json"
_users_cache: list | None = None


def load_users() -> list:
    global _users_cache
    if _users_cache is not None:
        return _users_cache

    # 1. Fichier local (dev ou fichier déjà initialisé)
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            _users_cache = json.load(f)
        return _users_cache

    # 2. Env var Render (USERS_JSON) → bootstrap
    env_data = os.environ.get("USERS_JSON")
    if env_data:
        _users_cache = json.loads(env_data)
        _flush_users()          # écrit le fichier pour cette session
        return _users_cache

    _users_cache = []
    return _users_cache


def _flush_users():
    """Écrit le cache sur disque."""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(_users_cache, f, indent=2, ensure_ascii=False)


def save_users(users: list):
    global _users_cache
    _users_cache = users
    _flush_users()


def get_all_creators() -> list:
    """Tous les créateurs depuis users.json (pas l'env var CREATORS)."""
    return [
        u["creator_name"]
        for u in load_users()
        if u.get("creator_name") and u.get("role") == "creator"
    ]


def find_user_by_email(email: str):
    return next(
        (u for u in load_users() if u["email"].lower() == email.lower()), None
    )


def current_user():
    email = session.get("user_email")
    if not email:
        return None
    return find_user_by_email(email)


# ──────────────────────────────────────────────────────────────
# DECORATORS
# ──────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "Connexion requise"}), 401
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "Connexion requise"}), 401
        if user.get("role") != "admin":
            return jsonify({"error": "Admin requis"}), 403
        return f(*args, **kwargs)
    return wrapper


def can_access_creator(requested_creator):
    user = current_user()
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return user.get("creator_name") == requested_creator


# ──────────────────────────────────────────────────────────────
# AUTH — LOGIN / LOGOUT / ME
# ──────────────────────────────────────────────────────────────
@app.route("/api/auth/login", methods=["POST"])
def login():
    data     = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400

    user = find_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Identifiants invalides"}), 401

    # Vérifie email si le champ existe (rétrocompatible : comptes anciens = ok)
    if not user.get("verified", True):
        return jsonify({"error": "Email non vérifié. Vérifie ta boîte mail."}), 401

    session["user_email"] = user["email"]
    return jsonify({
        "success": True,
        "user": {
            "email":        user["email"],
            "role":         user["role"],
            "creator_name": user.get("creator_name")
        }
    })


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/auth/me", methods=["GET"])
@login_required
def me():
    user = current_user()
    return jsonify({
        "email":        user["email"],
        "role":         user["role"],
        "creator_name": user.get("creator_name")
    })


# ──────────────────────────────────────────────────────────────
# AUTH — INSCRIPTION
# ──────────────────────────────────────────────────────────────
@app.route("/api/auth/register", methods=["POST"])
def register():
    from mailer import send_verification

    data         = request.get_json(silent=True) or {}
    email        = (data.get("email") or "").strip().lower()
    password     = data.get("password") or ""
    creator_name = (data.get("creator_name") or "").strip()

    if not email or not password or not creator_name:
        return jsonify({"error": "Email, mot de passe et nom de créateur requis"}), 400
    if len(password) < 8:
        return jsonify({"error": "Mot de passe trop court (8 caractères minimum)"}), 400
    if find_user_by_email(email):
        return jsonify({"error": "Cet email est déjà utilisé"}), 409

    token  = secrets.token_urlsafe(32)
    expiry = (dt.datetime.now() + dt.timedelta(hours=24)).isoformat()

    users = load_users()
    users.append({
        "email":                email,
        "password_hash":        generate_password_hash(password),
        "role":                 "creator",
        "creator_name":         creator_name,
        "verified":             False,
        "verification_token":   token,
        "token_expiry":         expiry,
    })
    save_users(users)
    send_verification(email, token)

    return jsonify({
        "success": True,
        "message": "Compte créé ! Vérifie ta boîte mail pour activer ton compte."
    })


# ──────────────────────────────────────────────────────────────
# AUTH — VÉRIFICATION EMAIL
# ──────────────────────────────────────────────────────────────
@app.route("/api/auth/verify/<token>", methods=["GET"])
def verify_email(token):
    users = load_users()
    user  = next((u for u in users if u.get("verification_token") == token), None)

    if not user:
        return _html_page("❌ Lien invalide", "Ce lien de vérification n'existe pas."), 400

    expiry = user.get("token_expiry")
    if expiry and dt.datetime.fromisoformat(expiry) < dt.datetime.now():
        return _html_page("⏰ Lien expiré", "Inscris-toi à nouveau pour recevoir un nouveau lien."), 400

    user["verified"] = True
    user.pop("verification_token", None)
    user.pop("token_expiry", None)
    save_users(users)

    return _html_page(
        "✅ Email confirmé !",
        "Ton compte est activé. <a href='/'>Connecte-toi maintenant →</a>"
    )


# ──────────────────────────────────────────────────────────────
# AUTH — MOT DE PASSE OUBLIÉ
# ──────────────────────────────────────────────────────────────
@app.route("/api/auth/forgot-password", methods=["POST"])
def forgot_password():
    from mailer import send_reset

    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    user = find_user_by_email(email)
    if user:
        token  = secrets.token_urlsafe(32)
        expiry = (dt.datetime.now() + dt.timedelta(hours=1)).isoformat()

        users = load_users()
        for u in users:
            if u["email"].lower() == email:
                u["reset_token"]  = token
                u["reset_expiry"] = expiry
                break
        save_users(users)
        send_reset(email, token)

    # Toujours répondre OK (pas de fuite info sur l'existence de l'email)
    return jsonify({
        "success": True,
        "message": "Si cet email existe, un lien de réinitialisation a été envoyé."
    })


@app.route("/api/auth/reset/<token>", methods=["GET"])
def reset_password_page(token):
    """Page HTML de reset (rendu côté serveur)."""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Nouveau mot de passe — Content Tracker</title>
  <style>
    body {{ font-family:'DM Sans',sans-serif; background:#0a0a0f; color:#f0f0f5;
           display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
    .card {{ background:#1a1a24; border:1px solid rgba(255,255,255,.07);
             border-radius:16px; padding:32px; width:340px; }}
    h2 {{ margin:0 0 8px; }}
    p  {{ color:#6b6b80; font-size:13px; margin:0 0 24px; }}
    input {{ width:100%; background:#13131a; border:1px solid rgba(255,255,255,.07);
             border-radius:10px; color:#f0f0f5; font-size:15px; padding:12px 14px;
             outline:none; box-sizing:border-box; margin-bottom:12px; }}
    input:focus {{ border-color:#7c6aff; }}
    button {{ width:100%; padding:14px; border:none; border-radius:10px;
              background:linear-gradient(135deg,#7c6aff,#ff6a9b);
              color:#fff; font-size:15px; font-weight:500; cursor:pointer; }}
    #msg {{ margin-top:12px; font-size:13px; text-align:center; }}
    .ok  {{ color:#3ddc84; }}
    .err {{ color:#ff5555; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>🔑 Nouveau mot de passe</h2>
    <p>Choisis un mot de passe de 8 caractères minimum.</p>
    <input type="password" id="pwd"  placeholder="Nouveau mot de passe">
    <input type="password" id="pwd2" placeholder="Confirme le mot de passe">
    <button onclick="reset()">Changer le mot de passe</button>
    <div id="msg"></div>
  </div>
  <script>
    async function reset() {{
      const p1  = document.getElementById('pwd').value;
      const p2  = document.getElementById('pwd2').value;
      const msg = document.getElementById('msg');
      if (p1.length < 8)  {{ msg.className='err'; msg.textContent='Trop court (8 min)'; return; }}
      if (p1 !== p2)       {{ msg.className='err'; msg.textContent='Les mots de passe sont différents'; return; }}
      const r = await fetch('/api/auth/reset/{token}', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{ password: p1 }})
      }});
      const d = await r.json();
      msg.className = r.ok ? 'ok' : 'err';
      msg.textContent = d.message || d.error;
      if (r.ok) setTimeout(() => window.location = '/', 2000);
    }}
  </script>
</body>
</html>"""


@app.route("/api/auth/reset/<token>", methods=["POST"])
def reset_password(token):
    data     = request.get_json(silent=True) or {}
    password = data.get("password") or ""

    if len(password) < 8:
        return jsonify({"error": "Mot de passe trop court"}), 400

    users = load_users()
    user  = next((u for u in users if u.get("reset_token") == token), None)

    if not user:
        return jsonify({"error": "Lien invalide ou déjà utilisé"}), 400

    expiry = user.get("reset_expiry")
    if expiry and dt.datetime.fromisoformat(expiry) < dt.datetime.now():
        return jsonify({"error": "Lien expiré (1h max)"}), 400

    user["password_hash"] = generate_password_hash(password)
    user.pop("reset_token",  None)
    user.pop("reset_expiry", None)
    save_users(users)

    return jsonify({"success": True, "message": "Mot de passe changé ! Redirection…"})


# ──────────────────────────────────────────────────────────────
# CREATOR — CLÉS API
# ──────────────────────────────────────────────────────────────
@app.route("/api/creator/apis", methods=["GET"])
@login_required
def get_my_apis():
    from creator_apis import get_masked_apis
    user    = current_user()
    creator = user.get("creator_name") or user["email"]
    return jsonify(get_masked_apis(creator))


@app.route("/api/creator/apis", methods=["POST"])
@login_required
def save_my_apis():
    from creator_apis import save_creator_apis
    user    = current_user()
    creator = user.get("creator_name") or user["email"]
    data    = request.get_json(silent=True) or {}
    save_creator_apis(creator, data)
    return jsonify({"success": True, "message": "Clés API sauvegardées."})


@app.route("/api/creator/apis/<key>", methods=["DELETE"])
@login_required
def delete_my_api(key):
    from creator_apis import delete_creator_api
    user    = current_user()
    creator = user.get("creator_name") or user["email"]
    delete_creator_api(creator, key)
    return jsonify({"success": True})


# ──────────────────────────────────────────────────────────────
# ROUTES CRÉATEUR — STATS / IDÉES
# ──────────────────────────────────────────────────────────────
@app.route("/api/stats/<creator>", methods=["GET"])
@login_required
def get_stats(creator):
    if not can_access_creator(creator):
        return jsonify({"error": "Accès interdit"}), 403
    stats = get_creator_stats(creator)
    return jsonify({"creator": creator, "stats": stats})


@app.route("/api/stats/manual", methods=["POST"])
@login_required
def add_stats():
    user = current_user()
    data = request.get_json(silent=True) or {}

    required = ["creator", "platform", "date", "views", "likes"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Champs requis : {required}"}), 400

    if user["role"] != "admin" and data["creator"] != user.get("creator_name"):
        return jsonify({"error": "Accès interdit"}), 403

    success = add_manual_stats(data)
    return jsonify({"success": success})


@app.route("/api/ideas/swipe", methods=["POST"])
@login_required
def swipe_idea():
    user = current_user()
    data = request.get_json(silent=True) or {}

    if not all(k in data for k in ["idea", "decision", "creator"]):
        return jsonify({"error": "Champs requis : idea, decision, creator"}), 400

    if user["role"] != "admin" and data["creator"] != user.get("creator_name"):
        return jsonify({"error": "Accès interdit"}), 403

    save_content_decision(data)
    return jsonify({"success": True})


# ──────────────────────────────────────────────────────────────
# ROUTES ADMIN
# ──────────────────────────────────────────────────────────────
@app.route("/api/admin/creators", methods=["GET"])
@admin_required
def list_creators():
    creators = get_all_creators()
    return jsonify({"creators": creators})


@app.route("/api/admin/dashboard", methods=["GET"])
@admin_required
def dashboard():
    data = get_dashboard_data()
    return jsonify(data)


@app.route("/api/admin/sync", methods=["POST"])
@admin_required
def sync_all():
    """Sync global (env vars) ou par créateur si token présent."""
    try:
        from creator_apis import get_creator_apis
        from collectors import get_youtube_stats_apikey
        from sheets import get_google_creds, write_stats_to_sheet, get_spreadsheet_id

        sheet_id = get_spreadsheet_id()
        yt_stats, ig_stats, fb_stats = [], [], []

        creators = get_all_creators()
        for creator in creators:
            c_apis = get_creator_apis(creator)

            # YouTube : clé API par créateur si dispo, sinon OAuth global
            yt_key = c_apis.get("youtube_api_key")
            yt_cid = c_apis.get("youtube_channel_id")
            if yt_key and yt_cid:
                yt_stats += get_youtube_stats_apikey(api_key=yt_key, channel_id=yt_cid)
            else:
                try:
                    creds     = get_google_creds()
                    yt_stats += get_youtube_stats(creds)
                except Exception:
                    pass

            # Instagram + Facebook
            token  = c_apis.get("meta_access_token")
            ig_id  = c_apis.get("instagram_business_id")
            fb_id  = c_apis.get("facebook_page_id")
            ig_stats += get_instagram_stats(token=token, business_id=ig_id)
            fb_stats += get_facebook_stats(token=token, page_id=fb_id)

        all_stats = yt_stats + ig_stats + fb_stats

        try:
            creds = get_google_creds()
            write_stats_to_sheet(creds, sheet_id, all_stats)
        except Exception as e:
            print(f"Google Sheets write error : {e}")

        return jsonify({"synced": {
            "youtube":   len(yt_stats),
            "instagram": len(ig_stats),
            "facebook":  len(fb_stats),
            "total":     len(all_stats)
        }})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────────────────────
# HEALTH / FRONT
# ──────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "3.0.0"})


@app.route("/", methods=["GET"])
def serve_index():
    return send_file("index.html")


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────
def _html_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} — Content Tracker</title>
  <style>
    body {{ font-family:'DM Sans',sans-serif; background:#0a0a0f; color:#f0f0f5;
           display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
    .card {{ background:#1a1a24; border:1px solid rgba(255,255,255,.07);
             border-radius:16px; padding:40px 32px; text-align:center; max-width:400px; }}
    h2 {{ margin:0 0 12px; font-size:22px; }}
    p  {{ color:#9090a0; line-height:1.6; }}
    a  {{ color:#7c6aff; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>{title}</h2>
    <p>{body}</p>
  </div>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
