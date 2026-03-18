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

# Simulate a game vs simulated opponents (auto-pilot heuristic)
python3 game_simulator.py decks/<deck>/decklist.txt [--opponents aggro,midrange,control] [--seed 42] [--max-turns 15]

# Auto-pilot game (heuristic AI plays the deck, no interaction needed)
python3 auto_pilot.py decks/<deck>/decklist.txt [--seed 42] [--max-turns 15]

# Multiplayer game: 2-4 real decks play against each other
# Auto mode (heuristic AI for all players):
python3 game_orchestrator.py decks/<a>/decklist.txt decks/<b>/decklist.txt decks/<c>/decklist.txt decks/<d>/decklist.txt --auto --seed 42 --max-turns 12
# Multiplayer with N real decks (auto-pilot):
python3 multiplayer_game.py decks/<a>/decklist.txt decks/<b>/decklist.txt --ai auto --seed 42 --max-turns 12

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

## Game Simulator Architecture

Three layers of game simulation, from simple to full LLM:

### 1. Auto-pilot (`auto_pilot.py`)
Heuristic AI plays a single deck vs 3 simulated opponents. Good for testing mana bases and curves. No card abilities or triggers.

### 2. Multiplayer engine (`multiplayer_game.py`, `game_orchestrator.py`)
2-4 real decks play against each other with proper turn order, combat, and priority. Auto mode uses heuristics. The orchestrator provides per-player state snapshots with full oracle text and trigger detection.

### 3. LLM multiplayer (subagent-driven)
Claude subagents pilot each deck. The flow:
1. Launch one persistent Agent per player — give it the deck's CLAUDE.md and opening hand
2. The main conversation acts as engine + judge
3. Each turn: run `game_orchestrator.py` to produce state snapshots, SendMessage each agent with their snapshot
4. Agent responds with an action (e.g. `cast Cultivate`, `attack all -> Muldrotha`)
5. Engine resolves the action, detects triggers, updates state
6. If an agent says `JUDGE: <question>`, the game pauses for the judge to rule on complex interactions
7. Agents can set auto-skip if they have no instant-speed interaction (hidden from other players)

Key design: **Players propose, Judge validates, Engine executes.** The engine handles zones/mana/combat math. Players see oracle text and propose creative plays. The judge validates against oracle text before the engine commits.

## Commander Bracket Rules (as of February 2026)

Each deck specifies its bracket in its CLAUDE.md. Never suggest cards that violate the deck's bracket restrictions.

### Bracket 1 (Exhibition)
- Ultra-casual, theme-focused play
- No Game Changers, no intentional two-card infinite combos, no mass land denial, no extra-turn cards
- Games last 9+ turns

### Bracket 2 (Core)
- Approximately precon-level power
- No Game Changers, no intentional two-card infinite combos, no mass land denial
- Extra-turn cards in low quantities only, not chained
- Games last 8+ turns

### Bracket 3 (Upgraded)
- Stronger than precons, souped-up decks
- Up to three Game Changers allowed
- No early-game two-card infinite combos (first ~6 turns), no mass land denial
- Games last 6+ turns

### Bracket 4 (Optimized)
- High-powered Commander, no restrictions beyond banned list
- Games may end turn 4+

### Game Changers List (banned in Brackets 1–2, max 3 in Bracket 3)
- **White:** Drannith Magistrate, Enlightened Tutor, Serra's Sanctum, Smothering Tithe, Teferi's Protection, Humility
- **Blue:** Cyclonic Rift, Force of Will, Fierce Guardianship, Rhystic Study, Thassa's Oracle, Mystical Tutor, Narset Parter of Veils, Intuition, Consecrated Sphinx
- **Black:** Bolas's Citadel, Demonic Tutor, Imperial Seal, Opposition Agent, Tergrid God of Fright, Vampiric Tutor, Ad Nauseam, Necropotence, Orcish Bowmasters, Notion Thief, Braids Cabal Minion
- **Red:** Jeska's Will, Underworld Breach, Gamble
- **Green:** Survival of the Fittest, Gaea's Cradle, Worldly Tutor, Crop Rotation, Seedborn Muse, Natural Order
- **Multicolor:** Grand Arbiter Augustin IV, Aura Shards, Coalition Victory
- **Colorless/Land:** Ancient Tomb, Chrome Mox, The One Ring, The Tabernacle at Pendrell Vale, Grim Monolith, Lion's Eye Diamond, Mox Diamond, Mana Vault, Glacial Chasm, Mishra's Workshop, Field of the Dead, Panoptic Mirror, Farewell, Biorhythm, Gifts Ungiven

## Key Rules
- **Always run the tools** — never manually count card types, lands, or categories from decklist.txt. Use `deck_analyzer.py` for type breakdowns and `otag_fetcher.py` for functional categories. The decklist file is an Archidekt export; only the tools parse it correctly against Scryfall data.
- Always use Scryfall data and otags for card categorization — never trust manual tags in decklist files
- Parser tags are only reliable for deck membership status (Buy, noDeck, Maybeboard)
- Caches: `cache/cards.json` (Scryfall card data), `cache/otags.json` (Scryfall otags)
- Respect Scryfall rate limits: 100ms between requests (10 req/s max)
- Budget: no single card over €10
- No goodstuff — suggestions must synergize with the specific deck's theme
- Use Command Zone template (2025 New Era) as guideline for category counts

## Template & Curve Enforcement
- **Defend the template** — resist changes that move category counts away from the Command Zone template targets unless there's a specific, articulated reason (e.g. commander ability compensates for a category, or the deck's strategy genuinely requires deviation). Push back on swaps that weaken underrepresented categories.
- **Mana curve must match commander and abilities** — after any swap, check that the mana curve supports the deck's game plan. A deck with a 5CMC commander needs enough early ramp to cast it on curve. Evoke/cost-reduction commanders can tolerate higher average CMC. Flag swaps that raise average CMC without adding proportional value.
- **Run deck_analyzer.py after every decklist change** — verify the template check, mana curve, and category counts still look healthy. If a swap pushes a category below template minimums, flag it.

## Bracket Synergy Checks
- **Every card suggestion must fit the deck's bracket** — check the deck's CLAUDE.md for its bracket, then verify the suggested card doesn't violate bracket restrictions (Game Changers list, combo density, power level).
- **Synergy over power** — cards should synergize with the specific commander's abilities and the deck's stated theme, not just be generically strong. A card that's powerful but off-theme is worse than a slightly weaker card that enables the deck's core game plan.
- **Flag bracket drift** — if accumulated swaps are pushing a deck toward a higher bracket (more tutors, more efficient combos, stronger individual cards), warn about bracket creep even if no single card violates the rules.

## Deck folder structure
Each deck lives in `decks/<name>/` with:
- `decklist.txt` — Archidekt export format (source of truth for what's in the deck)
- `deck.json` — Generated full deck data with Scryfall data + otags
- `CLAUDE.md` — Design decisions that can't be derived from the cards/tools
- `cuts.txt` — Cards removed and why (tracks owned cards for future reference)
