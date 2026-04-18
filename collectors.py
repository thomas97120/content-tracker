"""
collectors.py — Collecte des stats depuis les APIs sociales
Même logique que stats_tracker_gsheet.py, adapté pour Flask.
"""

import os
import re
import datetime
import requests


def _yt_format(item):
    """Détecte Short via durée ISO 8601 < 61s OU #shorts dans le titre."""
    title = item.get("snippet", {}).get("title", "").lower()
    if "#shorts" in title or "#short" in title:
        return "Short"
    dur = item.get("contentDetails", {}).get("duration", "")
    if dur:
        # PT1M30S → 90s, PT45S → 45s
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
        if m:
            h, mn, s = (int(x or 0) for x in m.groups())
            total = h * 3600 + mn * 60 + s
            if total <= 60:
                return "Short"
    return "Video"

DAYS_TO_FETCH         = int(os.environ.get("DAYS_TO_FETCH", 7))
META_ACCESS_TOKEN     = os.environ.get("META_ACCESS_TOKEN", "")
INSTAGRAM_BUSINESS_ID = os.environ.get("INSTAGRAM_BUSINESS_ID", "")
FACEBOOK_PAGE_ID      = os.environ.get("FACEBOOK_PAGE_ID", "")


# ─────────────────────────────────────────────
#  YOUTUBE — OAuth (admin global)
# ─────────────────────────────────────────────

def get_youtube_stats(creds, days=None):
    """
    Stats par vidéo (Data API v3) via OAuth.
    Même résultat que YouTube Studio — titres + stats individuelles.
    """
    from googleapiclient.discovery import build

    _days = days or DAYS_TO_FETCH

    youtube = build("youtube", "v3", credentials=creds)

    # 1. Chaîne
    channel_resp = youtube.channels().list(part="id,statistics,snippet", mine=True).execute()
    items = channel_resp.get("items", [])
    if not items:
        raise ValueError("Aucune chaîne YouTube trouvée pour ce compte Google")

    channel      = items[0]
    channel_id   = channel["id"]
    channel_name = channel.get("snippet", {}).get("title", "")
    subscribers  = int(channel["statistics"].get("subscriberCount", 0))

    # 2. Vidéos récentes
    search_resp = youtube.search().list(
        channelId=channel_id,
        part="id",
        type="video",
        order="date",
        maxResults=min(_days * 3, 50)
    ).execute()

    video_ids = [
        item["id"]["videoId"]
        for item in search_resp.get("items", [])
        if item.get("id", {}).get("videoId")
    ]
    if not video_ids:
        return []

    # 3. Stats détaillées
    vids_resp = youtube.videos().list(
        id=",".join(video_ids),
        part="statistics,snippet,contentDetails"
    ).execute()

    cutoff  = datetime.date.today() - datetime.timedelta(days=_days)
    results = []

    for item in vids_resp.get("items", []):
        pub_iso  = item["snippet"]["publishedAt"]  # 2024-01-15T14:30:00Z
        pub_date = pub_iso[:10]
        pub_hour = int(pub_iso[11:13]) if len(pub_iso) > 13 else None
        if pub_date < str(cutoff):
            continue
        s = item["statistics"]
        results.append({
            "plateforme":    "YouTube",
            "date":          pub_date,
            "hour":          pub_hour,
            "titre":         item["snippet"]["title"][:50],
            "format":        _yt_format(item),
            "vues":          int(s.get("viewCount",    0)),
            "reach":         int(s.get("viewCount",    0)),
            "abonnes":       subscribers,
            "likes":         int(s.get("likeCount",    0)),
            "commentaires":  int(s.get("commentCount", 0)),
            "partages":      0,
            "sauvegardes":   0,
            "_channel_name": channel_name,
            "_channel_id":   channel_id,
        })

    return results


# ─────────────────────────────────────────────
#  YOUTUBE — OAuth token stocké par créateur
# ─────────────────────────────────────────────

def get_youtube_stats_oauth_creator(token_json: str, days=None):
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

    return get_youtube_stats(creds, days=days)


# ─────────────────────────────────────────────
#  YOUTUBE — API Key simple (par créateur)
# ─────────────────────────────────────────────

def get_youtube_stats_apikey(api_key=None, channel_id=None, days=None):
    """
    Stats YouTube via Data API v3 avec une simple clé API.
    Pas besoin d'OAuth — accès aux données publiques de la chaîne.
    Obtenir une clé : console.cloud.google.com → YouTube Data API v3.
    """
    if not api_key or not channel_id:
        print("YouTube API Key : youtube_api_key ou youtube_channel_id manquant")
        return []
    _days = days or DAYS_TO_FETCH
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
            "maxResults": min(_days * 2, 50)
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

        cutoff  = datetime.date.today() - datetime.timedelta(days=_days)
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
#  TIKTOK — OAuth (Login Kit v2)
# ─────────────────────────────────────────────

def get_tiktok_stats(token_json: str, days=None):
    """Stats TikTok via Login Kit v2. Laisse les erreurs remonter."""
    import json as _json
    _days = days or DAYS_TO_FETCH

    if not token_json or token_json.startswith("enc:"):
        raise ValueError("TikTok: token chiffré non déchiffré — ENCRYPTION_KEY manquante")

    data         = _json.loads(token_json)
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("TikTok: access_token manquant dans le token stocké")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }

    # 1. Infos utilisateur (optionnel — scope peut manquer en sandbox)
    followers = 0
    disp_name = "TikTok"
    try:
        _ur = requests.get(
            "https://open.tiktokapis.com/v2/user/info/",
            headers=headers,
            params={"fields": "open_id,display_name,username,follower_count"}
        )
        user_resp = _ur.json()
        if user_resp.get("error", {}).get("code", "ok") == "ok":
            u         = user_resp.get("data", {}).get("user", {})
            followers = u.get("follower_count", 0)
            disp_name = u.get("display_name") or u.get("username", "TikTok")
        else:
            print(f"TikTok user/info ignoré: {user_resp.get('error', {})}")
    except Exception as e:
        print(f"TikTok user/info ignoré: {e}")

    # 2. Liste vidéos (fields = query param, max_count = body)
    _vr = requests.post(
        "https://open.tiktokapis.com/v2/video/list/",
        headers=headers,
        params={"fields": "id,title,create_time,like_count,comment_count,share_count,view_count"},
        json={"max_count": min(_days * 3, 20)},
    )
    try:
        video_resp = _vr.json()
    except Exception:
        raise ValueError(f"TikTok video/list HTTP {_vr.status_code}: {_vr.text[:200] or 'réponse vide'}")

    cutoff  = datetime.date.today() - datetime.timedelta(days=_days)
    results = []

    for v in video_resp.get("data", {}).get("videos", []):
        ts       = v.get("create_time", 0)
        pub_date = datetime.date.fromtimestamp(ts).isoformat()
        pub_hour = datetime.datetime.fromtimestamp(ts).hour if ts else None
        if pub_date < str(cutoff):
            continue
        results.append({
            "plateforme":    "TikTok",
            "date":          pub_date,
            "hour":          pub_hour,
            "titre":         (v.get("title") or "TikTok")[:50],
            "format":        "Video",
            "vues":          v.get("view_count",    0),
            "reach":         v.get("view_count",    0),
            "abonnes":       followers,
            "likes":         v.get("like_count",    0),
            "commentaires":  v.get("comment_count", 0),
            "partages":      v.get("share_count",   0),
            "sauvegardes":   0,
            "_channel_name": disp_name,
        })

    return results


# ─────────────────────────────────────────────
#  INSTAGRAM
# ─────────────────────────────────────────────

def get_instagram_stats(token=None, business_id=None, days=None):
    token       = token       or META_ACCESS_TOKEN
    business_id = business_id or INSTAGRAM_BUSINESS_ID
    if not token or not business_id:
        print("Instagram : META_ACCESS_TOKEN ou INSTAGRAM_BUSINESS_ID manquant")
        return []
    _days = days or DAYS_TO_FETCH
    try:
        BASE   = "https://graph.facebook.com/v19.0"
        params = {"access_token": token}

        account_resp = requests.get(
            f"{BASE}/{business_id}",
            params={**params, "fields": "followers_count"}
        ).json()
        followers = account_resp.get("followers_count", 0)

        results = []
        cutoff  = datetime.datetime.now() - datetime.timedelta(days=_days)

        # Pagination sur /media
        page_url = f"{BASE}/{business_id}/media"
        page_params = {**params, "fields": "id,caption,media_type,timestamp", "limit": 100}
        fetched_pages = 0

        while page_url and fetched_pages < 10:          # max 10 pages = 1000 médias
            media_resp = requests.get(page_url, params=page_params if fetched_pages == 0 else {}).json()
            fetched_pages += 1
            stop_pagination = False

            for media in media_resp.get("data", []):
                post_date = datetime.datetime.fromisoformat(
                    media["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
                if post_date < cutoff:
                    stop_pagination = True
                    break

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
                    "titre":        (media.get("caption", "")[:50] + "…") if media.get("caption") else media_type,
                    "format":       media_type,
                    "vues":         stats.get("impressions", 0),
                    "reach":        stats.get("reach", 0),
                    "abonnes":      followers,
                    "likes":        stats.get("likes_count", 0),
                    "commentaires": stats.get("comments_count", 0),
                    "partages":     stats.get("shares", 0),
                    "sauvegardes":  stats.get("saved", 0),
                })

            if stop_pagination:
                break
            next_url = media_resp.get("paging", {}).get("next")
            page_url = next_url  # None si plus de pages
            page_params = {}     # next URL contient déjà tous les params

        return results

    except Exception as e:
        print(f"Instagram ERREUR : {e}")
        return []


# ─────────────────────────────────────────────
#  FACEBOOK
# ─────────────────────────────────────────────

def get_facebook_stats(token=None, page_id=None, days=None):
    token   = token   or META_ACCESS_TOKEN
    page_id = page_id or FACEBOOK_PAGE_ID
    if not token or not page_id:
        print("Facebook : META_ACCESS_TOKEN ou FACEBOOK_PAGE_ID manquant")
        return []
    _days = days or DAYS_TO_FETCH
    try:
        BASE   = "https://graph.facebook.com/v19.0"
        params = {"access_token": token}

        page_resp = requests.get(
            f"{BASE}/{page_id}",
            params={**params, "fields": "fan_count"}
        ).json()
        fans = page_resp.get("fan_count", 0)

        results = []
        cutoff  = datetime.datetime.now() - datetime.timedelta(days=_days)

        # Pagination sur /posts
        page_url    = f"{BASE}/{page_id}/posts"
        page_params = {**params, "fields": "id,message,created_time", "limit": 100}
        fetched_pages = 0

        while page_url and fetched_pages < 10:
            posts_resp = requests.get(page_url, params=page_params if fetched_pages == 0 else {}).json()
            fetched_pages += 1
            stop_pagination = False

            for post in posts_resp.get("data", []):
                post_date = datetime.datetime.fromisoformat(
                    post["created_time"].replace("+0000", "+00:00")).replace(tzinfo=None)
                if post_date < cutoff:
                    stop_pagination = True
                    break

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
                    "titre":        (post.get("message", "")[:50] + "…") if post.get("message") else "Post",
                    "format":       "Post",
                    "vues":         stats.get("post_impressions", 0),
                    "reach":        stats.get("post_reach", 0),
                    "abonnes":      fans,
                    "likes":        eng_resp.get("reactions", {}).get("summary", {}).get("total_count", 0),
                    "commentaires": eng_resp.get("comments",  {}).get("summary", {}).get("total_count", 0),
                    "partages":     eng_resp.get("shares",    {}).get("count", 0),
                    "sauvegardes":  0,
                })

            if stop_pagination:
                break
            next_url    = posts_resp.get("paging", {}).get("next")
            page_url    = next_url
            page_params = {}

        return results

    except Exception as e:
        print(f"Facebook ERREUR : {e}")
        return []
