# The Wise Mothman

## Design Principles
- No generic goodstuff — every card should synergize with this deck's specific theme
- Win with style through synergistic loops, not raw power
- Bracket 3 — no instant-win infinite combos without board presence
- Budget: no single card over €10 (Scryfall EUR prices)

## Non-obvious Design Decisions
- Wave Goodbye chosen specifically because this deck's creatures always have +1/+1 counters (functionally one-sided)
- Tainted lands kept despite being conditional — Swamp count was increased to support them
- Stubborn Denial over more expensive counterspells — Ferocious is reliably online in this deck
- Conduit of Worlds over Raul — keeps mana open for instant-speed interaction
- Undead Alchemist was cut despite being on-theme — replacing combat damage with mill is anti-synergy with the counter beatdown plan

## Mulligan Strategy

Goal: cast Mothman turn 3-4. He costs {1}{B}{G}{U} — all 3 colors required.

### Auto-keep
- 3+ lands with all 3 colors (or 2 colors + fixer) and a ramp spell — cast Mothman turn 3 with a dork/signet, or turn 4 naturally.
- 2 lands + mana dork (Birds of Paradise, Devoted Druid, Incubation Druid) — dork turn 1-2, Mothman turn 3. The dream.
- 3 lands + counter doubler or proliferate creature (Hardened Scales, Winding Constrictor, Branching Evolution) — deploy engine before Mothman so his first attack immediately pays off.

### Good keep
- 3+ lands with 2 colors + 2 CMC ramp (Farseek, Nature's Lore, Rampant Growth) — the ramp finds the missing color and gets Mothman out turn 3-4.
- 2 lands + Sol Ring/Arcane Signet + action — fast mana into Mothman.
- 3 lands + Guardian Project or Fathom Mage + cheap creatures — card draw engine online before or alongside Mothman.

### Mulligan
- 1 land even with ramp — Mothman needs colored mana from lands, not just ramp artifacts.
- 2+ lands but only 1 color and no fixers — can't cast Mothman or most spells. The deck is heavily multicolor.
- No green sources — green is the primary color (47 pips). Most ramp, creatures, and counter synergy require green.
- All top-end, no early plays — Vigor + Agent Frank Horrigan + Triskelion does nothing before turn 6.

### Priority order for opening hand
1. Green-producing land (non-negotiable — enables ramp and most creatures)
2. Color fixing for B and U (Farseek/Nature's Lore find duals, fixing lands)
3. Mana dork or 2 CMC ramp — turn 3 Mothman is the ideal
4. Counter doubler (Hardened Scales, Winding Constrictor, Branching Evolution) — deploy before Mothman to maximize his first attack
5. Proliferate creature (Thrummingbird, Flux Channeler, Evolution Sage) — multiplies value after Mothman lands
6. Interaction/protection (Stubborn Denial, Swiftfoot Boots) — nice to have, not a keep reason

### Dream curves
**Aggro start:**
- T1: Forest, Birds of Paradise
- T2: Land, Winding Constrictor
- T3: Land, The Wise Mothman — attacks immediately next turn, doubled counters

**Value start:**
- T1: Land
- T2: Land, Farseek (find Breeding Pool/dual)
- T3: Land, Hardened Scales + Thrummingbird
- T4: The Wise Mothman — engine already online

### Key color notes
- Farseek and Nature's Lore can find Sunken Hollow, Hinterland Harbor, etc. — use them to fix the missing color
- Tainted lands need a Swamp — keep Swamp-producing lands in opening hand when possible
- Many tapped lands (Temples, Opulent Palace) — plan your first 3 turns carefully around tap timing

## Game Simulation Findings (2026-03-18)

### Performance: 3 LLM games, 0 wins (best: 2nd place T12)
- Commander online T4 consistently, rad counters pressure the whole table
- Winding Constrictor doubles rad counters — terrifying when combined with Thrummingbird proliferate
- Fathom Mage + counter doublers drew 6 cards in one shot (best single draw in any game)
- **Board wipes are devastating** — all +1/+1 counter investment lost instantly

### MVP Cards
- **Winding Constrictor** — doubled rad counters on all opponents, doubled +1/+1 growth
- **Fathom Mage** — evolved with counter doublers for 6 cards in one trigger
- **Thrummingbird** — proliferate on combat damage compounded every counter type

### Underperformers
- **Singularity Rupture** — board wipe that also milled Muldrotha's graveyard, actively helping the opponent
- **Vigor** — drawn late, too expensive to cast after board wipes
- **Reanimate** — nothing worth reanimating in first 5 turns

### Improvement Priorities
1. Add standalone threats that don't depend on counters (Herald of Secret Streams for unblockable)
2. Add board protection (Inspiring Call — draw + indestructible for creatures with counters)
3. Replace Karn's Bastion (colorless) with a colored dual — 3-color deck can't afford colorless lands
4. More cheap interaction to survive against Ureni's dragon army
