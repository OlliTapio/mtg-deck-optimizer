# Brigid, Clachan's Heart // Brigid, Doun's Mind

## Commander
Brigid, Clachan's Heart — {2}{W} 3/2 Kithkin Warrior. ETB or transform-in: create a 1/1 GW Kithkin token. At first main phase, pay {G} to transform.
Brigid, Doun's Mind — 3/2 Kithkin Soldier. {T}: Add X {G} or X {W} where X = other creatures you control. At first main phase, pay {W} to transform back.

Brigid flips every turn for 1 mana, making a Kithkin token on each front-face entry AND generating massive mana from the back face.

## Bracket
1 (Exhibition) — ultra-casual, theme-focused. No Game Changers, no intentional 2-card infinite combos, no mass land denial, no extra-turn cards. Every nonland card is Kithkin, Changeling, has kithkin/changeling in Scryfall art tags, or is Lorwyn-block equipment.

## Theme
GW Kithkin tribal go-wide. Flood the board with Kithkin through Brigid tokens, Militia's Pride attack triggers, Clachan Festival, Ajani, Kinbinding, and Cloudgoat Ranger. Pump with Wizened Cenn, Light from Within, Mirror Entity, and Kinbinding. Protect with Selfless Safewright (flash convoke, hexproof + indestructible for all Kithkin).

## Design Principles
- Every card must be Kithkin, Changeling, have kithkin/changeling in Scryfall art tags, or be Lorwyn equipment
- Budget: no single card over €10
- No conventional ramp (Sol Ring etc.) — Brigid's back side IS the ramp engine
- Low curve (avg 2.82 CMC) compensates for limited ramp
- Obsidian Battle-Axe auto-equips to Brigid (Warrior) giving +2/+1 and haste on recast

## Known Issues
- Ramp: only 2 sources (Brigid herself + Springleaf Parade) — if Brigid is removed repeatedly, mana dries up
- Card draw: limited to Realmwalker, Eclipsed Kithkin, Kithkin Mourncaller, Surge of Thoughtweft, Ajani
- Board wipes: zero — intentional (we're the board-wide army), but vulnerable to opponents' wipes. Morningtide's Light and Selfless Safewright are the recovery/protection tools
- 35 lands is tight but the low curve and Brigid's mana generation should support it

## Mulligan Strategy

Goal: cast Brigid turn 3, start generating tokens and mana immediately.

### Auto-keep
- 3+ lands (at least 1 Plains, 1 Forest or GW dual) + 1-2 drop Kithkin — Brigid turn 3, start building board turn 1-2.
- 2 lands including a green source + multiple 1-2 drops — curve out aggressively, Brigid turn 3 off natural land drops.
- Any hand with Temple Garden or Command Tower + 2 other lands — color-fixed, cast anything.

### Good keep
- 3 lands + Wizened Cenn or Light from Within — deploy anthem before going wide.
- 2 lands + Realmwalker or Eclipsed Kithkin — card advantage engine to find more gas.
- 3 lands + Militia's Pride + creatures — attack triggers generate free tokens.

### Mulligan
- 1 land — even with low curve, need lands for Brigid on turn 3.
- No green source and no fixing — can't transform Brigid, losing half her value.
- All 4+ drops — the deck wins by curving out, not by landing bombs.
- All noncreature spells — equipment and enchantments need bodies to matter.

### Priority order for opening hand
1. Plains (cast most creatures and Brigid)
2. Green source (transform Brigid, cast green Kithkin)
3. 1-2 drop Kithkin (start building the board immediately)
4. Anthem (Wizened Cenn, Light from Within) — deploy before going wide
5. Equipment (Obsidian Battle-Axe gives Brigid haste on recast)
6. Interaction — nice to have, not a keep reason

### Dream curves
**Aggro start:**
- T1: Plains, Goldmeadow Harrier
- T2: Forest, Wizened Cenn (Harrier is now 2/2)
- T3: Land, Brigid — makes a token, two Kithkin buffed by Cenn
- T4: Transform Brigid (mana), flip back (token), play more threats

**Value start:**
- T1: Land, Cenn's Tactician
- T2: Land, Realmwalker (choose Kithkin — cast from top)
- T3: Land, Brigid + cast Kithkin from library top
- T4: Flip Brigid for mana, deploy multiple creatures

## Game Simulation Findings (2026-03-18)

### Performance: 2 LLM games, 0 wins (best: 3rd place T10)
- Go-wide strategy works early — Mirror Entity turned 7 tokens into 4/4s for 20 damage
- Brigid's flip-for-tokens + flip-for-mana engine generates 1 token per turn cycle reliably
- **Folds to board wipes** — one Akroan War Chapter II destroyed the entire board
- **Folds to flyers** — no answers to Ureni's dragon army or Mothman's flying creatures
- 35 lands is too few (1.8 average mulligans across simulations)

### MVP Cards
- **Mirror Entity** — all creatures become X/X with all types, enables lethal alpha strikes
- **Wizened Cenn** — +1/+1 anthem is the backbone of every attack
- **Cloudgoat Ranger** — 3 tokens on ETB rebuilds board quickly

### Underperformers
- **Mirrormind Crown** — 4-mana equipment never equipped, too slow
- **Springleaf Parade** — competed for same mana as board development
- **Dundoolin Weaver** — ETB irrelevant (no targets), died to Akroan War

### Improvement Priorities
1. **Add 2-3 more lands** (35 → 37-38) — 1.8 avg mulligans is worst in portfolio
2. Add board protection (Rootborn Defenses — populate + indestructible)
3. Add reach/flying answers (Sandsteppe Outcast? Or equipment with reach)
4. Replace Mirrormind Crown with Swiftfoot Boots for commander protection

### Round 2 Findings (confirmed)
- Mulliganed to 5 AGAIN (1 land on 7-card hand). 35 lands is not enough — confirmed across 4 games
- Akroan War Chapter II destroyed the board AGAIN (8 creatures → 2). Board protection is mandatory
- Cloudgoat Ranger stranded in hand at 5 CMC — never hit 5 mana. Curve too high for 35 lands
- Dundoolin Weaver confirmed underperformer — ETB fizzled, vanilla body

## Origin
Custom build — all Lorwyn/Shadowmoor/Eclipsed Lorwyn Kithkin tribal
