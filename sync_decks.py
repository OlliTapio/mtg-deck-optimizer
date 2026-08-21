"""Regenerate deck.json for every deck (or the ones passed) from decklist.txt.

This is the durable, environment-independent guarantee that deck.json matches
decklist.txt (issue #7). Run it locally via `make sync`, and in CI followed by
`git diff --exit-code decks/*/deck.json` to fail the build on any stale deck.json.

Usage:
    python3 sync_decks.py                     # regenerate all decks
    python3 sync_decks.py decks/wise_mothman  # regenerate specific deck(s)
    python3 sync_decks.py --check             # non-zero exit if any deck.json is stale
"""
import glob
import json
import os
import sys

from deck_to_json import deck_to_json

DECKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decks")


def deck_dirs(args):
    """Resolve the list of deck directories to process.

    Accepts deck dirs, decklist paths, or nothing (= all decks with a decklist).
    """
    if args:
        dirs = []
        for a in args:
            a = a.rstrip("/")
            if a.endswith("decklist.txt"):
                a = os.path.dirname(a)
            dirs.append(a)
        return dirs
    return sorted(
        os.path.dirname(p) for p in glob.glob(os.path.join(DECKS_DIR, "*", "decklist.txt"))
    )


def regenerate(deck_dir, check=False):
    """Regenerate one deck's deck.json. In check mode, don't write; report drift.

    Returns True if the file is (or was already) up to date, False if stale.
    """
    decklist = os.path.join(deck_dir, "decklist.txt")
    out_path = os.path.join(deck_dir, "deck.json")
    if not os.path.exists(decklist):
        print(f"  SKIP {deck_dir}: no decklist.txt", file=sys.stderr)
        return True

    data = deck_to_json(decklist)
    # Match deck_to_json.py's exact output (json.dump indent=2, no trailing newline)
    # so --check reports genuine content drift, not formatting noise.
    new_text = json.dumps(data, indent=2)

    if check:
        old_text = ""
        if os.path.exists(out_path):
            with open(out_path) as f:
                old_text = f.read()
        if old_text == new_text:
            return True
        print(f"  STALE {out_path}", file=sys.stderr)
        return False

    with open(out_path, "w") as f:
        f.write(new_text)
    print(f"  wrote {out_path}", file=sys.stderr)
    return True


def main():
    check = "--check" in sys.argv
    targets = [a for a in sys.argv[1:] if a != "--check"]

    dirs = deck_dirs(targets)
    ok = True
    for d in dirs:
        ok = regenerate(d, check=check) and ok

    if check and not ok:
        print(
            "\nOne or more deck.json files are out of sync with decklist.txt.\n"
            "Run `python3 sync_decks.py` and commit the result.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
