"""
ideas_store.py — Stockage des idées de contenu par créateur
Env var Render : IDEAS_JSON
"""
import json, os
from pathlib import Path

IDEAS_FILE = "ideas.json"
_cache: dict | None = None

def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if Path(IDEAS_FILE).exists():
        with open(IDEAS_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)
        return _cache
    env = os.environ.get("IDEAS_JSON")
    if env:
        _cache = json.loads(env)
        _flush()
        return _cache
    _cache = {}
    return _cache

def _flush():
    with open(IDEAS_FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, indent=2, ensure_ascii=False)

def get_ideas(creator: str) -> list:
    return _load().get(creator, [])

def add_idea(creator: str, idea: dict):
    global _cache
    data = _load()
    data.setdefault(creator, []).append(idea)
    _cache = data
    _flush()

def update_idea_decision(creator: str, idea_id: str, decision: str):
    global _cache
    data = _load()
    for idea in data.get(creator, []):
        if idea.get("id") == idea_id:
            idea["decided"] = decision
            break
    _cache = data
    _flush()

def export_all() -> dict:
    return _load()
