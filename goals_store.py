import json, os
_FILE = "goals.json"
_goals = {}

def _load():
    global _goals
    if os.path.exists(_FILE):
        try:
            with open(_FILE) as f: _goals = json.load(f)
        except: _goals = {}
_load()

def _save():
    with open(_FILE, "w") as f: json.dump(_goals, f)

def get_goals(creator: str) -> dict:
    return _goals.get(creator, {"views_per_week": 0, "posts_per_week": 0, "engagement_pct": 0})

def set_goals(creator: str, goals: dict):
    _goals[creator] = goals
    _save()
