"""Card cache backed by Scryfall API. Stores full Scryfall JSON in cache/cards.json."""
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
import sys

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "cards.json")
SCRYFALL_NAMED = "https://api.scryfall.com/cards/named"
REQUEST_DELAY = 0.1
HEADERS = {'User-Agent': 'MTGDeckOptimizer/1.0', 'Accept': 'application/json'}

_last_request_time = 0.0


def _load_cache():
    """Load the JSON cache from disk."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_cache(cache):
    """Write the JSON cache to disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def _rate_limit():
    """Respect Scryfall 100ms rate limit."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    _last_request_time = time.time()


def _fetch_from_scryfall(name):
    """Fetch a card from Scryfall by exact name, falling back to fuzzy."""
    _rate_limit()

    # Handle split cards: Scryfall wants the full "A // B" name
    params = urllib.parse.urlencode({'exact': name})
    url = f"{SCRYFALL_NAMED}?{params}"

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            _rate_limit()
            params = urllib.parse.urlencode({'fuzzy': name})
            url = f"{SCRYFALL_NAMED}?{params}"
            req = urllib.request.Request(url, headers=HEADERS)
            try:
                with urllib.request.urlopen(req) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError:
                print(f"  WARNING: Card not found on Scryfall: {name}", file=sys.stderr)
                return None
        raise


def get_card(name):
    """Get full Scryfall data for a card. Uses cache, hits API only if needed.

    Returns the full raw Scryfall JSON dict, or None if not found.
    """
    cache = _load_cache()

    # Normalize key: lowercase for matching
    key = name.lower().strip()

    if key in cache:
        return cache[key]

    print(f"  Fetching from Scryfall: {name}", file=sys.stderr)
    data = _fetch_from_scryfall(name)
    if data:
        cache[key] = data
        _save_cache(cache)
    return data


def get_deck_cards(decklist_file):
    """Parse a decklist and fetch full Scryfall data for every card.

    Returns a list of dicts, each containing:
      - All fields from parser.py (name, count, set, tags, etc.)
      - 'scryfall': the full raw Scryfall JSON
    """
    from parser import parse_decklist

    parsed = parse_decklist(decklist_file)
    all_cards = []

    # Commander + deck cards
    card_list = parsed['deck'][:]
    if parsed['commander']:
        card_list.insert(0, parsed['commander'])

    for card in card_list:
        scryfall_data = get_card(card['name'])
        enriched = dict(card)
        enriched['scryfall'] = scryfall_data
        all_cards.append(enriched)

    return all_cards, parsed
