"""
csv_parser.py — Parse les exports CSV de chaque plateforme social
"""
import csv
import io
import datetime

def _rows(content: str):
    """Lit un CSV (détecte séparateur , ou ;)."""
    sample = content[:2048]
    sep = ';' if sample.count(';') > sample.count(',') else ','
    reader = csv.DictReader(io.StringIO(content), delimiter=sep)
    return list(reader)

def _int(val):
    try: return int(str(val).replace(',','').replace(' ','').replace('\xa0','') or 0)
    except: return 0

def _date(val):
    """Normalise n'importe quel format de date en YYYY-MM-DD."""
    val = str(val).strip()
    for fmt in ('%Y-%m-%d','%d/%m/%Y','%m/%d/%Y','%d-%m-%Y','%Y/%m/%d','%b %d, %Y','%d %b %Y'):
        try: return datetime.datetime.strptime(val, fmt).strftime('%Y-%m-%d')
        except: pass
    return val

def parse_youtube(rows):
    """YouTube Studio → Analytiques → Export (par jour)."""
    results = []
    for r in rows:
        date = _date(r.get('Date') or r.get('date') or '')
        if not date: continue
        results.append({
            'plateforme':   'YouTube',
            'date':         date,
            'titre':        '—',
            'format':       'Video',
            'vues':         _int(r.get('Views') or r.get('Vues') or r.get('views') or 0),
            'reach':        _int(r.get('Views') or r.get('Vues') or 0),
            'abonnes':      _int(r.get('Subscribers') or r.get('Abonnés') or 0),
            'likes':        _int(r.get('Likes') or 0),
            'commentaires': _int(r.get('Comments') or r.get('Commentaires') or 0),
            'partages':     0,
            'sauvegardes':  0,
        })
    return results

def parse_instagram(rows):
    """Meta Business Suite → Insights → Export."""
    results = []
    for r in rows:
        date = _date(r.get('Date') or r.get('date') or '')
        if not date: continue
        results.append({
            'plateforme':   'Instagram',
            'date':         date,
            'titre':        r.get('Title') or r.get('Titre') or '—',
            'format':       r.get('Type') or r.get('Format') or 'Post',
            'vues':         _int(r.get('Impressions') or r.get('Impressions totales') or 0),
            'reach':        _int(r.get('Reach') or r.get('Portée') or 0),
            'abonnes':      _int(r.get('Followers') or r.get('Abonnés') or 0),
            'likes':        _int(r.get('Likes') or 0),
            'commentaires': _int(r.get('Comments') or r.get('Commentaires') or 0),
            'partages':     _int(r.get('Shares') or r.get('Partages') or 0),
            'sauvegardes':  _int(r.get('Saves') or r.get('Sauvegardes') or 0),
        })
    return results

def parse_facebook(rows):
    """Meta Business Suite → Insights → Export page."""
    results = []
    for r in rows:
        date = _date(r.get('Date') or r.get('date') or '')
        if not date: continue
        results.append({
            'plateforme':   'Facebook',
            'date':         date,
            'titre':        r.get('Title') or r.get('Message') or '—',
            'format':       'Post',
            'vues':         _int(r.get('Impressions') or r.get('Post Impressions') or 0),
            'reach':        _int(r.get('Reach') or r.get('Post Reach') or 0),
            'abonnes':      _int(r.get('Fans') or r.get('Page Likes') or 0),
            'likes':        _int(r.get('Reactions') or r.get('Likes') or 0),
            'commentaires': _int(r.get('Comments') or r.get('Commentaires') or 0),
            'partages':     _int(r.get('Shares') or r.get('Partages') or 0),
            'sauvegardes':  0,
        })
    return results

def parse_tiktok(rows):
    """TikTok Studio → Analytiques → Télécharger."""
    results = []
    for r in rows:
        date = _date(r.get('Date') or r.get('date') or '')
        if not date: continue
        results.append({
            'plateforme':   'TikTok',
            'date':         date,
            'titre':        r.get('Video') or r.get('Title') or '—',
            'format':       'Vidéo courte',
            'vues':         _int(r.get('Video views') or r.get('Views') or r.get('Vues') or 0),
            'reach':        _int(r.get('Video views') or r.get('Views') or 0),
            'abonnes':      _int(r.get('Followers') or r.get('Abonnés') or 0),
            'likes':        _int(r.get('Likes') or 0),
            'commentaires': _int(r.get('Comments') or r.get('Commentaires') or 0),
            'partages':     _int(r.get('Shares') or r.get('Partages') or 0),
            'sauvegardes':  0,
        })
    return results

def parse_snapchat(rows):
    """Snap Ads Manager → Rapports."""
    results = []
    for r in rows:
        date = _date(r.get('Date') or r.get('date') or '')
        if not date: continue
        results.append({
            'plateforme':   'Snapchat',
            'date':         date,
            'titre':        r.get('Story') or r.get('Content') or '—',
            'format':       'Story',
            'vues':         _int(r.get('Impressions') or r.get('Views') or 0),
            'reach':        _int(r.get('Reach') or r.get('Unique views') or 0),
            'abonnes':      _int(r.get('Subscribers') or 0),
            'likes':        0,
            'commentaires': 0,
            'partages':     _int(r.get('Shares') or 0),
            'sauvegardes':  _int(r.get('Screenshots') or 0),
        })
    return results

PARSERS = {
    'YouTube':   parse_youtube,
    'Instagram': parse_instagram,
    'Facebook':  parse_facebook,
    'TikTok':    parse_tiktok,
    'Snapchat':  parse_snapchat,
}

def parse_csv(platform: str, content: str) -> list:
    parser = PARSERS.get(platform)
    if not parser:
        return []
    rows = _rows(content)
    return parser(rows)
