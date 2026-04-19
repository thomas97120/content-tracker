"""
app.py — version 3.1
Démarre avec : python app.py
"""

from flask import Flask, jsonify, redirect, request, send_file, session
from flask_cors import CORS
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
import json
import os
import secrets
import datetime as dt
import requests
import time

# Cache simple en mémoire : {creator_days_key: (timestamp, data)}
_stats_cache: dict = {}
CACHE_TTL = 300  # 5 minutes

# Jobs de sync historique : {job_id: {status, progress, result, error}}
import threading
_sync_jobs: dict = {}

from collectors import get_youtube_stats, get_instagram_stats, get_facebook_stats
from sheets import (
    get_creator_stats, add_manual_stats,
    get_dashboard_data, save_content_decision
)
# get_all_creators est défini localement (lit users.json)

APP_URL = os.environ.get("APP_URL", "http://localhost:5000")

# Bootstrap historique depuis env var (Render persistence)
try:
    from history_store import bootstrap_from_env
    bootstrap_from_env()
except Exception as _he:
    print(f"[history] bootstrap skip: {_he}")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-render")
app.config.update(
    SESSION_COOKIE_HTTPONLY  = True,
    SESSION_COOKIE_SAMESITE  = 'Lax',
    SESSION_COOKIE_SECURE    = os.environ.get("FLASK_ENV") != "development",
)
CORS(app, supports_credentials=True)

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=[])


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


def _clear_creator_cache(creator: str):
    """Vide toutes les entrées de cache pour ce créateur."""
    keys = [k for k in _stats_cache if k.startswith(f"{creator}_")]
    for k in keys:
        _stats_cache.pop(k, None)


# ──────────────────────────────────────────────────────────────
# AUTH — LOGIN / LOGOUT / ME
# ──────────────────────────────────────────────────────────────
@limiter.limit("10 per minute")
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


@app.route("/api/auth/change-password", methods=["POST"])
@login_required
def change_password():
    user = current_user()
    data = request.get_json(silent=True) or {}
    current_pw = data.get("current_password") or ""
    new_pw     = data.get("new_password") or ""

    if not check_password_hash(user["password_hash"], current_pw):
        return jsonify({"error": "Mot de passe actuel incorrect"}), 400
    if len(new_pw) < 8:
        return jsonify({"error": "Nouveau mot de passe trop court (8 car. min)"}), 400

    users = load_users()
    for u in users:
        if u["email"] == user["email"]:
            u["password_hash"] = generate_password_hash(new_pw)
            break
    save_users(users)
    return jsonify({"success": True, "message": "Mot de passe changé !"})


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
# OAUTH — GOOGLE (YouTube)
# ──────────────────────────────────────────────────────────────
@app.route("/api/auth/google/connect")
@login_required
def google_connect():
    client_id     = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return jsonify({"error": "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET manquants dans Render"}), 500

    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        {"web": {
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uris": [f"{APP_URL}/api/auth/google/callback"],
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
        }},
        scopes=[
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ]
    )
    flow.redirect_uri = f"{APP_URL}/api/auth/google/callback"
    auth_url, state  = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="false"
    )

    user = current_user()
    session["oauth_state"]         = state
    session["oauth_creator"]       = user.get("creator_name") or user["email"]
    session["oauth_code_verifier"] = getattr(flow, "code_verifier", None)
    return redirect(auth_url)


@app.route("/api/auth/google/callback")
def google_callback():
    import json as _json
    from google_auth_oauthlib.flow import Flow
    from creator_apis import save_creator_apis

    client_id     = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    state         = session.get("oauth_state")
    creator       = session.get("oauth_creator")

    if not creator:
        return redirect("/?error=session_lost")

    flow = Flow.from_client_config(
        {"web": {
            "client_id":     client_id,
            "client_secret": client_secret,
            "redirect_uris": [f"{APP_URL}/api/auth/google/callback"],
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
        }},
        scopes=[
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
        state=state
    )
    flow.redirect_uri = f"{APP_URL}/api/auth/google/callback"

    # Restaure le code_verifier PKCE stocké lors du connect
    code_verifier = session.get("oauth_code_verifier")
    if code_verifier:
        flow.code_verifier = code_verifier

    try:
        # Nécessite HTTPS en prod — contourne pour le callback
        import os as _os
        _os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        flow.fetch_token(authorization_response=request.url.replace("http://", "https://"))
        creds = flow.credentials
        token_data = {
            "token":         creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri":     creds.token_uri,
            "client_id":     creds.client_id,
            "client_secret": creds.client_secret,
            "scopes":        list(creds.scopes or []),
        }
        save_creator_apis(creator, {"google_token": _json.dumps(token_data)})
        _clear_creator_cache(creator)
        return redirect("/?connected=youtube")
    except Exception as e:
        return redirect(f"/?error={str(e)[:80]}")


# ──────────────────────────────────────────────────────────────
# OAUTH — TIKTOK
# ──────────────────────────────────────────────────────────────
@app.route("/api/auth/tiktok/connect")
@login_required
def tiktok_connect():
    import hashlib, base64
    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    if not client_key:
        return jsonify({"error": "TIKTOK_CLIENT_KEY manquant dans Render"}), 500

    user    = current_user()
    state   = secrets.token_urlsafe(16)
    creator = user.get("creator_name") or user["email"]

    # PKCE
    code_verifier  = secrets.token_urlsafe(40)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    session["tiktok_state"]         = state
    session["oauth_creator"]        = creator
    session["tiktok_code_verifier"] = code_verifier

    redirect_uri = f"{APP_URL}/api/auth/tiktok/callback"
    auth_url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={client_key}"
        f"&scope=user.info.basic,user.info.stats,video.list"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    return redirect(auth_url)


@app.route("/api/auth/tiktok/callback")
def tiktok_callback():
    try:
        import json as _json
        from creator_apis import save_creator_apis

        code    = request.args.get("code")
        state   = request.args.get("state")
        creator = session.get("oauth_creator")

        if not creator:
            return redirect("/?error=tiktok_session_perdue_reconnecte_toi")
        if state != session.get("tiktok_state"):
            return redirect("/?error=tiktok_state_mismatch")
        if not code:
            err = request.args.get("error_description", "access_denied")
            return redirect(f"/?error=tiktok_{err[:60]}")

        client_key    = os.environ.get("TIKTOK_CLIENT_KEY")
        client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
        redirect_uri  = f"{APP_URL}/api/auth/tiktok/callback"
        code_verifier = session.get("tiktok_code_verifier", "")

        token_resp = requests.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key":    client_key,
                "client_secret": client_secret,
                "code":          code,
                "grant_type":    "authorization_code",
                "redirect_uri":  redirect_uri,
                "code_verifier": code_verifier,
            }
        ).json()

        print(f"TikTok token response: {token_resp}")

        access_token = token_resp.get("access_token")
        if not access_token:
            err = token_resp.get("message") or token_resp.get("error_description") or str(token_resp)
            return redirect(f"/?error=tiktok_{str(err)[:80]}")

        token_data = {
            "access_token":  access_token,
            "refresh_token": token_resp.get("refresh_token"),
            "open_id":       token_resp.get("open_id"),
            "scope":         token_resp.get("scope"),
            "expires_in":    token_resp.get("expires_in"),
        }
        save_creator_apis(creator, {"tiktok_token": _json.dumps(token_data)})
        _clear_creator_cache(creator)
        return redirect("/?connected=tiktok")

    except Exception as e:
        return redirect(f"/?error=tiktok_exception_{str(e)[:80]}")


# ──────────────────────────────────────────────────────────────
# OAUTH — META (Instagram + Facebook)
# ──────────────────────────────────────────────────────────────
@app.route("/api/auth/meta/connect")
@login_required
def meta_connect():
    app_id = os.environ.get("META_APP_ID")
    if not app_id:
        return jsonify({"error": "META_APP_ID manquant dans Render"}), 500

    user    = current_user()
    state   = secrets.token_urlsafe(16)
    creator = user.get("creator_name") or user["email"]
    session["meta_state"]    = state
    session["oauth_creator"] = creator

    redirect_uri = f"{APP_URL}/api/auth/meta/callback"
    scope        = "email,public_profile,instagram_basic,instagram_manage_insights,pages_show_list,pages_read_engagement"
    auth_url     = (
        f"https://www.facebook.com/v19.0/dialog/oauth"
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state={state}"
    )
    return redirect(auth_url)


@app.route("/api/auth/meta/callback")
def meta_callback():
    from creator_apis import save_creator_apis

    state   = request.args.get("state")
    code    = request.args.get("code")
    creator = session.get("oauth_creator")

    if state != session.get("meta_state") or not creator:
        return redirect("/?error=oauth_state_mismatch")

    app_id      = os.environ.get("META_APP_ID")
    app_secret  = os.environ.get("META_APP_SECRET")
    redirect_uri = f"{APP_URL}/api/auth/meta/callback"

    # Code → token court
    token_resp  = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={"client_id": app_id, "redirect_uri": redirect_uri,
                "client_secret": app_secret, "code": code}
    ).json()
    short_token = token_resp.get("access_token")
    if not short_token:
        return redirect(f"/?error=meta_token_failed")

    # Token court → token long (60 jours)
    long_resp  = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={"grant_type": "fb_exchange_token", "client_id": app_id,
                "client_secret": app_secret, "fb_exchange_token": short_token}
    ).json()
    long_token = long_resp.get("access_token", short_token)

    # Récupère automatiquement Page ID + Instagram Business ID
    pages_resp = requests.get(
        "https://graph.facebook.com/v19.0/me/accounts",
        params={"access_token": long_token,
                "fields": "id,name,instagram_business_account"}
    ).json()

    apis   = {"meta_access_token": long_token}
    fb_id  = None
    ig_id  = None
    for page in pages_resp.get("data", []):
        if not fb_id:
            fb_id = page.get("id")
        ig_acc = page.get("instagram_business_account")
        if ig_acc and not ig_id:
            ig_id = ig_acc.get("id")

    if fb_id: apis["facebook_page_id"]      = fb_id
    if ig_id: apis["instagram_business_id"] = ig_id

    save_creator_apis(creator, apis)
    _clear_creator_cache(creator)
    return redirect("/?connected=meta")


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

    from creator_apis import get_creator_apis
    from collectors import (
        get_youtube_stats_oauth_creator, get_youtube_stats_apikey,
        get_instagram_stats, get_facebook_stats, get_tiktok_stats,
    )

    days    = int(request.args.get("days", 7))
    compare = request.args.get("compare", "1") != "0"
    refresh = request.args.get("refresh") == "1"  # force bypass cache

    # Cache
    cache_key = f"{creator}_{days}_{'c' if compare else 'n'}"
    if not refresh:
        cached = _stats_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < CACHE_TTL:
            return jsonify(cached[1])

    fetch_days = days * 2 if compare else days

    c_apis       = get_creator_apis(creator)
    google_token = c_apis.get("google_token")
    yt_key       = c_apis.get("youtube_api_key")
    yt_cid       = c_apis.get("youtube_channel_id")
    meta_token   = c_apis.get("meta_access_token")
    ig_id        = c_apis.get("instagram_business_id")
    fb_id        = c_apis.get("facebook_page_id")
    tiktok_token = c_apis.get("tiktok_token")

    live   = []
    errors = []

    # YouTube
    if google_token:
        try:
            rows = get_youtube_stats_oauth_creator(google_token, days=fetch_days)
            live += rows
            if not rows:
                errors.append("YouTube OAuth : 0 résultats (chaîne vide ou API non activée)")
        except Exception as e:
            errors.append(f"YouTube OAuth : {e}")
    elif yt_key and yt_cid:
        try:
            rows = get_youtube_stats_apikey(api_key=yt_key, channel_id=yt_cid, days=fetch_days)
            live += rows
            if not rows:
                errors.append("YouTube API Key : 0 résultats")
        except Exception as e:
            errors.append(f"YouTube API Key : {e}")

    # Instagram + Facebook
    if meta_token:
        try:
            ig = get_instagram_stats(token=meta_token, business_id=ig_id)
            live += ig
            if not ig:
                errors.append("Instagram : 0 résultats")
        except Exception as e:
            errors.append(f"Instagram : {e}")
        try:
            fb = get_facebook_stats(token=meta_token, page_id=fb_id)
            live += fb
            if not fb:
                errors.append("Facebook : 0 résultats")
        except Exception as e:
            errors.append(f"Facebook : {e}")

    # TikTok
    if tiktok_token:
        try:
            tt = get_tiktok_stats(tiktok_token, days=fetch_days)
            live += tt
            if not tt:
                errors.append("TikTok : 0 résultats")
        except Exception as e:
            errors.append(f"TikTok : {e}")

    # Regroupe par plateforme + split période courante / précédente
    if live:
        import datetime as _dt
        cutoff_cur  = str(_dt.date.today() - _dt.timedelta(days=days))
        cutoff_prev = str(_dt.date.today() - _dt.timedelta(days=days * 2))

        by_platform = {}
        prev_platform = {}
        account_info = {}

        for row in live:
            p    = row.get("plateforme", "Autre")
            date = row.get("date", "")
            if row.get("_channel_name") and p not in account_info:
                account_info[p] = {
                    "name": row["_channel_name"],
                    "id":   row.get("_channel_id", ""),
                }
            if date >= cutoff_cur:
                by_platform.setdefault(p, []).append(row)
            elif compare and date >= cutoff_prev:
                prev_platform.setdefault(p, []).append(row)

        resp = {"creator": creator, "stats": by_platform,
                "prev_stats": prev_platform if compare else {},
                "source": "live",
                "warnings": errors, "accounts": account_info, "days": days}
        _stats_cache[cache_key] = (time.time(), resp)

        # Push alerts (background, non-bloquant)
        try:
            from push_manager import check_and_alert
            user = current_user()
            if user:
                import threading as _t
                _t.Thread(
                    target=check_and_alert,
                    args=(user["email"], by_platform, prev_platform, days),
                    daemon=True
                ).start()
        except Exception:
            pass

        return jsonify(resp)

    # Fallback : Sheets
    stats = get_creator_stats(creator)
    return jsonify({"creator": creator, "stats": stats, "source": "sheets", "errors": errors, "days": days})


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


@app.route("/api/ideas/<creator>", methods=["GET"])
@login_required
def get_ideas(creator):
    if not can_access_creator(creator):
        return jsonify({"error": "Accès interdit"}), 403
    from ideas_store import get_ideas
    return jsonify({"ideas": get_ideas(creator)})


@app.route("/api/ideas", methods=["POST"])
@login_required
def add_idea():
    from ideas_store import add_idea
    import uuid
    user = current_user()
    data = request.get_json(silent=True) or {}
    creator = data.get("creator") or user.get("creator_name") or ""
    if not can_access_creator(creator):
        return jsonify({"error": "Accès interdit"}), 403
    idea = {
        "id":      str(uuid.uuid4()),
        "title":   data.get("title", ""),
        "desc":    data.get("desc", ""),
        "format":  data.get("format", ""),
        "viral":   data.get("viral", 0),
        "effort":  data.get("effort", 0),
        "decided": None,
        "created_at": dt.datetime.now().isoformat(),
    }
    add_idea(creator, idea)
    return jsonify({"success": True, "idea": idea})


@app.route("/api/ideas/<creator>/generate", methods=["POST"])
@login_required
def generate_ideas(creator):
    """Génère des idées de contenu via IA basées sur les stats du créateur."""
    if not can_access_creator(creator):
        return jsonify({"error": "Accès interdit"}), 403

    from ai_coach import _API_KEY, _API_URL, _MODEL
    from ideas_store import add_idea, get_ideas
    import uuid, json as _json, urllib.request

    if not _API_KEY:
        return jsonify({"error": "GROQ_API_KEY ou OPENAI_API_KEY manquant"}), 400

    # Récupère les stats depuis le cache
    cache_key = f"{creator}_30_c"
    cached = _stats_cache.get(cache_key)
    stats_cur = cached[1].get("stats", {}) if cached else {}

    # Résumé top posts pour le prompt
    all_posts = []
    for plat, posts in stats_cur.items():
        for p in posts:
            v = p.get("vues", 0) or 0
            if v > 0:
                all_posts.append({
                    "platform": plat,
                    "title":    (p.get("titre") or "")[:60],
                    "format":   p.get("format", ""),
                    "views":    v,
                })
    top = sorted(all_posts, key=lambda x: x["views"], reverse=True)[:6]
    platforms = list({p["platform"] for p in all_posts}) or ["TikTok", "YouTube"]

    top_txt = "\n".join(
        f'- [{p["platform"]} · {p["format"]}] "{p["title"]}" → {p["views"]:,} vues'
        for p in top
    ) or "Pas encore de données — génère des idées génériques pertinentes."

    # Idées déjà existantes (pour éviter doublons)
    existing = [i.get("title", "") for i in get_ideas(creator)]
    avoid_txt = "\n".join(f"- {t}" for t in existing[:10]) or "Aucune"

    prompt = f"""Tu es un stratège de contenu expert pour créateurs sur {', '.join(platforms)}.

TOP POSTS DU CRÉATEUR :
{top_txt}

IDÉES DÉJÀ DANS SA LISTE (ne pas répéter) :
{avoid_txt}

Génère exactement 8 idées de contenu originales et actionnables adaptées à ce créateur.
Réponds UNIQUEMENT en JSON valide, sans texte avant/après :

{{
  "ideas": [
    {{
      "title": "Titre accrocheur et court (max 60 chars)",
      "desc": "Description en 1-2 phrases : angle, structure, pourquoi ça va marcher",
      "format": "Short|Reel|TikTok|Video|Story|Live",
      "viral": 8,
      "effort": 3,
      "roi": 9
    }}
  ]
}}

Règles :
- viral (1-10) : potentiel de viralité basé sur les tendances actuelles
- effort (1-10) : temps/énergie nécessaire (1=très simple, 10=très complexe)
- roi (1-10) : rapport viral/effort (calcule intelligemment)
- Mix de formats : au moins 3 formats différents
- Idées concrètes et directement filmables, pas vagues"""

    try:
        body = _json.dumps({
            "model": _MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.85,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
        }).encode()

        req = urllib.request.Request(
            _API_URL, data=body,
            headers={"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as r:
            resp = _json.loads(r.read())

        content = _json.loads(resp["choices"][0]["message"]["content"])
        generated = content.get("ideas", [])

        saved = []
        for idea_data in generated[:8]:
            idea = {
                "id":         str(uuid.uuid4()),
                "title":      idea_data.get("title", "")[:80],
                "desc":       idea_data.get("desc", ""),
                "format":     idea_data.get("format", ""),
                "viral":      min(10, max(1, int(idea_data.get("viral", 5)))),
                "effort":     min(10, max(1, int(idea_data.get("effort", 5)))),
                "roi":        min(10, max(1, int(idea_data.get("roi", 5)))),
                "decided":    None,
                "ai_generated": True,
                "created_at": dt.datetime.now().isoformat(),
            }
            add_idea(creator, idea)
            saved.append(idea)

        return jsonify({"success": True, "ideas": saved, "count": len(saved)})

    except Exception as e:
        return jsonify({"error": f"Erreur IA : {str(e)[:120]}"}), 500


@app.route("/api/ideas/swipe", methods=["POST"])
@login_required
def swipe_idea():
    from ideas_store import update_idea_decision
    user = current_user()
    data = request.get_json(silent=True) or {}

    if not all(k in data for k in ["idea", "decision", "creator"]):
        return jsonify({"error": "Champs requis : idea, decision, creator"}), 400

    if user["role"] != "admin" and data["creator"] != user.get("creator_name"):
        return jsonify({"error": "Accès interdit"}), 403

    update_idea_decision(data["creator"], data.get("idea_id", ""), data["decision"])
    save_content_decision(data)
    return jsonify({"success": True})


@app.route("/api/import/csv", methods=["POST"])
@login_required
def import_csv():
    from csv_parser import parse_csv
    user     = current_user()
    platform = request.form.get("platform", "")
    creator  = request.form.get("creator") or user.get("creator_name") or ""

    if not can_access_creator(creator):
        return jsonify({"error": "Accès interdit"}), 403
    if "file" not in request.files:
        return jsonify({"error": "Fichier manquant"}), 400

    file    = request.files["file"]
    content = file.read().decode("utf-8-sig", errors="replace")

    stats = parse_csv(platform, content)
    if not stats:
        return jsonify({"error": "Aucune ligne valide trouvée — vérifie le format CSV et la plateforme sélectionnée"}), 400

    # Ajoute creator_name à chaque row
    for s in stats:
        s["creator_name"] = creator

    try:
        from sheets import get_google_creds, write_stats_to_sheet, get_spreadsheet_id
        creds    = get_google_creds()
        sheet_id = get_spreadsheet_id()
        write_stats_to_sheet(creds, sheet_id, stats, creator_name=creator)
        return jsonify({"success": True, "imported": len(stats), "platform": platform})
    except Exception as e:
        return jsonify({"error": f"Écriture Sheets échouée : {e}"}), 500


# ──────────────────────────────────────────────────────────────
# ROUTES ADMIN
# ──────────────────────────────────────────────────────────────
@app.route("/api/admin/creators", methods=["GET"])
@admin_required
def list_creators():
    creators = get_all_creators()
    return jsonify({"creators": creators})


@app.route("/api/admin/export", methods=["GET"])
@admin_required
def export_state():
    """
    Retourne le JSON à coller dans les env vars Render pour persister les données.
    USERS_JSON       → users.json
    CREATOR_APIS_JSON → creator_apis.json
    """
    from creator_apis import export_all as export_apis
    return jsonify({
        "USERS_JSON":        load_users(),
        "CREATOR_APIS_JSON": export_apis(),
        "instructions": (
            "Copie chaque valeur dans Render → Environment → ajoute/modifie "
            "les variables USERS_JSON et CREATOR_APIS_JSON. "
            "Redéploie ensuite pour que le bootstrap s'applique."
        )
    })


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

            # YouTube : token OAuth créateur → clé API → OAuth global
            yt_key       = c_apis.get("youtube_api_key")
            yt_cid       = c_apis.get("youtube_channel_id")
            google_token = c_apis.get("google_token")

            if google_token:
                from collectors import get_youtube_stats_oauth_creator
                yt_stats += get_youtube_stats_oauth_creator(google_token)
            elif yt_key and yt_cid:
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
            write_stats_to_sheet(creds, sheet_id, all_stats, creator_name=creator)
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
# INSIGHTS — Smart coach
# ──────────────────────────────────────────────────────────────

@app.route("/api/push/vapid-public-key", methods=["GET"])
def vapid_public_key():
    key = os.environ.get("VAPID_PUBLIC_KEY", "")
    return jsonify({"publicKey": key})


@app.route("/api/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    from push_manager import save_subscription
    user = current_user()
    sub  = request.get_json(silent=True) or {}
    if not sub.get("endpoint"):
        return jsonify({"error": "Abonnement invalide"}), 400
    save_subscription(user["email"], sub)
    return jsonify({"success": True})


@app.route("/api/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    from push_manager import remove_subscription
    user     = current_user()
    data     = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")
    remove_subscription(user["email"], endpoint)
    return jsonify({"success": True})


@app.route("/api/push/test", methods=["POST"])
@login_required
def push_test():
    from push_manager import send_push
    user   = current_user()
    result = send_push(
        user["email"],
        "🧠 Content Tracker",
        "Les notifications sont activées ! Tu seras alerté en cas de chute de vues.",
        "/"
    )
    return jsonify(result)


@app.route("/api/stats/<creator>/ai-suggestions", methods=["GET"])
@login_required
def ai_suggestions(creator):
    if not can_access_creator(creator):
        return jsonify({"error": "Accès interdit"}), 403
    from ai_coach import generate_suggestions

    cache_key = f"{creator}_{request.args.get('days', 7)}_c"
    cached    = _stats_cache.get(cache_key)
    if not cached:
        return jsonify({"error": "Stats non chargées"}), 425

    stats_cur = cached[1].get("stats", {})
    result    = generate_suggestions(stats_cur, creator)
    return jsonify(result)


@app.route("/api/admin/generate-vapid", methods=["GET"])
@admin_required
def generate_vapid():
    from push_manager import generate_vapid_keys
    return jsonify(generate_vapid_keys())


@app.route("/api/stats/<creator>/insights", methods=["GET"])
@login_required
def get_insights(creator):
    if not can_access_creator(creator):
        return jsonify({"error": "Accès interdit"}), 403

    from insights_engine import analyze

    # Récupère stats courantes + précédentes (cache si dispo)
    days = int(request.args.get("days", 7))
    cache_key = f"{creator}_{days}_c"
    cached = _stats_cache.get(cache_key)

    if cached and (time.time() - cached[0]) < CACHE_TTL:
        stats_cur  = cached[1].get("stats", {})
        stats_prev = cached[1].get("prev_stats", {})
    else:
        # Pas de cache → retourne vide (le front appelle /insights après /stats)
        return jsonify({"error": "Stats non chargées, recharge d'abord"}), 425

    result = analyze(stats_cur, stats_prev, days)
    return jsonify(result)


# ──────────────────────────────────────────────────────────────
# HISTORIQUE — sync + lecture
# ──────────────────────────────────────────────────────────────

HISTORY_DAYS = 365  # fenêtre max de collecte


def _run_sync_history(job_id: str, creator: str, c_apis: dict):
    """Exécuté dans un thread background — remplit _sync_jobs[job_id]."""
    from collectors import (
        get_youtube_stats_oauth_creator, get_youtube_stats_apikey,
        get_instagram_stats, get_facebook_stats, get_tiktok_stats,
    )
    from history_store import upsert_posts, get_history_summary

    job = _sync_jobs[job_id]
    all_rows, errors = [], []

    steps = [
        ("YouTube",   bool(c_apis.get("google_token") or (c_apis.get("youtube_api_key") and c_apis.get("youtube_channel_id")))),
        ("Instagram", bool(c_apis.get("meta_access_token") and c_apis.get("instagram_business_id"))),
        ("Facebook",  bool(c_apis.get("meta_access_token") and c_apis.get("facebook_page_id"))),
        ("TikTok",    bool(c_apis.get("tiktok_token"))),
    ]
    total_steps = sum(1 for _, active in steps if active) or 1
    done_steps  = 0

    def advance(name):
        nonlocal done_steps
        done_steps += 1
        job["progress"] = int(done_steps / total_steps * 100)
        job["step"]     = name

    try:
        # YouTube
        if c_apis.get("google_token"):
            job["step"] = "YouTube OAuth…"
            try:
                rows = get_youtube_stats_oauth_creator(c_apis["google_token"], days=HISTORY_DAYS)
                all_rows += rows
            except Exception as e:
                errors.append(f"YouTube OAuth : {e}")
            advance("YouTube")
        elif c_apis.get("youtube_api_key") and c_apis.get("youtube_channel_id"):
            job["step"] = "YouTube API Key…"
            try:
                rows = get_youtube_stats_apikey(
                    api_key=c_apis["youtube_api_key"],
                    channel_id=c_apis["youtube_channel_id"],
                    days=HISTORY_DAYS,
                )
                all_rows += rows
            except Exception as e:
                errors.append(f"YouTube API Key : {e}")
            advance("YouTube")

        # Instagram
        if c_apis.get("meta_access_token") and c_apis.get("instagram_business_id"):
            job["step"] = "Instagram (pagination)…"
            try:
                rows = get_instagram_stats(
                    token=c_apis["meta_access_token"],
                    business_id=c_apis["instagram_business_id"],
                    days=HISTORY_DAYS,
                )
                all_rows += rows
            except Exception as e:
                errors.append(f"Instagram : {e}")
            advance("Instagram")

        # Facebook
        if c_apis.get("meta_access_token") and c_apis.get("facebook_page_id"):
            job["step"] = "Facebook (pagination)…"
            try:
                rows = get_facebook_stats(
                    token=c_apis["meta_access_token"],
                    page_id=c_apis["facebook_page_id"],
                    days=HISTORY_DAYS,
                )
                all_rows += rows
            except Exception as e:
                errors.append(f"Facebook : {e}")
            advance("Facebook")

        # TikTok
        if c_apis.get("tiktok_token"):
            job["step"] = "TikTok…"
            try:
                rows = get_tiktok_stats(c_apis["tiktok_token"], days=HISTORY_DAYS)
                all_rows += rows
            except Exception as e:
                errors.append(f"TikTok : {e}")
            advance("TikTok")

        stored  = upsert_posts(creator, all_rows)
        summary = get_history_summary(creator)

        job.update({
            "status":   "done",
            "progress": 100,
            "step":     "Terminé",
            "fetched":  len(all_rows),
            "stored":   stored,
            "errors":   errors,
            "summary":  summary,
        })
    except Exception as e:
        job.update({"status": "error", "error": str(e)})


@app.route("/api/stats/<creator>/sync-history", methods=["POST"])
@login_required
def sync_history(creator):
    """Lance le sync en background et retourne un job_id immédiatement."""
    if not can_access_creator(creator):
        return jsonify({"error": "Accès interdit"}), 403

    from creator_apis import get_creator_apis

    # Si un job est déjà en cours pour ce créateur → retourne le même
    for jid, job in _sync_jobs.items():
        if job.get("creator") == creator and job.get("status") == "running":
            return jsonify({"job_id": jid, "status": "running", "reused": True})

    job_id = secrets.token_urlsafe(12)
    _sync_jobs[job_id] = {
        "creator":  creator,
        "status":   "running",
        "progress": 0,
        "step":     "Démarrage…",
        "fetched":  0,
        "stored":   0,
        "errors":   [],
        "summary":  {},
    }

    c_apis = get_creator_apis(creator)
    t = threading.Thread(
        target=_run_sync_history,
        args=(job_id, creator, c_apis),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id, "status": "running"}), 202


@app.route("/api/stats/sync-status/<job_id>", methods=["GET"])
@login_required
def sync_status(job_id):
    """Polling : retourne l'état du job de sync."""
    job = _sync_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404
    return jsonify(job)


@app.route("/api/stats/<creator>/history", methods=["GET"])
@login_required
def get_creator_history(creator):
    """Retourne l'historique stocké, avec filtre optionnel by date range."""
    if not can_access_creator(creator):
        return jsonify({"error": "Accès interdit"}), 403

    from history_store import get_history, get_history_summary, get_monthly_breakdown

    days      = int(request.args.get("days", 365))
    from_date = request.args.get("from_date")  # YYYY-MM-DD
    to_date   = request.args.get("to_date")    # YYYY-MM-DD

    # Si from_date/to_date fournis, calcule days depuis from_date
    if from_date and to_date:
        try:
            _from = dt.date.fromisoformat(from_date)
            _to   = dt.date.fromisoformat(to_date)
            days  = (_to - _from).days + 1
        except Exception:
            pass

    rows    = get_history(creator, days=days)
    summary = get_history_summary(creator)
    monthly = get_monthly_breakdown(creator)

    # Filtre par plage de dates si demandé
    if from_date:
        rows = [r for r in rows if (r.get("date") or "") >= from_date]
    if to_date:
        rows = [r for r in rows if (r.get("date") or "") <= to_date]

    # Regroupe par plateforme (même format que /api/stats/<creator>)
    stats_by_platform: dict = {}
    for row in rows:
        plat = row.get("plateforme") or "Autre"
        stats_by_platform.setdefault(plat, []).append(row)

    return jsonify({
        "creator":           creator,
        "history":           rows,
        "stats_by_platform": stats_by_platform,
        "total":             len(rows),
        "summary":           summary,
        "monthly":           monthly,
        "days":              days,
        "from_date":         from_date,
        "to_date":           to_date,
    })


@app.route("/api/admin/export-history", methods=["GET"])
@admin_required
def export_history():
    """
    Exporte tout l'historique en JSON (à coller dans HISTORY_JSON sur Render).
    Format : { "creator1": [...rows], "creator2": [...rows] }
    """
    from history_store import get_history, export_all_json
    creators = get_all_creators()
    result   = {}
    for c in creators:
        result[c] = get_history(c, days=400)

    return jsonify({
        "HISTORY_JSON": result,
        "instructions": (
            "Copie la valeur de HISTORY_JSON dans Render → Environment. "
            "L'historique sera restauré automatiquement au prochain démarrage."
        ),
    })


@app.route("/api/admin/consolidated", methods=["GET"])
@admin_required
def admin_consolidated():
    """
    Vue consolidée : KPIs + score pour tous les créateurs.
    Utilisé par l'admin pour comparer les créateurs d'un coup d'œil.
    """
    from creator_apis import get_creator_apis
    from collectors import (
        get_youtube_stats_oauth_creator, get_youtube_stats_apikey,
        get_instagram_stats, get_facebook_stats, get_tiktok_stats,
    )
    from insights_engine import analyze

    days     = int(request.args.get("days", 7))
    creators = get_all_creators()
    results  = []

    for creator in creators:
        try:
            cache_key = f"{creator}_{days}_c"
            cached = _stats_cache.get(cache_key)
            if cached and (time.time() - cached[0]) < CACHE_TTL:
                data = cached[1]
            else:
                data = None

            if data:
                stats_cur  = data.get("stats", {})
                stats_prev = data.get("prev_stats", {})
            else:
                # Mini-fetch (réutilise le cache si dispo, sinon skip)
                stats_cur = {}; stats_prev = {}

            insight = analyze(stats_cur, stats_prev, days) if stats_cur else {}
            kpis    = insight.get("kpis", {})
            score   = insight.get("score", {})

            results.append({
                "creator":     creator,
                "score":       score.get("score", 0),
                "grade":       score.get("grade", "—"),
                "label":       score.get("label", "—"),
                "total_views": kpis.get("total_views", 0),
                "avg_views":   kpis.get("avg_views", 0),
                "eng_pct":     kpis.get("eng_pct", 0),
                "posts":       kpis.get("posts", 0),
                "followers":   kpis.get("followers", 0),
            })
        except Exception as e:
            results.append({"creator": creator, "error": str(e)[:60]})

    # Tri par score desc
    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    totals = {
        "total_views": sum(r.get("total_views", 0) for r in results),
        "total_posts": sum(r.get("posts", 0) for r in results),
        "avg_score":   round(sum(r.get("score", 0) for r in results) / len(results)) if results else 0,
    }

    return jsonify({"creators": results, "totals": totals, "days": days})


# ──────────────────────────────────────────────────────────────
# HEALTH / FRONT
# ──────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "3.1.0"})


@app.route("/manifest.json")
def manifest():
    return send_file("manifest.json", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    return send_file("sw.js", mimetype="application/javascript")


@app.route("/icon-192.png")
def icon_192():
    return send_file("icon-192.png", mimetype="image/png")


@app.route("/icon-512.png")
def icon_512():
    return send_file("icon-512.png", mimetype="image/png")



@app.route("/tiktokYNyZYXbgRqGTDoE1PzdEm9lnu0YXdXTK.txt")
def tiktok_verify():
    return "tiktok-developers-site-verification=YNyZYXbgRqGTDoE1PzdEm9lnu0YXdXTK", 200, {"Content-Type": "text/plain"}


@app.route("/<path:filename>")
def serve_static_txt(filename):
    """Sert les fichiers de vérification de domaine (TikTok, etc.)."""
    if filename.endswith(".txt") and "/" not in filename:
        import pathlib
        f = pathlib.Path(filename)
        if f.exists():
            return f.read_text(), 200, {"Content-Type": "text/plain"}
        # Fallback TikTok : format "tiktok-developers-site-verification=TOKEN"
        if filename.startswith("tiktok"):
            token = filename[len("tiktok"):-4]  # retire préfixe + .txt
            content = f"tiktok-developers-site-verification={token}"
            return content, 200, {"Content-Type": "text/plain; charset=utf-8"}
    return jsonify({"error": "Not found"}), 404


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
