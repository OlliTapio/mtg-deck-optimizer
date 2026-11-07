# MTG Deck Optimizer

Tools I use with Claude to track my Commander (EDH) decks: check them for updates and prices,
and work out what to change.

**What I learned:** LLMs are bad at seeing card synergy directly from a decklist. They miss real
interactions and invent ones that don't exist. So the model never judges synergy unaided.
It calls tools that compute the evidence and reasons from that:

- **Archidekt pull:** public decks are pulled straight into the repo's decklist format
- **Card data:** full rules text and Scryfall's community function tags ("otags") for every
  card, cached locally
- **Deck analysis:** card types, mana curve, cut candidates, instant- vs sorcery-speed
  interaction, and search across the deck's rules text
- **Synergy:** keywords, types and triggers are read from every card to score which cards feed
  each other, with the card text behind every score. Cut candidates combine low synergy with
  high mana value
- **Combos:** known combos and near-misses from [Commander Spellbook](https://commanderspellbook.com),
  checked against the deck's bracket
- **Simulation:** opening hands, games against simulated opponents, and multiplayer games
  between real decks played by a rule-based autopilot
- **LLM vs LLM (deprecated):** a game server (HTTP and MCP) where agents each pilot a deck against
  the others. It will be removed; use the autopilot simulations instead.

## Usage

```bash
python3 archidekt.py pull https://archidekt.com/decks/<id> --synergy   # pull a public deck and score it
python3 deck_analyzer.py decks/<deck>/decklist.txt            # full analysis
python3 deck_analyzer.py decks/<deck>/decklist.txt --cuts     # cut candidates
python3 synergy.py decks/<deck>/decklist.txt                  # synergy report
python3 synergy.py decks/<deck>/decklist.txt --card "Hardened Scales"
python3 deck_analyzer.py decks/<deck>/decklist.txt --search "proliferate"
python3 combos.py decks/<deck>/decklist.txt                   # known combos
python3 hand_simulator.py decks/<deck>/decklist.txt 1000      # opening hands
python3 game_simulator.py decks/<deck>/decklist.txt --opponents aggro,midrange,control
python3 price_check.py --deck decks/<deck>/decklist.txt
python3 otag_fetcher.py decks/<deck>/decklist.txt
```

All commands are in [CLAUDE.md](CLAUDE.md), which is also how Claude finds them.
