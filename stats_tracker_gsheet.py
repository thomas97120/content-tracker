"""
╔══════════════════════════════════════════════════════════╗
║       SOCIAL MEDIA STATS TRACKER — Google Sheets         ║
║  Plateformes : YouTube + Instagram + Facebook            ║
║  Premier lancement : crée le Google Sheet complet        ║
║  Lancements suivants : ajoute les nouvelles stats        ║
╚══════════════════════════════════════════════════════════╝

INSTALLATION (une seule fois) :
  pip install google-api-python-client google-auth-oauthlib requests

CONFIGURATION :
  1. Remplis les variables de la section CONFIG ci-dessous
  2. Lance : python stats_tracker_gsheet.py
  3. Accepte les permissions dans le navigateur (une seule fois)
  4. Le script crée ton Google Sheet et y écrit les stats !
"""

import os
import json
import datetime
import requests
from pathlib import Path

# ─────────────────────────────────────────────
#  CONFIG — À REMPLIR UNE SEULE FOIS
# ─────────────────────────────────────────────

# ── Google (YouTube + Sheets) ─────────────────
# Même fichier pour YouTube Analytics ET Google Sheets
# Obtenir sur : https://console.cloud.google.com
# APIs à activer : "YouTube Analytics API" + "YouTube Data API v3" + "Google Sheets API" + "Google Drive API"
GOOGLE_CLIENT_SECRETS_FILE = "client_secrets.json"

# ── Instagram & Facebook ──────────────────────
META_ACCESS_TOKEN    = "COLLE_TON_TOKEN_META_ICI"
INSTAGRAM_BUSINESS_ID = "TON_ID_INSTAGRAM"
FACEBOOK_PAGE_ID      = "TON_ID_PAGE_FB"

# ── Paramètres du Sheet ───────────────────────
SHEET_TITLE   = "📊 Content Strategy Tracker"
DAYS_TO_FETCH = 7

# ── Fichier de config local ───────────────────
# Sauvegarde l'ID du Google Sheet créé pour les prochains lancements
CONFIG_FILE = "tracker_config.json"

# ─────────────────────────────────────────────
#  AUTHENTIFICATION GOOGLE (OAuth 2.0)
# ─────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

def get_google_credentials():
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    import google.auth.transport.requests

    creds = None
    token_file = "google_token.json"

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(google.auth.transport.requests.Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return creds


# ─────────────────────────────────────────────
#  GOOGLE SHEETS — Helpers
# ─────────────────────────────────────────────

def sheets_request(creds, method, path, body=None):
    """Appel générique à l'API Sheets v4."""
    from google.auth.transport.requests import Request as GRequest
    import google.auth.transport.requests

    token = creds.token
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"https://sheets.googleapis.com/v4/spreadsheets{path}"
    resp = getattr(requests, method)(url, headers=headers, json=body)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def drive_request(creds, method, path, body=None, params=None):
    """Appel générique à l'API Drive v3."""
    token = creds.token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"https://www.googleapis.com/drive/v3{path}"
    resp = getattr(requests, method)(url, headers=headers, json=body, params=params)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def col_letter(n):
    """Convertit un index (1-based) en lettre de colonne : 1→A, 26→Z, 27→AA."""
    result = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        result = chr(65 + r) + result
    return result


def rgba(r, g, b, a=1.0):
    return {"red": r/255, "green": g/255, "blue": b/255, "alpha": a}


# ─────────────────────────────────────────────
#  CRÉATION DU GOOGLE SHEET
# ─────────────────────────────────────────────

PLATFORMS = [
    {"name": "Instagram", "emoji": "📸", "color": rgba(225, 48, 108)},
    {"name": "TikTok",    "emoji": "🎵", "color": rgba(30,  30,  30)},
    {"name": "YouTube",   "emoji": "▶️", "color": rgba(204,  0,   0)},
    {"name": "Facebook",  "emoji": "👍", "color": rgba(24,  119, 242)},
    {"name": "Snapchat",  "emoji": "👻", "color": rgba(255, 252,  0)},
]

STAT_HEADERS = [
    "Date", "Titre du contenu", "Format",
    "Vues / Impressions", "Portée (Reach)", "Abonnés (total)", "Δ Abonnés",
    "Likes", "Commentaires", "Partages", "Sauvegardes",
    "Taux engagement (%)", "Score performance", "Notes"
]

DASHBOARD_HEADERS = [
    "Plateforme", "Abonnés totaux", "Vues moy. / post",
    "Taux engagement moy. (%)", "Meilleur format",
    "Meilleur sujet", "Fréquence idéale", "Priorité"
]


def create_google_sheet(creds):
    """Crée le Google Sheet avec tous les onglets et la mise en forme."""
    print("  Création du Google Sheet...")

    # 1. Crée le classeur avec les onglets
    sheets_body = [{"properties": {"title": "🎯 Dashboard", "index": 0}}]
    for p in PLATFORMS:
        sheets_body.append({"properties": {"title": f"{p['emoji']} {p['name']}"}})
    sheets_body.append({"properties": {"title": "📖 Guide"}})

    spreadsheet = sheets_request(creds, "post", "", body={
        "properties": {"title": SHEET_TITLE},
        "sheets": sheets_body
    })

    spreadsheet_id = spreadsheet["spreadsheetId"]
    sheets_info    = {s["properties"]["title"]: s["properties"]["sheetId"]
                      for s in spreadsheet["sheets"]}

    print(f"  Sheet créé : https://docs.google.com/spreadsheets/d/{spreadsheet_id}")

    # 2. Prépare les requêtes de mise en forme (batch)
    requests_batch = []

    # ── Onglets plateformes ──────────────────────────────────
    for p in PLATFORMS:
        sheet_name = f"{p['emoji']} {p['name']}"
        sid        = sheets_info[sheet_name]
        color      = p["color"]

        # Couleur de l'onglet
        requests_batch.append({"updateSheetProperties": {
            "properties": {"sheetId": sid, "tabColor": color},
            "fields": "tabColor"
        }})

        # Fige la ligne 1 (en-têtes)
        requests_batch.append({"updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}},
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"
        }})

        # Largeurs de colonnes
        col_widths = [100, 220, 140, 120, 120, 110, 90, 80, 100, 90, 100, 130, 120, 180]
        for ci, w in enumerate(col_widths):
            requests_batch.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": ci, "endIndex": ci+1},
                "properties": {"pixelSize": w},
                "fields": "pixelSize"
            }})

        # Hauteur ligne d'en-tête
        requests_batch.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 48},
            "fields": "pixelSize"
        }})

        # Mise en forme de la ligne d'en-tête
        requests_batch.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": len(STAT_HEADERS)},
            "cell": {"userEnteredFormat": {
                "backgroundColor": color,
                "textFormat": {"foregroundColor": rgba(255,255,255), "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP"
            }},
            "fields": "userEnteredFormat"
        }})

        # Formatage conditionnel sur le taux d'engagement (colonne L = index 11)
        requests_batch.append({"addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": sid, "startRowIndex": 1, "endRowIndex": 200,
                            "startColumnIndex": 11, "endColumnIndex": 12}],
                "gradientRule": {
                    "minpoint": {"color": rgba(231,76,60),  "type": "NUMBER", "value": "0"},
                    "midpoint": {"color": rgba(241,196,15), "type": "NUMBER", "value": "3"},
                    "maxpoint": {"color": rgba(39,174,96),  "type": "NUMBER", "value": "10"},
                }
            },
            "index": 0
        }})

        # Alternance de couleurs sur les lignes de données
        requests_batch.append({"addBanding": {
            "bandedRange": {
                
                "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 200,
                          "startColumnIndex": 0, "endColumnIndex": len(STAT_HEADERS)},
                "rowProperties": {
                    "headerColor":      rgba(245,245,245),
                    "firstBandColor":   rgba(255,255,255),
                    "secondBandColor":  rgba(248,249,250),
                }
            }
        }})

    # ── Onglet Dashboard ────────────────────────────────────
    dash_sid = sheets_info["🎯 Dashboard"]
    requests_batch.append({"updateSheetProperties": {
        "properties": {"sheetId": dash_sid, "tabColor": rgba(108,52,131)},
        "fields": "tabColor"
    }})
    requests_batch.append({"updateSheetProperties": {
        "properties": {"sheetId": dash_sid, "gridProperties": {"frozenRowCount": 2}},
        "fields": "gridProperties.frozenRowCount"
    }})

    # Envoi du batch de mise en forme
    sheets_request(creds, "post", f"/{spreadsheet_id}:batchUpdate", body={"requests": requests_batch})

    # 3. Écriture des données (en-têtes + formules)
    value_updates = []

    for p in PLATFORMS:
        sheet_name = f"{p['emoji']} {p['name']}"

        # En-têtes
        value_updates.append({
            "range": f"'{sheet_name}'!A1:{col_letter(len(STAT_HEADERS))}1",
            "values": [STAT_HEADERS]
        })

        # Formules pour 100 lignes de données
        formula_rows = []
        for row in range(2, 102):
            # Taux engagement = (Likes+Coms+Partages+Sauvegardes) / Vues * 100
            eng = f"=IF(D{row}>0,(H{row}+I{row}+J{row}+K{row})/D{row}*100,\"\")"
            # Score performance
            score = f"=IF(D{row}>0,ROUND((D{row}*0.3+E{row}*0.2+L{row}*10*0.3+(H{row}+I{row}+J{row})*0.2)/1000,1),\"\")"
            formula_rows.append(["", "", "", "", "", "", "", "", "", "", "", eng, score, ""])

        value_updates.append({
            "range": f"'{sheet_name}'!A2:{col_letter(len(STAT_HEADERS))}101",
            "values": formula_rows
        })

    # Dashboard — Résumé plateformes
    dash_data = [["🎯 CONTENT STRATEGY DASHBOARD"]]
    dash_data.append(DASHBOARD_HEADERS)
    for p in PLATFORMS:
        dash_data.append([f"{p['emoji']} {p['name']}", "", "", "", "", "", "", "🟡 À évaluer"])

    # Dashboard — Matrice de décision
    dash_data.append([])
    dash_data.append(["🧠 MATRICE DE DÉCISION"])
    dash_data.append(["Idée de contenu", "Format", "Plateforme(s)", "Score viral (1-10)",
                      "Effort (1-10)", "ROI estimé", "Décision", "Deadline"])

    matrix_start = len(dash_data) + 1
    for i in range(10):
        row_num = matrix_start + i
        roi_formula   = f"=IF(AND(D{row_num}<>\"\",E{row_num}<>\"\",E{row_num}>0),ROUND(D{row_num}/E{row_num},1),\"\")"
        dec_formula   = (f"=IF(F{row_num}=\"\",\"\","
                         f"IF(F{row_num}>=1.5,\"✅ À produire\","
                         f"IF(F{row_num}>=1,\"🟡 À tester\",\"❌ Passer\")))")
        dash_data.append(["", "", "", "", "", roi_formula, dec_formula, ""])

    value_updates.append({
        "range": "'🎯 Dashboard'!A1",
        "values": dash_data
    })

    # Guide
    guide_data = [
        ["📖 GUIDE D'UTILISATION"],
        [],
        ["🎯 Objectif", "Centraliser tes stats, analyser ce qui performe, décider quoi produire."],
        [],
        ["📋 Étapes", ""],
        ["1️⃣ Renseigne tes stats", "Lance le script Python chaque semaine — il remplit automatiquement."],
        ["2️⃣ Taux d'engagement", "Calculé auto : (Likes+Coms+Partages+Sauvegardes) / Vues × 100"],
        ["3️⃣ Matrice de décision", "Entre tes idées dans le Dashboard → décision calculée automatiquement."],
        ["4️⃣ ROI contenu", "ROI = Score viral ÷ Effort. ≥1.5 → produire | ≥1 → tester | <1 → passer"],
        [],
        ["📊 Benchmarks engagement", ""],
        ["📸 Instagram", "Bon : >3% | Excellent : >6%"],
        ["🎵 TikTok",    "Bon : >5% | Excellent : >10%"],
        ["▶️ YouTube",   "Bon : >2% | Excellent : >5%"],
        ["👍 Facebook",  "Bon : >1% | Excellent : >3%"],
        ["👻 Snapchat",  "Bon : >3% | Excellent : >7%"],
    ]
    value_updates.append({"range": "'📖 Guide'!A1", "values": guide_data})

    # Envoi de toutes les valeurs en une seule requête
    sheets_request(creds, "post", f"/{spreadsheet_id}/values:batchUpdate", body={
        "valueInputOption": "USER_ENTERED",
        "data": value_updates
    })

    print("  Structure et formules créées.")
    return spreadsheet_id


# ─────────────────────────────────────────────
#  COLLECTE DES STATS (identique au script Excel)
# ─────────────────────────────────────────────

def get_youtube_stats(creds):
    try:
        from googleapiclient.discovery import build

        youtube           = build("youtube", "v3", credentials=creds)
        youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)

        channel_resp = youtube.channels().list(part="id,statistics", mine=True).execute()
        channel      = channel_resp["items"][0]
        channel_id   = channel["id"]
        subscribers  = int(channel["statistics"].get("subscriberCount", 0))

        end_date   = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH)

        analytics = youtube_analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics="views,likes,comments,shares",
            dimensions="day"
        ).execute()

        rows    = analytics.get("rows", [])
        results = []
        for row in rows:
            date_str, views, likes, comments, shares = row
            results.append({
                "plateforme":   "YouTube",
                "sheet":        "▶️ YouTube",
                "date":         date_str,
                "titre":        "—",
                "format":       "Video",
                "vues":         int(views),
                "reach":        int(views),
                "abonnes":      subscribers,
                "likes":        int(likes),
                "commentaires": int(comments),
                "partages":     int(shares),
                "sauvegardes":  0,
            })

        print(f"  YouTube : {len(results)} jours ({sum(r['vues'] for r in results)} vues)")
        return results
    except Exception as e:
        print(f"  YouTube ERREUR : {e}")
        return []


def get_instagram_stats():
    try:
        BASE   = "https://graph.facebook.com/v19.0"
        params = {"access_token": META_ACCESS_TOKEN}

        account_resp = requests.get(f"{BASE}/{INSTAGRAM_BUSINESS_ID}",
                                    params={**params, "fields": "followers_count"}).json()
        followers = account_resp.get("followers_count", 0)

        media_resp = requests.get(f"{BASE}/{INSTAGRAM_BUSINESS_ID}/media",
                                  params={**params,
                                          "fields": "id,caption,media_type,timestamp",
                                          "limit": DAYS_TO_FETCH * 3}).json()
        medias = media_resp.get("data", [])

        results = []
        cutoff  = datetime.datetime.now() - datetime.timedelta(days=DAYS_TO_FETCH)

        for media in medias:
            post_date = datetime.datetime.fromisoformat(
                media["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
            if post_date < cutoff:
                continue

            media_type = media.get("media_type", "IMAGE")
            metrics    = "impressions,reach,likes_count,comments_count,saved,shares"
            insights   = requests.get(f"{BASE}/{media['id']}/insights",
                                      params={**params, "metric": metrics}).json()
            stats = {item["name"]: item["values"][0]["value"]
                     for item in insights.get("data", [])}

            results.append({
                "plateforme":   "Instagram",
                "sheet":        "📸 Instagram",
                "date":         post_date.strftime("%Y-%m-%d"),
                "titre":        (media.get("caption", "")[:40] + "…") if media.get("caption") else media_type,
                "format":       media_type,
                "vues":         stats.get("impressions", 0),
                "reach":        stats.get("reach", 0),
                "abonnes":      followers,
                "likes":        stats.get("likes_count", 0),
                "commentaires": stats.get("comments_count", 0),
                "partages":     stats.get("shares", 0),
                "sauvegardes":  stats.get("saved", 0),
            })

        print(f"  Instagram : {len(results)} posts")
        return results
    except Exception as e:
        print(f"  Instagram ERREUR : {e}")
        return []


def get_facebook_stats():
    try:
        BASE   = "https://graph.facebook.com/v19.0"
        params = {"access_token": META_ACCESS_TOKEN}

        page_resp = requests.get(f"{BASE}/{FACEBOOK_PAGE_ID}",
                                 params={**params, "fields": "fan_count"}).json()
        fans = page_resp.get("fan_count", 0)

        posts_resp = requests.get(f"{BASE}/{FACEBOOK_PAGE_ID}/posts",
                                  params={**params,
                                          "fields": "id,message,created_time",
                                          "limit": DAYS_TO_FETCH * 3}).json()
        posts  = posts_resp.get("data", [])
        cutoff = datetime.datetime.now() - datetime.timedelta(days=DAYS_TO_FETCH)

        results = []
        for post in posts:
            post_date = datetime.datetime.fromisoformat(
                post["created_time"].replace("+0000", "+00:00")).replace(tzinfo=None)
            if post_date < cutoff:
                continue

            post_id  = post["id"]
            insights = requests.get(f"{BASE}/{post_id}/insights",
                                    params={**params,
                                            "metric": "post_impressions,post_reach"}).json()
            stats    = {item["name"]: item["values"][0]["value"]
                        for item in insights.get("data", [])}

            eng_resp = requests.get(f"{BASE}/{post_id}",
                                    params={**params,
                                            "fields": "reactions.summary(true),comments.summary(true),shares"}).json()
            likes    = eng_resp.get("reactions", {}).get("summary", {}).get("total_count", 0)
            comments = eng_resp.get("comments",  {}).get("summary", {}).get("total_count", 0)
            shares   = eng_resp.get("shares",    {}).get("count", 0)

            results.append({
                "plateforme":   "Facebook",
                "sheet":        "👍 Facebook",
                "date":         post_date.strftime("%Y-%m-%d"),
                "titre":        (post.get("message", "")[:40] + "…") if post.get("message") else "Post",
                "format":       "Post",
                "vues":         stats.get("post_impressions", 0),
                "reach":        stats.get("post_reach", 0),
                "abonnes":      fans,
                "likes":        likes,
                "commentaires": comments,
                "partages":     shares,
                "sauvegardes":  0,
            })

        print(f"  Facebook : {len(results)} posts")
        return results
    except Exception as e:
        print(f"  Facebook ERREUR : {e}")
        return []


# ─────────────────────────────────────────────
#  ÉCRITURE DANS GOOGLE SHEETS
# ─────────────────────────────────────────────

def get_next_empty_row(creds, spreadsheet_id, sheet_name):
    """Trouve la première ligne vide dans un onglet."""
    result = sheets_request(creds, "get",
        f"/{spreadsheet_id}/values/'{sheet_name}'!A:A")
    values = result.get("values", [])
    return len(values) + 1  # +1 car 1-indexed


def write_to_sheets(creds, spreadsheet_id, all_stats):
    """Groupe les stats par onglet et les écrit en batch."""
    from collections import defaultdict
    grouped = defaultdict(list)
    for stat in all_stats:
        grouped[stat["sheet"]].append(stat)

    updates = []
    for sheet_name, stats in grouped.items():
        next_row = get_next_empty_row(creds, spreadsheet_id, sheet_name)

        rows = []
        for s in stats:
            rows.append([
                s.get("date", ""),
                s.get("titre", "—"),
                s.get("format", "—"),
                s.get("vues", 0),
                s.get("reach", 0),
                s.get("abonnes", 0),
                "",                    # Δ abonnés — manuel
                s.get("likes", 0),
                s.get("commentaires", 0),
                s.get("partages", 0),
                s.get("sauvegardes", 0),
                # Colonnes L et M : formules déjà présentes dans le sheet
            ])

        end_row = next_row + len(rows) - 1
        updates.append({
            "range": f"'{sheet_name}'!A{next_row}:K{end_row}",
            "values": rows
        })

    if updates:
        sheets_request(creds, "post", f"/{spreadsheet_id}/values:batchUpdate", body={
            "valueInputOption": "USER_ENTERED",
            "data": updates
        })

    total = sum(len(v) for v in grouped.values())
    print(f"  Lignes ajoutées : {total}")


# ─────────────────────────────────────────────
#  GESTION DE LA CONFIG LOCALE
# ─────────────────────────────────────────────

def load_config():
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─────────────────────────────────────────────
#  POINT D'ENTRÉE
# ─────────────────────────────────────────────

def main():
    print("=" * 56)
    print("  SOCIAL STATS TRACKER — Google Sheets")
    print(f"  Période : {DAYS_TO_FETCH} derniers jours")
    print("=" * 56)

    # Authentification Google (ouvre le navigateur la 1ère fois)
    print("\nAuthentification Google...")
    creds = get_google_credentials()
    print("  OK")

    # Charge ou crée le Google Sheet
    config         = load_config()
    spreadsheet_id = config.get("spreadsheet_id")

    if not spreadsheet_id:
        print("\nPremier lancement — création du Google Sheet...")
        spreadsheet_id = create_google_sheet(creds)
        save_config({"spreadsheet_id": spreadsheet_id})
        print(f"\n  Lien de ton sheet :")
        print(f"  https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
    else:
        print(f"\nSheet existant chargé.")
        print(f"  https://docs.google.com/spreadsheets/d/{spreadsheet_id}")

    # Collecte des stats
    print("\n[1/3] YouTube...")
    all_stats = get_youtube_stats(creds)

    print("\n[2/3] Instagram...")
    all_stats += get_instagram_stats()

    print("\n[3/3] Facebook...")
    all_stats += get_facebook_stats()

    print(f"\nTotal collecté : {len(all_stats)} lignes")

    # Écriture dans Sheets
    if all_stats:
        print("\nÉcriture dans Google Sheets...")
        write_to_sheets(creds, spreadsheet_id, all_stats)

    print("\nTerminé !")
    print(f"Ouvre ton sheet : https://docs.google.com/spreadsheets/d/{spreadsheet_id}")


if __name__ == "__main__":
    main()


# ═══════════════════════════════════════════════════════════
#  README — Setup complet en 10 minutes
# ═══════════════════════════════════════════════════════════
#
# ── ÉTAPE 1 : Google Cloud Console ──────────────────────────
# 1. Va sur https://console.cloud.google.com
# 2. Crée un projet (bouton en haut à gauche)
# 3. Va dans "APIs et services" → "Bibliothèque"
# 4. Active ces 4 APIs :
#      - YouTube Data API v3
#      - YouTube Analytics API
#      - Google Sheets API
#      - Google Drive API
# 5. Va dans "APIs et services" → "Identifiants"
# 6. Clique "Créer des identifiants" → "ID client OAuth 2.0"
# 7. Type d'application : "Application de bureau"
# 8. Télécharge le JSON → renomme-le "client_secrets.json"
# 9. Place "client_secrets.json" dans le même dossier que ce script
#
# ── ÉTAPE 2 : Écran de consentement OAuth ───────────────────
# Si tu vois une erreur "app non vérifiée" au premier lancement :
# 1. Va dans "APIs et services" → "Écran de consentement OAuth"
# 2. Type : Externe
# 3. Ajoute ton adresse email en "utilisateur test"
# 4. Relance le script → clique "Continuer quand même"
#
# ── ÉTAPE 3 : Token Meta (Instagram + Facebook) ─────────────
# 1. Va sur https://developers.facebook.com/tools/explorer
# 2. Sélectionne ton app (ou crée-en une de type "Business")
# 3. Clique "Générer un token d'accès"
# 4. Coche ces permissions :
#      instagram_basic, instagram_manage_insights
#      pages_read_engagement, pages_show_list, read_insights
# 5. Copie le token → colle dans META_ACCESS_TOKEN
#
# ── TROUVER TES IDs ─────────────────────────────────────────
# Dans un navigateur, colle cette URL (remplace TON_TOKEN) :
#   https://graph.facebook.com/me/accounts?access_token=TON_TOKEN
# → Tu vois tes pages Facebook avec leur "id"
# → Clique sur une page → cherche "instagram_business_account"
#
# ── AUTOMATISER (optionnel) ──────────────────────────────────
# Sur Mac/Linux, lance le script automatiquement chaque lundi :
#   crontab -e
#   0 9 * * 1 cd /chemin/vers/script && python stats_tracker_gsheet.py
#
# Sur Windows, utilise le "Planificateur de tâches" Windows.
# ═══════════════════════════════════════════════════════════
