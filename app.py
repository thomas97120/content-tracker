"""
app.py — version 2.5 sécurisée
Démarre avec : python app.py
"""

from flask import Flask, jsonify, request, send_file, session
from flask_cors import CORS
from functools import wraps
from werkzeug.security import check_password_hash
import json
import os

from collectors import get_youtube_stats, get_instagram_stats, get_facebook_stats
from sheets import (
    get_all_creators, get_creator_stats, add_manual_stats,
    get_dashboard_data, save_content_decision
)

app = Flask(__name__)

# IMPORTANT : remplace cette valeur sur Render
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-render")

# Très important pour que le front déployé puisse envoyer les cookies de session
CORS(app, supports_credentials=True)


# ──────────────────────────────────────────────────────────────
# USERS
# ──────────────────────────────────────────────────────────────
USERS_FILE = "users.json"


def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def find_user_by_email(email):
    users = load_users()
    return next((u for u in users if u["email"].lower() == email.lower()), None)


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
# AUTH
# ──────────────────────────────────────────────────────────────
@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis"}), 400

    user = find_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Identifiants invalides"}), 401

    session["user_email"] = user["email"]

    return jsonify({
        "success": True,
        "user": {
            "email": user["email"],
            "role": user["role"],
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
        "email": user["email"],
        "role": user["role"],
        "creator_name": user.get("creator_name")
    })


# ──────────────────────────────────────────────────────────────
# ROUTES CRÉATEUR
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
    results = {}
    try:
        from sheets import get_google_creds, write_stats_to_sheet, get_spreadsheet_id
        creds = get_google_creds()
        sheet_id = get_spreadsheet_id()

        yt_stats = get_youtube_stats(creds)
        ig_stats = get_instagram_stats()
        fb_stats = get_facebook_stats()

        all_stats = yt_stats + ig_stats + fb_stats
        write_stats_to_sheet(creds, sheet_id, all_stats)

        results = {
            "youtube": len(yt_stats),
            "instagram": len(ig_stats),
            "facebook": len(fb_stats),
            "total": len(all_stats)
        }
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"synced": results})


# ──────────────────────────────────────────────────────────────
# HEALTH / FRONT
# ──────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "2.5.0"})


@app.route("/", methods=["GET"])
def serve_index():
    return send_file("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
