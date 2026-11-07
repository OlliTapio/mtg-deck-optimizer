# MTG Deck Optimizer

Tools for Claude to analyze and improve Commander/EDH decks during conversations.

## Commands

```bash
# Pull a public deck from Archidekt into decks/<deck>/decklist.txt (+ source.json), optionally score it
python3 archidekt.py pull https://archidekt.com/decks/<id>/<slug> [--deck <folder>] [--synergy]
python3 archidekt.py pull decks/<deck>          # re-pull a deck that has a source.json
python3 archidekt.py pull --all                 # re-pull every deck with a source.json
python3 archidekt.py search "Deck name"         # find public decks

# Full deck analysis (types, curve, otag categories, template check)
python3 deck_analyzer.py decks/<deck>/decklist.txt

# Full oracle text for all cards
python3 deck_analyzer.py decks/<deck>/decklist.txt --oracle

# Instant vs sorcery speed interaction breakdown
python3 deck_analyzer.py decks/<deck>/decklist.txt --speed

# Cut candidates: low synergy + high mana value first, role cards (removal, ramp, draw) listed apart
python3 deck_analyzer.py decks/<deck>/decklist.txt --cuts

# Search oracle text across all cards
python3 deck_analyzer.py decks/<deck>/decklist.txt --search "rad counter"

# Synergy: themes, best pairs, commander fit, per-card totals, with the card text behind every score
python3 synergy.py decks/<deck>/decklist.txt
python3 synergy.py decks/<deck>/decklist.txt --card "Card Name"   # one card's partners (judge a swap)
python3 synergy.py decks/<deck>/decklist.txt --cuts               # cut candidates by synergy + mana value
python3 synergy.py decks/<deck>/decklist.txt --features           # what was read from each card
python3 synergy.py decks/<deck>/decklist.txt --save               # write decks/<deck>/synergy.json

# Known combos (Commander Spellbook): combos in the deck, near-misses, bracket flags
python3 combos.py decks/<deck>/decklist.txt [--almost 30] [--prices] [--json] [--refresh]

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

# Scryfall search examples with otags and common filters
python3 scryfall_search.py --search "otag:ramp t:creature cmc=2 id<=bug f:commander" --verbose
python3 scryfall_search.py --search "otag:mana-dork t:creature cmc<=2 id<=bug f:commander" --verbose
python3 scryfall_search.py --search "otag:board-wipe id<=bug f:commander cmc<=4" --verbose
python3 scryfall_search.py --search "otag:removal t:instant id<=bug f:commander cmc<=2" --verbose
python3 scryfall_search.py --search "t:creature o:'+1/+1 counter' cmc<=3 id<=bug f:commander" --verbose
python3 scryfall_search.py --search "t:land o:'{G}' o:'{U}' -t:basic eur<=5" --verbose
```

## Scryfall Search Syntax Quick Reference
- `id<=bug` — color identity within Sultai (BUG). Use `id<=rg`, `id<=wub`, etc.
- `f:commander` — legal in Commander format
- `cmc<=3` or `cmc=2` — converted mana cost filter
- `t:creature`, `t:instant`, `t:land` — type filter
- `o:'text'` — oracle text contains
- `eur<=10` — price filter in euros
- `-o:'text'` — exclude oracle text
- `-t:legendary` — exclude type
- `set:fin` — specific set code
- `otag:tag-name` — Scryfall community otags (see below)

### Common Scryfall otags
- `otag:ramp` — mana acceleration (dorks, rocks, land fetch)
- `otag:mana-dork` — creatures that tap for mana
- `otag:board-wipe` — mass removal
- `otag:removal` — targeted removal
- `otag:counterspell` — counter spells
- `otag:card-advantage` — card draw and value engines
- `otag:tutor` — search library effects
- `otag:recursion` — graveyard recursion
- `otag:evasion` — flying, unblockable, menace, etc.
- `otag:lifegain` — life gain effects
- `otag:graveyard-hate` — graveyard disruption
- `otag:mill` — mill effects
- `otag:proliferate` — proliferate effects

## Game Simulator Architecture

Game simulation is a core feature: use it to test mana bases, curves and matchups. Two layers, from simple to full multiplayer:

### 1. Auto-pilot (`auto_pilot.py`)
Heuristic AI plays a single deck vs 3 simulated opponents. Good for testing mana bases and curves. No card abilities or triggers.

### 2. Multiplayer engine (`multiplayer_game.py`, `game_orchestrator.py`)
2-4 real decks play against each other with proper turn order, combat, and priority. Use auto mode (`--ai auto` / `--auto`), which plays every deck with heuristics.

### Deprecated: LLM vs LLM games
LLM agents piloting decks against each other is deprecated and will be removed. Do not use or extend it, and do not launch subagents to pilot decks. This covers `codex_game.py`, `game_http_server.py`, `game_mcp_server.py`, `game_server.py`, `game_watch.py`, `game_viewer.html`, `multiplayer_game.py --ai llm` and `game_orchestrator.py` without `--auto`. These print a deprecation warning when run.

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

## Synergy calculator (`synergy.py`)
Reads keywords, types and triggers, tags each card with what it **produces** and what it **cares about**, and scores pairs where one feeds the other.
- A theme counts only when the deck has both a producer and a payoff (ten foretell cards with no cast-from-exile payoff score 0). Denser themes score more.
- Main theme x1.5, subtheme x1.25, pairs with the commander x2.
- Counter axes are separate: +1/+1, -1/-1, rad. Rad counters also count as mill. Proliferate feeds all of them.
- Regex reading of rules text misses unusual wording. Check surprising scores with `--card` / `--features` and the oracle text before trusting them.
- Known combos from Commander Spellbook add a pair bonus between every two pieces (2.0). Combos that win the game (damage, life loss, opponent mill, extra turns, "win the game") get an extra bonus that drops fast with the deck's target bracket: +6.0 in bracket 4, +2.1 in 3, +0.74 in 2, +0.26 in 1. Combo pieces are never cut candidates.
- Ramp scoring (spell // land MDFCs are land drops, not ramp):
  - Commander pair: base 1.0 for a 4-MV commander (+0.5 per MV above, max 2.5, 0 at MV 3 or less), x1.0 if the ramp costs <= commander MV - 2 (commander a turn early), x0.5 at MV - 1, 0 otherwise. Creature ramp x1.5. Then the x2 commander bonus.
  - Curve: 0.25 x (average MV - 2.5, capped 0..2) x number of 5+ MV spells, per ramp card.
  - Land ramp (lands onto the battlefield survive board wipes): +0.25 per expected turn above 5. Expected game length by bracket: 1 = 10 turns, 2 = 9, 3 = 7, 4 = 5.
- Protection (grants hexproof/shroud/indestructible/protection, phasing) pairs with the commander for 1.0 x commander dependence, then x2. Dependence = (commander's synergy / average card's synergy - 1) / 3, capped 0..1, +0.75 when the deck's CLAUDE.md names a commander-damage or voltron plan. Each protection card also gets 0.5 x dependence x the median card's synergy, so it competes with cards whose totals come from many pairs. Name the plan in the deck's CLAUDE.md win conditions so it is picked up.
- Repeatable producers weigh more: one-shots (instants/sorceries, "when ~ enters/dies", sacrifice ~, "enters with") x1.0; your-turn triggers, activated and static abilities x1.25; triggers that can fire on any player's turn x1.5. `--card` shows the factor.
- Proliferate is weak (x0.5) on a counter axis unless the deck has 8+ other producers of that counter (3+ for rad: rad sits on players and survives wipes), then full strength. With any rad producer in the deck, proliferate also counts as mill, since rad counters mill their holder.
- Proliferate also needs counters on the board: every card that puts down +1/+1, -1/-1 or rad counters pairs with every proliferate card (weight 0.5, sharing the counter theme's bonus). Proliferate cards don't pair with each other this way.
- A commander-damage plan makes the commander care about +1/+1 counters on itself, so counter producers pair with it.
- Card draw and selection get a base bonus scaled to the deck: draw (draws cards, impulse draw, card-advantage otag) 0.25 x median card synergy; selection only (scry, surveil, looting, look at the top) half that. Draw triggers and opponents drawing don't count.
- Reactive cards (noncreature targeted removal and counterspells, plus protection; not board wipes) lose 0.5 synergy each per card over 12 (14 for commander-damage decks).
- Never claim two cards synergise without running `synergy.py --card`, or reading both cards' oracle text.

## Combos (`combos.py`)
Asks Commander Spellbook's free API (backend.commanderspellbook.com) which combos the deck contains and which it almost contains.
- Every combo is flagged against the deck's bracket from its CLAUDE.md: two-card infinites are banned in brackets 1-2 and only allowed late in bracket 3.
- Near-misses are leads, not suggestions: check theme, bracket and the €10 budget before proposing one.

## Key Rules
- **Always run the tools** — never manually count card types, lands, or categories from decklist.txt. Use `deck_analyzer.py` for type breakdowns and `otag_fetcher.py` for functional categories. The decklist file is an Archidekt export; only the tools parse it correctly against Scryfall data.
- Always use Scryfall data and otags for card categorization — never trust manual tags in decklist files
- Parser tags are only reliable for deck membership status (Buy, noDeck, Maybeboard)
- Caches are committed to the repo so cloud sessions start warm: `cache/cards.json` (Scryfall card data), `cache/otags.json` (Scryfall otags), `cache/combos.json` (Commander Spellbook, keyed by the exact card list). Commit cache changes along with deck changes. Cached prices go stale: run `price_check.py` for current prices
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
- `source.json` — Written by `archidekt.py pull`: Archidekt deck id, URL, owner, bracket set on Archidekt (used when CLAUDE.md names no bracket)
- `synergy.json` — Generated by `synergy.py --save`: themes, pairs with reasons, per-card totals, cut ranking
- `CLAUDE.md` — Design decisions that can't be derived from the cards/tools
- `cuts.txt` — Cards removed and why (tracks owned cards for future reference)
