"""
tiktok_publisher.py — Publication de vidéos TikTok via Content Posting API v2
Scope requis : video.publish
"""

import json
import os
import time
import requests

TIKTOK_PUBLISH_INIT = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_PUBLISH_STATUS = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

PRIVACY_LEVELS = {
    "public":    "PUBLIC_TO_EVERYONE",
    "friends":   "MUTUAL_FOLLOW_FRIENDS",
    "private":   "SELF_ONLY",
}


def publish_video(token_json: str, video_path: str, title: str = "",
                  privacy: str = "public", disable_comment: bool = False,
                  disable_duet: bool = False, disable_stitch: bool = False) -> dict:
    """
    Publie une vidéo sur TikTok.
    Retourne {"publish_id": "...", "status": "processing|published|failed", "error": "..."}
    """
    try:
        data = json.loads(token_json)
    except Exception:
        return {"error": "Token TikTok invalide"}

    access_token = data.get("access_token")
    if not access_token:
        return {"error": "access_token manquant"}

    if not os.path.exists(video_path):
        return {"error": f"Fichier introuvable: {video_path}"}

    video_size = os.path.getsize(video_path)
    if video_size == 0:
        return {"error": "Fichier vidéo vide"}

    # Chunk size = 10 MB max (TikTok recommande ≤ 64 MB total pour upload simple)
    chunk_size  = min(video_size, 10 * 1024 * 1024)
    total_chunks = (video_size + chunk_size - 1) // chunk_size

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json; charset=UTF-8",
    }

    # 1. Init upload
    init_body = {
        "post_info": {
            "title":                   (title or "")[:150],
            "privacy_level":           PRIVACY_LEVELS.get(privacy, "PUBLIC_TO_EVERYONE"),
            "disable_duet":            disable_duet,
            "disable_comment":         disable_comment,
            "disable_stitch":          disable_stitch,
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source":            "FILE_UPLOAD",
            "video_size":        video_size,
            "chunk_size":        chunk_size,
            "total_chunk_count": total_chunks,
        },
    }

    try:
        r = requests.post(TIKTOK_PUBLISH_INIT, headers=headers, json=init_body, timeout=30)
        resp = r.json()
    except Exception as e:
        return {"error": f"Init failed: {e}"}

    if resp.get("error", {}).get("code", "ok") != "ok":
        err = resp.get("error", {})
        return {"error": f"TikTok init error: {err.get('message', str(err))}"}

    publish_id = resp.get("data", {}).get("publish_id")
    upload_url = resp.get("data", {}).get("upload_url")

    if not publish_id or not upload_url:
        return {"error": f"Réponse init invalide: {resp}"}

    # 2. Upload chunks
    try:
        with open(video_path, "rb") as f:
            for chunk_idx in range(total_chunks):
                chunk_data  = f.read(chunk_size)
                actual_size = len(chunk_data)
                start_byte  = chunk_idx * chunk_size
                end_byte    = start_byte + actual_size - 1

                upload_headers = {
                    "Content-Type":   "video/mp4",
                    "Content-Length": str(actual_size),
                    "Content-Range":  f"bytes {start_byte}-{end_byte}/{video_size}",
                }
                ur = requests.put(upload_url, headers=upload_headers, data=chunk_data, timeout=120)
                if ur.status_code not in (200, 201, 206):
                    return {"error": f"Upload chunk {chunk_idx} failed: HTTP {ur.status_code} — {ur.text[:200]}"}
    except Exception as e:
        return {"error": f"Upload error: {e}"}

    # 3. Poll status (max 60s)
    status_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json; charset=UTF-8",
    }
    for _ in range(12):  # 12 × 5s = 60s
        time.sleep(5)
        try:
            sr = requests.post(TIKTOK_PUBLISH_STATUS,
                               headers=status_headers,
                               json={"publish_id": publish_id},
                               timeout=15)
            st = sr.json()
        except Exception:
            continue

        status = st.get("data", {}).get("status", "")
        if status == "PUBLISH_COMPLETE":
            return {"publish_id": publish_id, "status": "published"}
        if status in ("FAILED", "PUBLISH_FAILED"):
            fail_reason = st.get("data", {}).get("fail_reason", "unknown")
            return {"publish_id": publish_id, "status": "failed", "error": fail_reason}
        # PROCESSING_UPLOAD / PROCESSING_DOWNLOAD → continue polling

    # Timeout mais publish_id connu → probablement en cours
    return {"publish_id": publish_id, "status": "processing"}
