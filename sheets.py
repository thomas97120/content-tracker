"""
sheets.py — Connexion et lecture/écriture Google Sheets
"""

import os
import json
import datetime
from pathlib import Path
import requests as http

# ─── Config ──────────────────────────────────────────────────
CONFIG_FILE = "tracker_config.json"
SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

PLATFORM_SHEETS = {
    "YouTube":   "▶️ YouTube",
    "Instagram": "📸 Instagram",
    "Facebook":  "👍 Facebook",
    "TikTok":    "🎵 TikTok",
    "Snapchat":  "👻 Snapchat",
}

# Colonnes du sheet (ordre identique à l'Excel/GSheet créé précédemment)
COL_DATE         = 0
COL_TITRE        = 1
COL_FORMAT       = 2
COL_VUES         = 3
COL_REACH        = 4
COL_ABONNES      = 5
COL_DELTA_AB     = 6
COL_LIKES        = 7
COL_COMMENTAIRES = 8
COL_PARTAGES     = 9
COL_SAUVEGARDES  = 10
# Col 11 = taux engagement (formule auto)
# Col 12 = score (formule auto)
COL_NOTES        = 13
COL_CREATOR      = 14


# ─── Auth ────────────────────────────────────────────────────

def get_google_creds():
    """Retourne les credentials Google (depuis token sauvegardé ou env var)."""
    from google.oauth2.credentials import Credentials
    import google.auth.transport.requests

    token_file = "google_token.json"

    # En production (Render/Railway), le token est dans une variable d'env
    token_env = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_env:
        token_data = json.loads(token_env)
        with open(token_file, "w") as f:
            json.dump(token_data, f)

    if not Path(token_file).exists():
        raise RuntimeError(
            "google_token.json introuvable. "
            "Lance d'abord stats_tracker_gsheet.py pour créer le token."
        )

    creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(google.auth.transport.requests.Request())
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return creds


def get_spreadsheet_id():
    """Lit l'ID du Google Sheet depuis tracker_config.json ou variable d'env."""
    sheet_id = os.environ.get("SPREADSHEET_ID")
    if sheet_id:
        return sheet_id

    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE) as f:
            return json.load(f).get("spreadsheet_id")

    raise RuntimeError(
        "SPREADSHEET_ID introuvable. "
        "Lance d'abord stats_tracker_gsheet.py pour créer le sheet."
    )


# ─── Helpers API Sheets ───────────────────────────────────────

def _sheets(creds, method, path, body=None, params=None):
    token   = creds.token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url     = f"https://sheets.googleapis.com/v4/spreadsheets{path}"
    resp    = getattr(http, method)(url, headers=headers, json=body, params=params)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _get_range(creds, sheet_id, range_str):
    result = _sheets(creds, "get", f"/{sheet_id}/values/{range_str}")
    return result.get("values", [])


def _append_rows(creds, sheet_id, sheet_name, rows):
    range_str = f"'{sheet_name}'!A:O"
    _sheets(creds, "post", f"/{sheet_id}/values/{range_str}:append",
            body={"values": rows},
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"})


# ─── Lecture des stats ────────────────────────────────────────

def get_creator_stats(creator_name: str) -> dict:
    """
    Retourne les stats d'un créateur par plateforme.
    Pour l'instant, toutes les données sont dans le même sheet.
    Si tu veux isoler par créateur → ajoute une colonne 'Créateur'
    dans le sheet et filtre ici.
    """
    try:
        creds    = get_google_creds()
        sheet_id = get_spreadsheet_id()
        result   = {}

        for platform, sheet_name in PLATFORM_SHEETS.items():
            rows = _get_range(creds, sheet_id, f"'{sheet_name}'!A2:N200")
            stats = []
            for row in rows:
                if len(row) < 4 or not row[COL_DATE]:
                    continue
                # Filtre par créateur si la colonne existe
                row_creator = row[COL_CREATOR] if len(row) > COL_CREATOR else ""
                if row_creator and row_creator != creator_name:
                    continue
                stats.append({
                    "date":         row[COL_DATE]         if len(row) > COL_DATE         else "",
                    "titre":        row[COL_TITRE]        if len(row) > COL_TITRE        else "",
                    "format":       row[COL_FORMAT]       if len(row) > COL_FORMAT       else "",
                    "vues":         _int(row, COL_VUES),
                    "reach":        _int(row, COL_REACH),
                    "abonnes":      _int(row, COL_ABONNES),
                    "likes":        _int(row, COL_LIKES),
                    "commentaires": _int(row, COL_COMMENTAIRES),
                    "partages":     _int(row, COL_PARTAGES),
                    "sauvegardes":  _int(row, COL_SAUVEGARDES),
                    "taux_eng":     _float(row, 11),
                    "score":        _float(row, 12),
                })
            result[platform] = stats

        return result

    except Exception as e:
        print(f"get_creator_stats ERREUR : {e}")
        # Retourne dict vide (Sheets pas configuré ou hors ligne)
        return {p: [] for p in PLATFORM_SHEETS}


def get_all_creators() -> list:
    """Retourne la liste des créateurs (colonne Créateur si elle existe)."""
    # Version simple : retourne une liste statique depuis env var
    creators_env = os.environ.get("CREATORS", "")
    if creators_env:
        return [c.strip() for c in creators_env.split(",")]
    return ["créateur_1"]


def get_dashboard_data() -> dict:
    """Retourne les données agrégées pour la vue admin."""
    try:
        creds    = get_google_creds()
        sheet_id = get_spreadsheet_id()
        summary  = {}

        for platform, sheet_name in PLATFORM_SHEETS.items():
            rows = _get_range(creds, sheet_id, f"'{sheet_name}'!A2:N200")
            vues_list = [_int(r, COL_VUES)    for r in rows if len(r) > COL_VUES and r[COL_DATE]]
            eng_list  = [_float(r, 11)         for r in rows if len(r) > 11       and r[COL_DATE]]
            ab_list   = [_int(r, COL_ABONNES)  for r in rows if len(r) > COL_ABONNES and r[COL_DATE]]

            summary[platform] = {
                "posts":        len(vues_list),
                "vues_moy":     int(sum(vues_list) / len(vues_list)) if vues_list else 0,
                "engagement_moy": round(sum(eng_list)  / len(eng_list),  2) if eng_list  else 0,
                "abonnes":      ab_list[-1] if ab_list else 0,
            }

        return {"platforms": summary, "updated_at": datetime.datetime.now().isoformat()}

    except Exception as e:
        print(f"get_dashboard_data ERREUR : {e}")
        return {"platforms": {}, "updated_at": datetime.datetime.now().isoformat()}


# ─── Écriture des stats ───────────────────────────────────────

def write_stats_to_sheet(creds, sheet_id, all_stats, creator_name=None):
    """Écrit une liste de stats dans les bons onglets."""
    from collections import defaultdict
    grouped = defaultdict(list)
    for s in all_stats:
        sheet_name = PLATFORM_SHEETS.get(s["plateforme"])
        if sheet_name:
            grouped[sheet_name].append(s)

    for sheet_name, stats in grouped.items():
        rows = []
        for s in stats:
            rows.append([
                s.get("date", ""),
                s.get("titre", "—"),
                s.get("format", "—"),
                s.get("vues", 0),
                s.get("reach", 0),
                s.get("abonnes", 0),
                "",
                s.get("likes", 0),
                s.get("commentaires", 0),
                s.get("partages", 0),
                s.get("sauvegardes", 0),
                "",   # col 11 — taux engagement (formule)
                "",   # col 12 — score (formule)
                "",   # col 13 — notes
                creator_name or "",  # col 14 — créateur
            ])
        _append_rows(creds, sheet_id, sheet_name, rows)


def add_manual_stats(data: dict) -> bool:
    """Ajoute une ligne de stats saisie manuellement (TikTok, Snapchat)."""
    try:
        creds      = get_google_creds()
        sheet_id   = get_spreadsheet_id()
        platform   = data.get("platform", "TikTok")
        sheet_name = PLATFORM_SHEETS.get(platform, "🎵 TikTok")

        row = [
            data.get("date", str(datetime.date.today())),
            data.get("titre", "—"),
            data.get("format", "—"),
            data.get("views",    0),
            data.get("reach",    0),
            data.get("followers",0),
            "",
            data.get("likes",    0),
            data.get("comments", 0),
            data.get("shares",   0),
            data.get("saves",    0),
        ]
        _append_rows(creds, sheet_id, sheet_name, [row])
        return True
    except Exception as e:
        print(f"Erreur add_manual_stats : {e}")
        return False


def save_content_decision(data: dict):
    """Sauvegarde une décision swipe dans l'onglet Dashboard."""
    try:
        creds    = get_google_creds()
        sheet_id = get_spreadsheet_id()
        row = [
            data.get("idea", ""),
            data.get("format", ""),
            data.get("platforms", ""),
            data.get("viral_score", ""),
            data.get("effort", ""),
            "",   # ROI calculé par formule
            data.get("decision", ""),
            data.get("deadline", ""),
        ]
        # Ajoute dans la section Matrice du Dashboard
        _sheets(creds, "post",
                f"/{sheet_id}/values/'🎯 Dashboard'!A13:H13:append",
                body={"values": [row]},
                params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"})
    except Exception as e:
        print(f"Erreur save_content_decision : {e}")


# ─── Utils ───────────────────────────────────────────────────

def _int(row, idx):
    try:
        return int(float(str(row[idx]).replace(",", "."))) if len(row) > idx and row[idx] else 0
    except:
        return 0

def _float(row, idx):
    try:
        return float(str(row[idx]).replace(",", ".")) if len(row) > idx and row[idx] else 0.0
    except:
        return 0.0
