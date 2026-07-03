# The Wise Mothman

## Win Conditions (in order)
1. **Commander damage** — Mothman grows via +1/+1 counters each attack (doubled by Hardened Scales, Branching Evolution, Corpsejack Menace). A flying beater with few blockers reaches 21 commander damage in 3-4 swings.
2. **Combat beatdown** — the whole board grows from counter doublers + proliferate. Swing wide with big creatures.
3. **Combo A: Walking Ballista + Vigor + counter doubler** — Ballista pings itself, Vigor replaces damage with +1/+1 counters, counter doubler (Hardened Scales/Branching Evolution/Corpsejack) makes it grow each loop. Infinite damage to any target.
4. **Combo B: Fathom Mage + Mothman + Psychic Corrosion** — Mothman's +1/+1 counters trigger Fathom Mage draws, Psychic Corrosion mills opponents on each draw. Infinite mill.

Rad counters are **incidental** — chip damage and mill disruption, NOT the primary plan.

## Design Principles
- No generic goodstuff — every card should synergize with this deck's specific theme
- Win with style through synergistic loops, not raw power
- Bracket 3 — no instant-win infinite combos without board presence
- Budget: no single card over €10 (Scryfall EUR prices)

## Non-obvious Design Decisions
- Wave Goodbye chosen specifically because this deck's creatures always have +1/+1 counters (functionally one-sided)
- Tainted Isle/Wood cut (Round 7): they produced only colorless without a Swamp in play — too fragile. Replaced with GU/BG slow + bond lands for unconditional fixing. This also relaxed the old "keep Swamp count high" constraint, since the only remaining Swamp-dependent lands (Drowned Catacomb, Woodland Cemetery) each have a Forest/Island fallback.
- Manabase deliberately GU-skewed: green (48 pips, primary) and blue (24 pips, double-pip on Pensive/Wave Goodbye) were under-sourced vs black. Land color sources rebalanced to ~G22/U19/B20 to match pip share. GU duals are also the cheapest side of every land cycle.
- Only 4 always-tapped lands kept, each for ETB value/fixing (Bojuka Bog, Opulent Palace, Path of Ancestry, Fetid Pools). (Mortuary Mire was the 5th, cut in Round 8 for a spell//land MDFC.) Pure-filler taplands (Haunted Mire, Tangled Islet) were cut for untapped/conditional lands.
- Stubborn Denial over more expensive counterspells — Ferocious is reliably online in this deck
- Conduit of Worlds over Raul — keeps mana open for instant-speed interaction
- Undead Alchemist was cut despite being on-theme — replacing combat damage with mill is anti-synergy with the counter beatdown plan
- Spell//land MDFCs added by cutting 3 black lands (Mortuary Mire + 2x Swamp), not spells — they count as land drops when mana-light but as **nonland cards** in library/graveyard (CR 712.14: characteristics off the battlefield are the front face's), so being milled feeds Mothman's +1/+1 trigger and rad-counter life loss. Cuts protected blue (tightest color) and trimmed oversupplied black; net land sources G +2 / U ±0 / B −1.
  - Revitalizing Repast // Old-Growth Grove ({B/G}) — instant: +1/+1 counter + indestructible. Protects Mothman AND feeds doublers/proliferate/Fathom Mage. Back taps B or G.
  - Bridgeworks Battle // Tanglespan Bridgeworks ({2}{G}) — sorcery: +2/+2 then fight. Removal leveraging the deck's big counter creatures. Back taps G.
  - Boggart Trawler // Boggart Bog ({2}{B}) — Goblin, ETB exile a graveyard. Kept Bojuka Bog alongside it: the deck feeds its own graveyard (Reanimate/World Shaper), so two GY-exile effects give control over when/whose yard gets hit. Reanimatable as a creature. Back taps B.
  - Mortuary Mire cut over Bojuka Bog — it was the slowest recursion (tapped, returns to top of library not hand, one-shot); Boggart Trawler is now recurable via Reanimate/Evolution Witness/Unnatural Restoration anyway.
  - Caveat: the deck's recursion is permanent-only (Unnatural Restoration/Evolution Witness return permanents; Reanimate creatures; Jetsam hits opponents' yards). So Repast (instant) and Bridgeworks (sorcery) are one-and-done once used or milled — acceptable, since milling them still makes Mothman counters.

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
- Farseek finds Island/Swamp-typed lands (basics or duals like Sunken Hollow, Turbulent Wilderness); Nature's Lore finds any Forest-typed land incl. duals; Sakura-Tribe Elder ("Steve") finds basic lands only (plus it chump-blocks and ramps) — use them to fix the missing color
- Green is primary (48 pips) but propped up partly by dorks/ramp; still prioritize a green land T1 for Birds/Incubation Druid
- Slow lands (Dreamroot Cascade, Deathcap Glade) are tapped T1-2 but untapped from T3 — fine for the T3-4 Mothman plan; lead on basics/dorks early
- Rejuvenating Springs enters untapped in any real multiplayer game (2+ opponents)

## Maybeboard
- Karn's Bastion — colorless proliferate land, future upgrade
- Bane of Progress — mass artifact/enchantment wipe that enters with a +1/+1 counter per permanent destroyed (on-theme). Sideboard-style answer vs artifact/enchantment-heavy pods.
- High Score — counter/draw payoff

