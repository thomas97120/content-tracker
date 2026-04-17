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
#  YOUTUBE
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

    except Exception as e:
        print(f"YouTube ERREUR : {e}")
        return []


# ─────────────────────────────────────────────
#  INSTAGRAM
# ─────────────────────────────────────────────

def get_instagram_stats():
    if not META_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ID:
        print("Instagram : META_ACCESS_TOKEN ou INSTAGRAM_BUSINESS_ID manquant")
        return []
    try:
        BASE   = "https://graph.facebook.com/v19.0"
        params = {"access_token": META_ACCESS_TOKEN}

        account_resp = requests.get(
            f"{BASE}/{INSTAGRAM_BUSINESS_ID}",
            params={**params, "fields": "followers_count"}
        ).json()
        followers = account_resp.get("followers_count", 0)

        media_resp = requests.get(
            f"{BASE}/{INSTAGRAM_BUSINESS_ID}/media",
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

def get_facebook_stats():
    if not META_ACCESS_TOKEN or not FACEBOOK_PAGE_ID:
        print("Facebook : META_ACCESS_TOKEN ou FACEBOOK_PAGE_ID manquant")
        return []
    try:
        BASE   = "https://graph.facebook.com/v19.0"
        params = {"access_token": META_ACCESS_TOKEN}

        page_resp = requests.get(
            f"{BASE}/{FACEBOOK_PAGE_ID}",
            params={**params, "fields": "fan_count"}
        ).json()
        fans = page_resp.get("fan_count", 0)

        posts_resp = requests.get(
            f"{BASE}/{FACEBOOK_PAGE_ID}/posts",
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
