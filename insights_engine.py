"""
insights_engine.py — Smart content coach
Score 0-100 + automated insights + recommendations
"""

from __future__ import annotations
import datetime


# ─────────────────────────────────────────────────────────────
#  SCORE  (0–100)
# ─────────────────────────────────────────────────────────────

def _views_score(avg_views: float, views_delta_pct: float | None) -> int:
    """
    40 pts max.
    Base sur avg_views (volumétrie) + tendance.
    """
    # Volumétrie (0-25)
    if   avg_views >= 500_000: base = 25
    elif avg_views >= 200_000: base = 22
    elif avg_views >= 100_000: base = 18
    elif avg_views >=  50_000: base = 14
    elif avg_views >=  20_000: base = 10
    elif avg_views >=   5_000: base = 6
    else:                      base = 2

    # Tendance (-15 to +15)
    if views_delta_pct is None:
        trend = 0
    elif views_delta_pct >= 20:   trend = 15
    elif views_delta_pct >= 5:    trend = 10
    elif views_delta_pct >= -5:   trend = 5
    elif views_delta_pct >= -20:  trend = 0
    elif views_delta_pct >= -40:  trend = -5
    else:                         trend = -10

    return max(0, min(40, base + trend))


def _engagement_score(eng_pct: float) -> int:
    """35 pts max. Barème universal multi-plateforme."""
    if   eng_pct >= 10: return 35
    elif eng_pct >=  8: return 30
    elif eng_pct >=  5: return 25
    elif eng_pct >=  3: return 18
    elif eng_pct >=  2: return 12
    elif eng_pct >=  1: return 6
    else:               return 0


def _frequency_score(posts: int, days: int) -> int:
    """25 pts max. Cadence hebdomadaire normalisée."""
    weeks        = max(days / 7, 1)
    posts_per_wk = posts / weeks

    if   posts_per_wk >= 5: return 25
    elif posts_per_wk >= 3: return 20
    elif posts_per_wk >= 2: return 14
    elif posts_per_wk >= 1: return 8
    else:                   return 2


def compute_score(
    avg_views:       float,
    views_delta_pct: float | None,
    eng_pct:         float,
    posts:           int,
    days:            int,
) -> dict:
    vs = _views_score(avg_views, views_delta_pct)
    es = _engagement_score(eng_pct)
    fs = _frequency_score(posts, days)
    total = vs + es + fs

    if   total >= 80: grade, label = "A", "Excellent"
    elif total >= 65: grade, label = "B", "Bon"
    elif total >= 50: grade, label = "C", "Moyen"
    elif total >= 35: grade, label = "D", "Faible"
    else:             grade, label = "F", "Critique"

    return {
        "score":    total,
        "grade":    grade,
        "label":    label,
        "breakdown": {"views": vs, "engagement": es, "frequency": fs},
    }


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

def _pct(a, b):
    """% change from b to a."""
    if not b:
        return None
    return round((a - b) / b * 100, 1)


def _fmt(n: float) -> str:
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return str(int(n))


# ─────────────────────────────────────────────────────────────
#  INSIGHTS
# ─────────────────────────────────────────────────────────────

def generate_insights(data: dict) -> list[dict]:
    """
    data keys:
      total_views, prev_views, avg_views, prev_avg_views,
      eng_pct, prev_eng_pct,
      posts, prev_posts, days,
      best_post, platform_split,
      best_hour, avg_views_by_format
    """
    insights = []

    total_views  = data.get("total_views", 0)
    prev_views   = data.get("prev_views", 0)
    avg_views    = data.get("avg_views", 0)
    prev_avg     = data.get("prev_avg_views", 0)
    eng          = data.get("eng_pct", 0)
    prev_eng     = data.get("prev_eng_pct", 0)
    posts        = data.get("posts", 0)
    prev_posts   = data.get("prev_posts", 0)
    days         = data.get("days", 7)
    best_post    = data.get("best_post") or {}
    platform_split = data.get("platform_split") or {}
    best_hour    = data.get("best_hour")
    fmt_perf     = data.get("avg_views_by_format") or {}

    posts_delta  = _pct(posts, prev_posts)
    views_delta  = _pct(total_views, prev_views)
    avg_delta    = _pct(avg_views, prev_avg)
    eng_delta    = _pct(eng, prev_eng)

    # 1. Corrélation fréquence → vues
    if posts_delta is not None and views_delta is not None:
        if posts_delta <= -20 and views_delta <= -20:
            insights.append({
                "type": "warning",
                "icon": "📉",
                "text": f"La baisse de publication ({posts_delta:+.0f}%) explique directement la chute des vues ({views_delta:+.0f}%) — corrélation directe.",
            })
        elif posts_delta >= 20 and views_delta >= 10:
            insights.append({
                "type": "positive",
                "icon": "🚀",
                "text": f"Plus de posts ({posts_delta:+.0f}%) a généré plus de vues ({views_delta:+.0f}%) — maintiens ce rythme.",
            })

    # 2. Outlier top vidéo
    if best_post.get("vues") and total_views > 0:
        top_pct = round(best_post["vues"] / total_views * 100)
        if top_pct >= 40:
            insights.append({
                "type": "warning",
                "icon": "⚠️",
                "text": f"Ta meilleure vidéo ({_fmt(best_post['vues'])} vues) représente {top_pct}% du total — performance trop dépendante d'un seul post.",
            })
        elif top_pct >= 25:
            insights.append({
                "type": "info",
                "icon": "🏆",
                "text": f"Ton top post génère {top_pct}% des vues totales — analyse son format/sujet pour le répliquer.",
            })

    # 3. Engagement découplé des vues
    if eng_delta is not None and views_delta is not None:
        if eng_delta > 10 and views_delta < -10:
            insights.append({
                "type": "positive",
                "icon": "💡",
                "text": f"Engagement en hausse ({eng_delta:+.0f}%) malgré moins de vues — ton audience est plus qualifiée, travaille la distribution.",
            })

    # 4. Engagement fort
    if eng >= 8:
        insights.append({
            "type": "positive",
            "icon": "🔥",
            "text": f"Taux d'engagement de {eng:.1f}% — dans le top 10% des créateurs. Ton contenu résonne fort avec ton audience.",
        })
    elif eng < 1.5 and posts > 3:
        insights.append({
            "type": "warning",
            "icon": "😶",
            "text": f"Engagement à {eng:.1f}% — très en dessous de la moyenne (3-5%). Le contenu ne génère pas de réaction.",
        })

    # 5. Concentration plateforme
    top_platform = max(platform_split, key=platform_split.get) if platform_split else None
    if top_platform:
        top_share = platform_split[top_platform]
        if top_share >= 80:
            insights.append({
                "type": "info",
                "icon": "📦",
                "text": f"{int(top_share)}% de tes vues viennent de {top_platform} — dépendance élevée à une seule plateforme.",
            })

    # 6. Cadence
    weeks = max(days / 7, 1)
    ppw   = posts / weeks
    if ppw < 1:
        insights.append({
            "type": "warning",
            "icon": "🐢",
            "text": f"Moins d'1 post par semaine ({ppw:.1f}/sem) — insuffisant pour maintenir l'algorithme actif.",
        })
    elif ppw >= 4:
        insights.append({
            "type": "positive",
            "icon": "⚡",
            "text": f"Cadence forte à {ppw:.1f} posts/semaine — tu alimentes l'algorithme régulièrement.",
        })

    # 7. Avg views en chute
    if avg_delta is not None and avg_delta <= -40:
        insights.append({
            "type": "warning",
            "icon": "📊",
            "text": f"Vues moyennes par vidéo en baisse de {avg_delta:.0f}% — les derniers posts underperforment. Analyse le format/sujet.",
        })

    # 8. Meilleure heure
    if best_hour is not None:
        insights.append({
            "type": "info",
            "icon": "🕐",
            "text": f"Tes posts à {best_hour}h génèrent en moyenne le plus de vues — c'est ta fenêtre d'or.",
        })

    # 9. Comparaison formats
    if len(fmt_perf) >= 2:
        sorted_fmt = sorted(fmt_perf.items(), key=lambda x: x[1], reverse=True)
        best_f, best_v = sorted_fmt[0]
        worst_f, worst_v = sorted_fmt[-1]
        if best_v > 0 and worst_v >= 0:
            ratio = best_v / max(worst_v, 1)
            if ratio >= 2:
                insights.append({
                    "type": "positive",
                    "icon": "🎞",
                    "text": f"Le format {best_f} performe {ratio:.1f}x mieux que {worst_f} — concentre ta production dessus.",
                })

    return insights[:8]  # max 8


# ─────────────────────────────────────────────────────────────
#  RECOMMENDATIONS
# ─────────────────────────────────────────────────────────────

def generate_recommendations(data: dict, score: int) -> list[dict]:
    recs = []

    posts       = data.get("posts", 0)
    days        = data.get("days", 7)
    eng         = data.get("eng_pct", 0)
    total_views = data.get("total_views", 0)
    prev_views  = data.get("prev_views", 0)
    best_hour   = data.get("best_hour")
    platform_split = data.get("platform_split") or {}
    fmt_perf    = data.get("avg_views_by_format") or {}
    views_delta = _pct(total_views, prev_views)

    weeks = max(days / 7, 1)
    ppw   = posts / weeks

    # 1. Fréquence
    if ppw < 2:
        recs.append({
            "priority": "high",
            "icon": "📅",
            "action": "Publie 3–4 fois par semaine",
            "why": "Sous 2 posts/sem, l'algorithme dé-priorise ton profil. Chaque post manqué = visibilité perdue.",
        })
    elif ppw < 3:
        recs.append({
            "priority": "medium",
            "icon": "📅",
            "action": "Vise 4–5 posts par semaine",
            "why": f"À {ppw:.1f} posts/sem tu es dans la moyenne — un peu plus et tu passes devant la concurrence.",
        })

    # 2. Heure de publication
    if best_hour is not None:
        recs.append({
            "priority": "high",
            "icon": "⏰",
            "action": f"Publie systématiquement entre {best_hour}h et {best_hour+1}h",
            "why": "Tes posts à cette heure génèrent le plus de vues — l'audience est là et l'algorithme booste les contenus qui démarrent vite.",
        })

    # 3. Format winner
    if fmt_perf:
        best_fmt = max(fmt_perf, key=fmt_perf.get)
        recs.append({
            "priority": "high",
            "icon": "🎞",
            "action": f"Double la production de {best_fmt}",
            "why": f"Ton meilleur format en avg vues — arrête d'expérimenter sur ce qui marche moins.",
        })

    # 4. Engagement élevé mais vues faibles
    if eng >= 4 and views_delta is not None and views_delta < -15:
        recs.append({
            "priority": "high",
            "icon": "📣",
            "action": "Booste la distribution (collab, réponse commentaires, crosspost)",
            "why": "Fort engagement + faibles vues = ton contenu est bon mais ne touche pas assez de monde. Le problème est la distribution, pas le contenu.",
        })

    # 5. Engagement faible
    if eng < 2:
        recs.append({
            "priority": "medium",
            "icon": "💬",
            "action": "Intègre un CTA clair dans chaque post (question, vote, tag)",
            "why": f"Engagement à {eng:.1f}% — pose une question en fin de vidéo ou en caption. L'algorithme TikTok/YT booste les posts qui génèrent des commentaires.",
        })

    # 6. Diversification plateforme
    top_platform = max(platform_split, key=platform_split.get) if platform_split else None
    if top_platform:
        top_share = platform_split[top_platform]
        if top_share >= 75:
            other = "TikTok" if top_platform == "YouTube" else "YouTube Shorts"
            recs.append({
                "priority": "medium",
                "icon": "🌐",
                "action": f"Reposts tes top contenus sur {other}",
                "why": f"{int(top_share)}% de tes vues viennent de {top_platform}. Recycler sur {other} = vues gratuites sans effort de création.",
            })

    # 7. Répliquer le top post
    best_post = data.get("best_post") or {}
    if best_post.get("vues") and total_views > 0:
        top_pct = round(best_post["vues"] / total_views * 100)
        if top_pct >= 25:
            recs.append({
                "priority": "high",
                "icon": "🏆",
                "action": f"Analyse et répliquer le format de ton top post ({_fmt(best_post['vues'])} vues)",
                "why": "Ce post surperforme — décortique le titre, la durée, l'accroche, l'heure de publication et reproduis la même structure.",
            })

    # 8. Score critique
    if score < 35:
        recs.append({
            "priority": "high",
            "icon": "🚨",
            "action": "Revois ta stratégie de contenu complètement",
            "why": "Score critique. Publie plus souvent, teste de nouveaux formats et analyse les créateurs qui performent dans ta niche.",
        })

    # Trier : high en premier
    order = {"high": 0, "medium": 1, "low": 2}
    recs.sort(key=lambda r: order.get(r["priority"], 9))
    return recs[:7]


# ─────────────────────────────────────────────────────────────
#  PRÉDICTION — prochain post
# ─────────────────────────────────────────────────────────────

def predict_next_post(stats_cur: dict) -> dict:
    """
    Prédit les vues du prochain post via moyenne glissante + tendance linéaire.
    Retourne: predicted_views, trend_pct, confidence, based_on
    """
    all_posts = sorted(
        [p for pl in stats_cur.values() for p in pl if p.get("date") and (p.get("vues") or 0) > 0],
        key=lambda x: x["date"]
    )
    if len(all_posts) < 3:
        return {"error": "Pas assez de posts pour prédire (minimum 3)"}

    views = [p["vues"] for p in all_posts]

    # Moyenne glissante des 5 derniers
    recent = views[-5:]
    avg_recent = sum(recent) / len(recent)

    # Tendance : derniers 3 vs 3 précédents
    if len(views) >= 6:
        last3 = sum(views[-3:]) / 3
        prev3 = sum(views[-6:-3]) / 3
        trend_pct = (last3 - prev3) / prev3 * 100 if prev3 > 0 else 0
    else:
        trend_pct = 0

    # Applique tendance amortie (50%) pour éviter surfit
    predicted = avg_recent * (1 + (trend_pct / 100) * 0.5)
    predicted = max(predicted, avg_recent * 0.3)  # plancher 30% de la moyenne

    confidence = "haute" if len(all_posts) >= 10 else "moyenne" if len(all_posts) >= 5 else "faible"

    # Intervalle de confiance simple (±1 écart-type)
    import math
    mean = sum(views) / len(views)
    std  = math.sqrt(sum((v - mean) ** 2 for v in views) / len(views))
    low  = max(0, round(predicted - std * 0.7))
    high = round(predicted + std * 0.7)

    return {
        "predicted_views": round(predicted),
        "range_low":       low,
        "range_high":      high,
        "avg_recent":      round(avg_recent),
        "trend_pct":       round(trend_pct, 1),
        "confidence":      confidence,
        "based_on":        len(all_posts),
    }


# ─────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────

def analyze(stats_cur: dict, stats_prev: dict, days: int) -> dict:
    """
    stats_cur / stats_prev : dict {platform: [post, ...]} (format API)
    Retourne { score, insights, recommendations }
    """
    def _agg(stats_obj):
        views = likes = comments = shares = posts = followers = 0
        best  = None
        fmt_data: dict[str, list] = {}

        for platform, plist in stats_obj.items():
            for p in plist:
                v = p.get("vues", 0) or 0
                l = p.get("likes", 0) or 0
                c = p.get("commentaires", 0) or 0
                s = p.get("partages", 0) or 0
                views    += v
                likes    += l
                comments += c
                shares   += s
                posts    += 1
                if not best or v > best.get("vues", 0):
                    best = p
                fmt = p.get("format") or "Autre"
                fmt_data.setdefault(fmt, []).append(v)
            if plist:
                followers += plist[-1].get("abonnes", 0) or 0

        eng = (likes + comments) / views * 100 if views > 0 else 0
        avg_views = views / posts if posts else 0
        avg_fmt = {f: sum(vs) / len(vs) for f, vs in fmt_data.items() if vs}
        return dict(
            total_views=views, likes=likes, comments=comments,
            posts=posts, followers=followers, eng_pct=round(eng, 2),
            avg_views=round(avg_views), best_post=best, avg_views_by_format=avg_fmt,
        )

    cur  = _agg(stats_cur)
    prev = _agg(stats_prev)

    # Platform split (vues par plateforme)
    platform_split = {}
    total = sum(
        sum(p.get("vues", 0) or 0 for p in pl)
        for pl in stats_cur.values()
    ) or 1
    for plat, pl in stats_cur.items():
        platform_split[plat] = round(
            sum(p.get("vues", 0) or 0 for p in pl) / total * 100, 1
        )

    # Best hour from current posts
    best_hour = None
    hour_views: dict[int, list] = {}
    for pl in stats_cur.values():
        for p in pl:
            h = p.get("hour")
            if h is not None:
                hour_views.setdefault(h, []).append(p.get("vues", 0) or 0)
    if hour_views:
        best_hour = max(hour_views, key=lambda h: sum(hour_views[h]) / len(hour_views[h]))

    data = {
        **cur,
        "prev_views":     prev["total_views"],
        "prev_avg_views": prev["avg_views"],
        "prev_eng_pct":   prev["eng_pct"],
        "prev_posts":     prev["posts"],
        "days":           days,
        "platform_split": platform_split,
        "best_hour":      best_hour,
    }

    views_delta = _pct(cur["total_views"], prev["total_views"])
    score_data  = compute_score(
        avg_views       = cur["avg_views"],
        views_delta_pct = views_delta,
        eng_pct         = cur["eng_pct"],
        posts           = cur["posts"],
        days            = days,
    )

    return {
        "score":           score_data,
        "insights":        generate_insights(data),
        "recommendations": generate_recommendations(data, score_data["score"]),
        "kpis":            cur,
        "prediction":      predict_next_post(stats_cur),
    }
