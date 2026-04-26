# Graph Report - .  (2026-04-26)

## Corpus Check
- Corpus is ~17,203 words - fits in a single context window. You may not need a graph.

## Summary
- 276 nodes · 490 edges · 14 communities detected
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 68 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_app.py|app.py]]
- [[_COMMUNITY_stats_tracker_gsheet.py|stats_tracker_gsheet.py]]
- [[_COMMUNITY_insights_engine.py|insights_engine.py]]
- [[_COMMUNITY_creator_apis.py|creator_apis.py]]
- [[_COMMUNITY_sheets.py|sheets.py]]
- [[_COMMUNITY_history_store.py|history_store.py]]
- [[_COMMUNITY_push_manager.py|push_manager.py]]
- [[_COMMUNITY_load_users()|load_users()]]
- [[_COMMUNITY_csv_parser.py|csv_parser.py]]
- [[_COMMUNITY_Content Tracker Project|Content Tracker Project]]
- [[_COMMUNITY_ideas_store.py|ideas_store.py]]
- [[_COMMUNITY_Content Tracker Application|Content Tracker Application]]
- [[_COMMUNITY_generate_suggestions()|generate_suggestions()]]
- [[_COMMUNITY_sw.js|sw.js]]

## God Nodes (most connected - your core abstractions)
1. `current_user()` - 19 edges
2. `can_access_creator()` - 16 edges
3. `sync_all()` - 12 edges
4. `load_users()` - 11 edges
5. `analyze()` - 11 edges
6. `Content Tracker Project` - 11 edges
7. `get_stats()` - 10 edges
8. `save_creator_apis()` - 9 edges
9. `main()` - 9 edges
10. `import_csv()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `dashboard()` --calls--> `get_dashboard_data()`  [INFERRED]
  app.py → sheets.py
- `get_stats()` --calls--> `get_creator_apis()`  [INFERRED]
  app.py → creator_apis.py
- `sync_all()` --calls--> `get_creator_apis()`  [INFERRED]
  app.py → creator_apis.py
- `sync_history()` --calls--> `get_creator_apis()`  [INFERRED]
  app.py → creator_apis.py
- `sync_all()` --calls--> `get_google_creds()`  [INFERRED]
  app.py → sheets.py

## Hyperedges (group relationships)
- **Flask Web Application Stack** — requirements_flask, requirements_flask_cors, requirements_flask_limiter, requirements_gunicorn [INFERRED 0.88]
- **Google API Integration Stack** — requirements_google_api_python_client, requirements_google_auth_oauthlib [INFERRED 0.90]
- **Web Push Notification Stack** — requirements_cryptography, requirements_pywebpush [INFERRED 0.80]

## Communities

### Community 0 - "app.py"
Cohesion: 0.06
Nodes (37): add_idea(), add_stats(), admin_consolidated(), can_access_creator(), current_user(), dashboard(), debug_ai(), export_excel() (+29 more)

### Community 1 - "stats_tracker_gsheet.py"
Cohesion: 0.08
Nodes (37): get_stats(), Sync global (env vars) ou par créateur si token présent., Exécuté dans un thread background — remplit _sync_jobs[job_id]., _run_sync_history(), sync_all(), get_tiktok_stats(), get_youtube_stats(), get_youtube_stats_apikey() (+29 more)

### Community 2 - "insights_engine.py"
Cohesion: 0.13
Nodes (24): get_insights(), send_weekly_email(), analyze(), best_days_analysis(), compute_score(), _engagement_score(), _fmt(), format_breakdown() (+16 more)

### Community 3 - "creator_apis.py"
Cohesion: 0.13
Nodes (23): _clear_creator_cache(), delete_my_api(), get_my_apis(), google_callback(), meta_callback(), Vide toutes les entrées de cache pour ce créateur., save_my_apis(), tiktok_callback() (+15 more)

### Community 4 - "sheets.py"
Cohesion: 0.16
Nodes (23): import_csv(), add_manual_stats(), _append_rows(), _float(), get_all_creators(), get_creator_stats(), get_dashboard_data(), get_google_creds() (+15 more)

### Community 5 - "history_store.py"
Cohesion: 0.17
Nodes (19): get_creator_history(), Retourne l'historique stocké, avec filtre optionnel by date range., bootstrap_from_env(), _conn(), export_all_json(), get_history(), get_history_summary(), get_monthly_breakdown() (+11 more)

### Community 6 - "push_manager.py"
Cohesion: 0.13
Nodes (17): generate_vapid(), push_subscribe(), push_test(), push_unsubscribe(), check_and_alert(), generate_vapid_keys(), push_manager.py — Web Push notifications (VAPID / PWA)  Setup Render :   VAPID_P, Admin : envoie à tous les abonnés. (+9 more)

### Community 7 - "load_users()"
Cohesion: 0.17
Nodes (18): change_password(), export_state(), find_user_by_email(), _flush_users(), forgot_password(), _html_page(), load_users(), login() (+10 more)

### Community 8 - "csv_parser.py"
Cohesion: 0.18
Nodes (17): _date(), _int(), parse_csv(), parse_facebook(), parse_instagram(), parse_snapchat(), parse_tiktok(), parse_youtube() (+9 more)

### Community 9 - "Content Tracker Project"
Cohesion: 0.24
Nodes (12): Graphify Knowledge Graph Instructions, Content Tracker Project, cryptography, flask, flask-cors, flask-limiter, google-api-python-client, google-auth-oauthlib (+4 more)

### Community 10 - "ideas_store.py"
Cohesion: 0.42
Nodes (8): swipe_idea(), add_idea(), export_all(), _flush(), get_ideas(), _load(), ideas_store.py — Stockage des idées de contenu par créateur Env var Render : IDE, update_idea_decision()

### Community 11 - "Content Tracker Application"
Cohesion: 0.52
Nodes (7): Circular Refresh / Sync Symbol, Content Tracker Application, icon-192.png — App Icon, icon-512.png — App Icon, Stylized Letter A Logo Mark, Purple Gradient Circle Design, Progressive Web App Icon (192px)

### Community 12 - "generate_suggestions()"
Cohesion: 0.4
Nodes (5): _fmt(), generate_suggestions(), ai_coach.py — Suggestions IA basées sur les top posts Supporte OpenRouter (gratu, Analyse les top posts du créateur et retourne :     - 5 idées de titres/sujets, ai_suggestions()

### Community 13 - "sw.js"
Cohesion: 1.0
Nodes (0): 

## Knowledge Gaps
- **83 isolated node(s):** `push_manager.py — Web Push notifications (VAPID / PWA)  Setup Render :   VAPID_P`, `Enregistre ou met à jour l'abonnement push d'un utilisateur.`, `Envoie une notification push à tous les abonnements d'un utilisateur.`, `Admin : envoie à tous les abonnés.`, `Génère une paire VAPID. Appeler une seule fois, stocker dans Render.` (+78 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `sw.js`** (1 nodes): `sw.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `import_csv()` connect `sheets.py` to `app.py`, `csv_parser.py`, `creator_apis.py`, `history_store.py`?**
  _High betweenness centrality (0.155) - this node is a cross-community bridge._
- **Why does `sync_all()` connect `stats_tracker_gsheet.py` to `app.py`, `creator_apis.py`, `sheets.py`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Why does `analyze()` connect `insights_engine.py` to `app.py`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `sync_all()` (e.g. with `get_spreadsheet_id()` and `get_creator_apis()`) actually correct?**
  _`sync_all()` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `analyze()` (e.g. with `get_insights()` and `admin_consolidated()`) actually correct?**
  _`analyze()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `push_manager.py — Web Push notifications (VAPID / PWA)  Setup Render :   VAPID_P`, `Enregistre ou met à jour l'abonnement push d'un utilisateur.`, `Envoie une notification push à tous les abonnements d'un utilisateur.` to the rest of the system?**
  _83 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `app.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06 - nodes in this community are weakly interconnected._