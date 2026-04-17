"""
app.py — Serveur principal Flask
Démarre avec : python app.py
"""

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import os
from collectors import get_youtube_stats, get_instagram_stats, get_facebook_stats
from sheets import (
    get_all_creators, get_creator_stats, add_manual_stats,
    get_dashboard_data, save_content_decision
)

app = Flask(__name__)
CORS(app)  # Autorise l'app mobile à parler au serveur

# ─── Clé secrète simple (change cette valeur) ────────────────
ADMIN_KEY   = os.environ.get("ADMIN_KEY",   "admin-secret-123")
CREATOR_KEY = os.environ.get("CREATOR_KEY", "creator-secret-456")


# ─── Auth helper ─────────────────────────────────────────────
def check_auth(role="creator"):
    key = request.headers.get("X-API-Key", "")
    if role == "admin":
        return key == ADMIN_KEY
    return key in (ADMIN_KEY, CREATOR_KEY)

def creator_name_from_key(key):
    """Retourne le nom du créateur depuis son token (format: creator-NOM-xxx)."""
    parts = key.split("-")
    return parts[1] if len(parts) >= 2 else "inconnu"


# ═══════════════════════════════════════════════════════════════
#  ROUTES CRÉATEUR
# ═══════════════════════════════════════════════════════════════

@app.route("/api/stats/<creator>", methods=["GET"])
def get_stats(creator):
    """Retourne les stats d'un créateur spécifique."""
    if not check_auth():
        return jsonify({"error": "Non autorisé"}), 401

    stats = get_creator_stats(creator)
    return jsonify({"creator": creator, "stats": stats})


@app.route("/api/stats/manual", methods=["POST"])
def add_stats():
    """Saisie manuelle de stats (TikTok, Snapchat)."""
    if not check_auth():
        return jsonify({"error": "Non autorisé"}), 401

    data = request.json
    required = ["creator", "platform", "date", "views", "likes"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Champs requis : {required}"}), 400

    success = add_manual_stats(data)
    return jsonify({"success": success})


@app.route("/api/ideas/swipe", methods=["POST"])
def swipe_idea():
    """Valide ou rejette une idée de contenu (swipe)."""
    if not check_auth():
        return jsonify({"error": "Non autorisé"}), 401

    data = request.json
    # decision = "approve" | "reject" | "later"
    if not all(k in data for k in ["idea", "decision", "creator"]):
        return jsonify({"error": "Champs requis : idea, decision, creator"}), 400

    save_content_decision(data)
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════
#  ROUTES ADMIN
# ═══════════════════════════════════════════════════════════════

@app.route("/api/admin/creators", methods=["GET"])
def list_creators():
    """Liste tous les créateurs (admin seulement)."""
    if not check_auth("admin"):
        return jsonify({"error": "Admin requis"}), 403

    creators = get_all_creators()
    return jsonify({"creators": creators})


@app.route("/api/admin/dashboard", methods=["GET"])
def dashboard():
    """Vue globale de tous les créateurs (admin seulement)."""
    if not check_auth("admin"):
        return jsonify({"error": "Admin requis"}), 403

    data = get_dashboard_data()
    return jsonify(data)


@app.route("/api/admin/sync", methods=["POST"])
def sync_all():
    """Déclenche la collecte des stats via APIs (admin seulement)."""
    if not check_auth("admin"):
        return jsonify({"error": "Admin requis"}), 403

    body    = request.json or {}
    creator = body.get("creator", "all")

    results = {}
    try:
        from sheets import get_google_creds, write_stats_to_sheet, get_spreadsheet_id
        creds  = get_google_creds()
        sheet_id = get_spreadsheet_id()

        yt_stats = get_youtube_stats(creds)
        ig_stats = get_instagram_stats()
        fb_stats = get_facebook_stats()

        all_stats = yt_stats + ig_stats + fb_stats
        write_stats_to_sheet(creds, sheet_id, all_stats)

        results = {
            "youtube":   len(yt_stats),
            "instagram": len(ig_stats),
            "facebook":  len(fb_stats),
            "total":     len(all_stats)
        }
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"synced": results})


# ═══════════════════════════════════════════════════════════════
#  SANTÉ DU SERVEUR
# ═══════════════════════════════════════════════════════════════

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.0.0"})

@app.route("/", methods=["GET"])
def serve_index():
    return send_file("index.html")
    
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
