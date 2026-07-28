# Radha Battlecruiser — "2-4-7"

Commander: **Radha, Heir to Keld** ({R}{G}). Taps {G}; adds {R}{R} when she attacks — the reason
the curve is 2-4-7, not 3-5-7.

## Game plan: 2-4-7
The line, every game:
- **T2 — Commander.** Cast Radha (3 lands not needed; 2 lands + any + her). She taps {G} and adds
  {R}{R} when she attacks — she is the guaranteed "+ mana" that makes the jump work.
- **T3 — Ramp 2.** 3 lands + Radha's {G} = 4 mana → cast a 4-CMC ramp-2 (two lands to battlefield).
  Now on 5-6 lands. **This is the make-or-break play — the whole deck is built to hit it.**
- **T4 — Seven-drop (~6 lands + Radha's {G} = 7 mana).** Two lines:
  - **A) Hard-cast a bomb** — tap Radha for {G}, drop a game-ender. Radha can't attack this turn.
  - **B) Michelangelo Sneak line** — attack Radha unblocked, Sneak Michelangelo ({2}{G}{G}) returning
    her; his combat damage puts a **land + a 7-drop** from hand into play; replay Radha for {R}{G}.
    Nets Michelangelo + a cheated bomb + Radha + 1 land ahead, all for ~6 mana. **This is turn-4 ramp.**
    (Rules: Radha's attack {R}{R} empties before the declare-blockers Sneak — pay Sneak from lands,
    spend {R}{R} on an instant during attackers.)
- **T5+ — Spam bombs.** One 7-drop per turn. Battlecruiser: out-mana the table, don't race a low curve.

### Ramp consistency (hard requirement)
Must hit the T3 ramp-2 ~**85% by the second hand** (one mulligan). Maintained by **12 early ramp-2
enablers** (Sol Ring + the 4-CMC land-ramp spells + Undermountain Adventurer + Court of Bounty) =
84.6% by 2nd hand; Radha on top of that guarantees a mana source. **Never cut below 12 early
ramp-2 pieces.** Slow ramp (6+ CMC land-fetch) does NOT count — it doesn't enable the T3 jump.

## Rules (apply to every card decision)
1. **2-4-7 is the spine** — judge every card by whether it supports/abuses that curve.
2. **Prefer multiplayer / political cards** that scale in a 4-player pod: voting / Will of the
   Council, Council's Dilemma, Parley, Villainous Choice, Tempting Offer, Monarch, Initiative.
3. **7-mana cards must end or threaten to end the game** — never incremental value.
4. **One-sided / asymmetric removal only** — mass artifact/enchantment destruction; damage-to-all
   our fatties survive (Where Ancients Tread, Warstorm Surge, Star of Extinction / "5 to all").
   No symmetric wraths that set us back — we have the biggest board.
5. **Ramp must ramp 2+** (no 1-for-1 dorks/rocks). Green ramp fetches basics → run mostly basics.
6. **Manabase: mostly basics + single-target land hate.** No mass land denial (Bracket 3).
7. **Bracket 3 / budget:** no Game Changers, no 2-card combos; no card over €10; deck ~€50-55;
   synergy over goodstuff.
8. **RG core non-negotiable** — green owns land ramp; UR can't hit the curve.

## Deck-specific notes
- **Ideal keep:** 3 land / 2 bomb / 1 removal / 1 ramp. Mulligan to 6 occasionally is fine.
  (Ramp-2 hit-rate spec lives under "Ramp consistency" above.)
- **Haste matters** (Akroma's Memorial — owned/off-budget; Rhythm of the Wild) so ramped 7-drops
  attack immediately. 36 lands (~2.55/opener) is correct — more floods.
- **otag counts mislead — count these by hand:**
  - *Mass disruption (functional 6):* board-wipe otag catches only 4 (Avengers Disassembled,
    Chandra's Ignition, Vandalblast, Steel Hellkite). Add **Jaheira's Respite** (Fog — otagged
    ramp/tutor) and **Terastodon** (3× noncreature destroy) = 6 real pieces.
  - *Ramp:* analyzer shows ~16 but reliable **T3 early ramp-2 = 12** (see "Ramp consistency"). The
    other 3 ramp toward the *turn-4* slot, not T3: **Michelangelo** (turn-4 Sneak line — ramps a
    land + cheats a bomb, see T4), Regal Behemoth (6-CMC monarch doubler), Jaheira's Respite (fog,
    ramps only when attacked). Do NOT count these toward the 85% *T3* metric.

## Tooling / variants
- `decklist.txt` set codes are placeholders `(na) 0` (build-to list); tools resolve by name.
- Golgari (BG) variant: green ramp ports 1:1; swap red burn/haste for black recursion + tutors.
  Helms: Gilanra + Tormod (partner) or Old Stickfingers. Not built.
- Reference: archidekt.com/decks/23264535 ("Oops only battlecruisers").
