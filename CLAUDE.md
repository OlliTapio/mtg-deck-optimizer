# MTG Deck Optimizer

Tools for Claude to analyze and improve Commander/EDH decks during conversations.

## Commands

```bash
# Full deck analysis (types, curve, otag categories, template check)
python3 deck_analyzer.py decks/<deck>/decklist.txt

# Full oracle text for all cards
python3 deck_analyzer.py decks/<deck>/decklist.txt --oracle

# Instant vs sorcery speed interaction breakdown
python3 deck_analyzer.py decks/<deck>/decklist.txt --speed

# Cut candidates sorted by CMC, flagging cards with no otags
python3 deck_analyzer.py decks/<deck>/decklist.txt --cuts

# Search oracle text across all cards
python3 deck_analyzer.py decks/<deck>/decklist.txt --search "rad counter"

# Simulate opening hands
python3 hand_simulator.py decks/<deck>/decklist.txt [n_hands]

# Check prices for entire deck or specific cards
python3 price_check.py --deck decks/<deck>/decklist.txt
python3 price_check.py --cards "Card Name" "Card Name"

# Fetch/view Scryfall otags for deck cards (cached in cache/otags.json)
python3 otag_fetcher.py decks/<deck>/decklist.txt
python3 otag_fetcher.py --card "Card Name"
python3 otag_fetcher.py decks/<deck>/decklist.txt --refresh  # force re-fetch

# Export deck to JSON with full Scryfall data + otags
python3 deck_to_json.py decks/<deck>/decklist.txt -o decks/<deck>/deck.json

# Look up a single card with full oracle text
python3 scryfall_search.py --lookup "Card Name" --verbose

# Search Scryfall with raw query
python3 scryfall_search.py --search "id<=bug f:commander o:proliferate" --verbose
```

## Key Rules
- Always use Scryfall data and otags for card categorization — never trust manual tags in decklist files
- Parser tags are only reliable for deck membership status (Buy, noDeck, Maybeboard)
- Caches: `cache/cards.json` (Scryfall card data), `cache/otags.json` (Scryfall otags)
- Respect Scryfall rate limits: 100ms between requests (10 req/s max)
- Budget: no single card over €10
- No goodstuff — suggestions must synergize with the specific deck's theme
- Use Command Zone template (2025 New Era) as guideline for category counts

## Deck folder structure
Each deck lives in `decks/<name>/` with:
- `decklist.txt` — Archidekt export format (source of truth for what's in the deck)
- `deck.json` — Generated full deck data with Scryfall data + otags
- `CLAUDE.md` — Design decisions that can't be derived from the cards/tools
- `cuts.txt` — Cards removed and why (tracks owned cards for future reference)
