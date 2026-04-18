"""
collectors.py — Collecte des stats depuis les APIs sociales
Même logique que stats_tracker_gsheet.py, adapté pour Flask.
"""

import os
import datetime
import requests

DAYS_TO_FETCH         = int(os.environ.get("DAYS_TO_FETCH", 7))
META_ACCESS_TOKEN     = os.environ.get("META_ACCESS_TOKEN", "")
INSTAGRAM_BUSINESS_ID = os.environ.get("INSTAGRAM_BUSINESS_ID", "")
FACEBOOK_PAGE_ID      = os.environ.get("FACEBOOK_PAGE_ID", "")


# ─────────────────────────────────────────────
#  YOUTUBE — OAuth (admin global)
# ─────────────────────────────────────────────

def get_youtube_stats(creds):
    """Laisse les erreurs remonter pour diagnostic."""
    from googleapiclient.discovery import build

    youtube           = build("youtube", "v3", credentials=creds)
    youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)

    channel_resp = youtube.channels().list(part="id,statistics", mine=True).execute()
    items = channel_resp.get("items", [])
    if not items:
        raise ValueError("Aucune chaîne YouTube trouvée pour ce compte Google")

    channel     = items[0]
    channel_id  = channel["id"]
    subscribers = int(channel["statistics"].get("subscriberCount", 0))

    end_date   = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=DAYS_TO_FETCH)

    analytics = youtube_analytics.reports().query(
        ids=f"channel=={channel_id}",
        startDate=str(start_date),
        endDate=str(end_date),
        metrics="views,likes,comments,shares",
        dimensions="day"
    ).execute()

    results = []
    for row in analytics.get("rows", []):
        date_str, views, likes, comments, shares = row
        results.append({
            "plateforme":   "YouTube",
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

    return results


# ─────────────────────────────────────────────
#  YOUTUBE — OAuth token stocké par créateur
# ─────────────────────────────────────────────

def get_youtube_stats_oauth_creator(token_json: str):
    """YouTube via token OAuth stocké par créateur. Laisse les erreurs remonter."""
    import json as _json
    from google.oauth2.credentials import Credentials
    import google.auth.transport.requests as _greq

    if not token_json or token_json.startswith("enc:"):
        raise ValueError("Token chiffré non déchiffré — ENCRYPTION_KEY manquante ou incorrecte sur Render")

    data  = _json.loads(token_json)
    creds = Credentials(
        token         = data.get("token"),
        refresh_token = data.get("refresh_token"),
        token_uri     = data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id     = data.get("client_id"),
        client_secret = data.get("client_secret"),
        scopes        = data.get("scopes"),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(_greq.Request())

    return get_youtube_stats(creds)


# ─────────────────────────────────────────────
#  YOUTUBE — API Key simple (par créateur)
# ─────────────────────────────────────────────

def get_youtube_stats_apikey(api_key=None, channel_id=None):
    """
    Stats YouTube via Data API v3 avec une simple clé API.
    Pas besoin d'OAuth — accès aux données publiques de la chaîne.
    Obtenir une clé : console.cloud.google.com → YouTube Data API v3.
    """
    if not api_key or not channel_id:
        print("YouTube API Key : youtube_api_key ou youtube_channel_id manquant")
        return []
    try:
        BASE   = "https://www.googleapis.com/youtube/v3"
        params = {"key": api_key}

        # Abonnés
        ch_resp = requests.get(f"{BASE}/channels", params={
            **params, "id": channel_id, "part": "statistics"
        }).json()
        if not ch_resp.get("items"):
            print(f"YouTube API Key : channel '{channel_id}' introuvable")
            return []
        ch_stats    = ch_resp["items"][0]["statistics"]
        subscribers = int(ch_stats.get("subscriberCount", 0))

        # Dernières vidéos (IDs)
        search_resp = requests.get(f"{BASE}/search", params={
            **params, "channelId": channel_id, "part": "id",
            "type": "video", "order": "date",
            "maxResults": min(DAYS_TO_FETCH * 2, 50)
        }).json()
        video_ids = [
            item["id"]["videoId"]
            for item in search_resp.get("items", [])
            if item.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return []

        # Stats détaillées des vidéos
        vids_resp = requests.get(f"{BASE}/videos", params={
            **params,
            "id":   ",".join(video_ids),
            "part": "statistics,snippet"
        }).json()

        cutoff  = datetime.date.today() - datetime.timedelta(days=DAYS_TO_FETCH)
        results = []

        for item in vids_resp.get("items", []):
            pub_date = item["snippet"]["publishedAt"][:10]
            if pub_date < str(cutoff):
                continue
            s = item["statistics"]
            results.append({
                "plateforme":   "YouTube",
                "date":         pub_date,
                "titre":        item["snippet"]["title"][:40],
                "format":       "Video",
                "vues":         int(s.get("viewCount",    0)),
                "reach":        int(s.get("viewCount",    0)),
                "abonnes":      subscribers,
                "likes":        int(s.get("likeCount",    0)),
                "commentaires": int(s.get("commentCount", 0)),
                "partages":     0,
                "sauvegardes":  0,
            })

        return results

    except Exception as e:
        print(f"YouTube API Key ERREUR : {e}")
        return []


# ─────────────────────────────────────────────
#  INSTAGRAM
# ─────────────────────────────────────────────

def get_instagram_stats(token=None, business_id=None):
    token       = token       or META_ACCESS_TOKEN
    business_id = business_id or INSTAGRAM_BUSINESS_ID
    if not token or not business_id:
        print("Instagram : META_ACCESS_TOKEN ou INSTAGRAM_BUSINESS_ID manquant")
        return []
    try:
        BASE   = "https://graph.facebook.com/v19.0"
        params = {"access_token": token}

        account_resp = requests.get(
            f"{BASE}/{business_id}",
            params={**params, "fields": "followers_count"}
        ).json()
        followers = account_resp.get("followers_count", 0)

        media_resp = requests.get(
            f"{BASE}/{business_id}/media",
            params={**params, "fields": "id,caption,media_type,timestamp", "limit": DAYS_TO_FETCH * 3}
        ).json()

        results = []
        cutoff  = datetime.datetime.now() - datetime.timedelta(days=DAYS_TO_FETCH)

        for media in media_resp.get("data", []):
            post_date = datetime.datetime.fromisoformat(
                media["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
            if post_date < cutoff:
                continue

            media_type = media.get("media_type", "IMAGE")
            insights   = requests.get(
                f"{BASE}/{media['id']}/insights",
                params={**params, "metric": "impressions,reach,likes_count,comments_count,saved,shares"}
            ).json()
            stats = {item["name"]: item["values"][0]["value"]
                     for item in insights.get("data", [])}

            results.append({
                "plateforme":   "Instagram",
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

        return results

    except Exception as e:
        print(f"Instagram ERREUR : {e}")
        return []


# ─────────────────────────────────────────────
#  FACEBOOK
# ─────────────────────────────────────────────

def get_facebook_stats(token=None, page_id=None):
    token   = token   or META_ACCESS_TOKEN
    page_id = page_id or FACEBOOK_PAGE_ID
    if not token or not page_id:
        print("Facebook : META_ACCESS_TOKEN ou FACEBOOK_PAGE_ID manquant")
        return []
    try:
        BASE   = "https://graph.facebook.com/v19.0"
        params = {"access_token": token}

        page_resp = requests.get(
            f"{BASE}/{page_id}",
            params={**params, "fields": "fan_count"}
        ).json()
        fans = page_resp.get("fan_count", 0)

        posts_resp = requests.get(
            f"{BASE}/{page_id}/posts",
            params={**params, "fields": "id,message,created_time", "limit": DAYS_TO_FETCH * 3}
        ).json()

        results = []
        cutoff  = datetime.datetime.now() - datetime.timedelta(days=DAYS_TO_FETCH)

        for post in posts_resp.get("data", []):
            post_date = datetime.datetime.fromisoformat(
                post["created_time"].replace("+0000", "+00:00")).replace(tzinfo=None)
            if post_date < cutoff:
                continue

            post_id  = post["id"]
            insights = requests.get(
                f"{BASE}/{post_id}/insights",
                params={**params, "metric": "post_impressions,post_reach"}
            ).json()
            stats    = {item["name"]: item["values"][0]["value"]
                        for item in insights.get("data", [])}

            eng_resp = requests.get(
                f"{BASE}/{post_id}",
                params={**params, "fields": "reactions.summary(true),comments.summary(true),shares"}
            ).json()

            results.append({
                "plateforme":   "Facebook",
                "date":         post_date.strftime("%Y-%m-%d"),
                "titre":        (post.get("message", "")[:40] + "…") if post.get("message") else "Post",
                "format":       "Post",
                "vues":         stats.get("post_impressions", 0),
                "reach":        stats.get("post_reach", 0),
                "abonnes":      fans,
                "likes":        eng_resp.get("reactions", {}).get("summary", {}).get("total_count", 0),
                "commentaires": eng_resp.get("comments",  {}).get("summary", {}).get("total_count", 0),
                "partages":     eng_resp.get("shares",    {}).get("count", 0),
                "sauvegardes":  0,
            })

        return results

    except Exception as e:
        print(f"Facebook ERREUR : {e}")
        return []
