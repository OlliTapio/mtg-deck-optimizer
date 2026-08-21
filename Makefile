.PHONY: sync sync-check bundle

# Regenerate every deck.json from its decklist.txt (issue #7 sync guarantee).
sync:
	python3 sync_decks.py

# Fail if any deck.json is out of sync with its decklist.txt (used in CI).
sync-check:
	python3 sync_decks.py --check

# Build the static data bundle consumed by the web SPA.
bundle:
	python3 build_site_data.py
