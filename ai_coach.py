"""
ai_coach.py — Suggestions IA basées sur les top posts
Supporte OpenRouter (gratuit), OpenAI et Groq.

Render — ajouter UNE des variables (par ordre de priorité) :
  OPENROUTER_API_KEY → gratuit sur openrouter.ai (recommandé — pas de blocage IP)
  OPENAI_API_KEY     → payant sur platform.openai.com
  GROQ_API_KEY       → gratuit sur console.groq.com (bloqué sur Render/Cloudflare)
"""
from __future__ import annotations
import os
import json

GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Sélection automatique du provider
if OPENROUTER_API_KEY:
    _API_URL = "https://openrouter.ai/api/v1/chat/completions"
    _API_KEY = OPENROUTER_API_KEY
    _MODEL   = "mistralai/mistral-7b-instruct:free"
    _EXTRA_HEADERS = {
        "HTTP-Referer": os.environ.get("APP_URL", "https://content-tracker.onrender.com"),
        "X-Title": "Content Tracker",
    }
elif OPENAI_API_KEY:
    _API_URL = "https://api.openai.com/v1/chat/completions"
    _API_KEY = OPENAI_API_KEY
    _MODEL   = "gpt-4o-mini"
    _EXTRA_HEADERS = {}
elif GROQ_API_KEY:
    _API_URL = "https://api.groq.com/openai/v1/chat/completions"
    _API_KEY = GROQ_API_KEY
    _MODEL   = "llama-3.3-70b-versatile"
    _EXTRA_HEADERS = {}
else:
    _API_URL = _API_KEY = _MODEL = ""
    _EXTRA_HEADERS = {}


def _fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return str(int(n))


def generate_suggestions(stats_cur: dict, creator: str = "") -> dict:
    """
    Analyse les top posts du créateur et retourne :
    - 5 idées de titres/sujets
    - L'angle de contenu gagnant
    - Le format optimal
    - L'accroche type
    """
    if not _API_KEY:
        return {"error": "Ajoute GROQ_API_KEY (gratuit : console.groq.com) ou OPENAI_API_KEY dans les variables Render"}

    # Collecte tous les posts
    all_posts = []
    for platform, posts in stats_cur.items():
        for p in posts:
            v   = p.get("vues", 0) or 0
            eng = (p.get("likes", 0) + p.get("commentaires", 0)) / v * 100 if v > 0 else 0
            all_posts.append({
                "platform": platform,
                "title":    (p.get("titre") or "")[:80],
                "format":   p.get("format", ""),
                "views":    v,
                "eng_pct":  round(eng, 1),
                "date":     p.get("date", ""),
            })

    if not all_posts:
        return {"error": "Aucun post disponible pour l'analyse"}

    # Top 8 par vues
    top = sorted(all_posts, key=lambda x: x["views"], reverse=True)[:8]
    # Flop 3 (pour contraste)
    flop = sorted(all_posts, key=lambda x: x["views"])[:3]

    top_txt  = "\n".join(
        f"- [{p['platform']} · {p['format']}] \"{p['title']}\" → {_fmt(p['views'])} vues, {p['eng_pct']}% eng"
        for p in top
    )
    flop_txt = "\n".join(
        f"- [{p['platform']} · {p['format']}] \"{p['title']}\" → {_fmt(p['views'])} vues"
        for p in flop
    ) if flop else "N/A"

    platforms = list({p["platform"] for p in all_posts})

    prompt = f"""Tu es un expert en stratégie de contenu pour créateurs ({', '.join(platforms)}).

TOP POSTS (meilleures performances) :
{top_txt}

POSTS QUI ONT SOUS-PERFORMÉ :
{flop_txt}

Analyse ces données et génère une réponse JSON structurée UNIQUEMENT (pas de texte avant/après) :

{{
  "winning_angle": "L'angle/thématique qui performe le mieux en 1 phrase courte",
  "winning_format": "Format optimal détecté (Short / Video / Reel / etc.)",
  "hook_pattern": "Le pattern d'accroche commun aux top posts en 1 phrase (ex: 'Question provocante + chiffre')",
  "title_ideas": [
    "Titre idée 1 — directement utilisable",
    "Titre idée 2 — directement utilisable",
    "Titre idée 3 — directement utilisable",
    "Titre idée 4 — directement utilisable",
    "Titre idée 5 — directement utilisable"
  ],
  "avoid": "Ce qui ne marche pas chez ce créateur en 1 phrase",
  "next_video": "Description du prochain vidéo à faire en 1-2 phrases concrètes"
}}"""

    try:
        import urllib.request
        payload = {
            "model":       _MODEL,
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens":  800,
        }
        # response_format json_object : supporté par OpenAI + Groq llama-3.3
        payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload).encode()

        import urllib.error
        headers = {"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"}
        headers.update(_EXTRA_HEADERS)
        req = urllib.request.Request(
            _API_URL,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as http_err:
            err_body = http_err.read().decode("utf-8", errors="replace")[:300]
            return {"error": f"Groq HTTP {http_err.code} — {err_body}"}

        content = resp["choices"][0]["message"]["content"]
        result  = json.loads(content)
        result["posts_analyzed"] = len(top)
        return result

    except Exception as e:
        return {"error": f"IA erreur : {str(e)[:200]}"}
