# Yuma, Proud Protector

## Design Principles
- **Bracket 2 (Core)** — see Bracket Rules below
- Naya (RGW) lands/landfall/graveyard deck
- Needs lands in graveyard fast to reduce Yuma's casting cost (8 CMC base, -1 per land in GY)
- Desert subtheme is central, not a "sub" theme: Deserts hitting graveyard create 4/2 Plant Warrior tokens with reach
- Dune Chanter is an essential enabler — turns ALL lands into Deserts, so every land sacrifice/mill triggers Yuma's token creation. Do not cut.
- Win condition: haste Plant tokens swinging for lethal
- No board wipes needed — we ARE the threat that needs answering
- Keep instant-speed interaction high to protect the plan
- Budget: no single card over €10

## Non-obvious Design Decisions
- Nahiri's Resolve (5 CMC RW enchantment) gives global haste AND blinks creatures for ETB re-triggers
- Desert Warfare returns sacrificed/milled Deserts to battlefield on end step — self-sustaining engine
- Zuran Orb is a finisher not lifegain — sac all lands, make tokens, swing with haste
- Splendid Reclamation loops with Zuran Orb for repeated mass landfall triggers
- Catharsis evoked for {R/W}{R/W} gives entire board haste for free
- Cactusfolk Sureshot gives trample + haste to 4+ power creatures at combat
- Yuma is the primary draw engine — every attack sacs a land and draws a card

## Mulligan Strategy

Goal: cast Yuma by turn 4-5. He costs {5}{R}{G}{W} minus 1 per land in graveyard.

### Auto-keep
- 3+ lands with a Harrow-type effect (Harrow, Springbloom Druid, Entish Restoration) — sacs land to GY (-1 cost) and ramps (+2 lands). Yuma costs 7 with 1 land in GY, castable turn 5.
- 3+ lands with mill/self-fill (Satyr Wayfinder, Aftermath Analyst, Dune Chanter, Winding Way, Life from the Loam) — dumps multiple lands to GY, Yuma could cost 4-5 by turn 5.
- 2 lands + 2 ramp spells in Naya colors.

### Good keep
- 4+ lands with any action — natural land drops plus find ways to fill GY.
- 2 lands + Lotus Cobra or Dryad of the Ilysian Grove — explosive mana acceleration.

### Mulligan
- 1 land even with ramp — too risky, need lands on battlefield AND in GY.
- All tapped lands, no ramp — too slow. Need at least 1 untapped source or Spelunking/Horizon Explorer.
- No green sources — can't cast most of the engine.
- All bombs, no engine — Omnath + Avenger + Phylath does nothing for 6 turns.

### Priority order for opening hand
1. Green-producing land (non-negotiable)
2. Land-sac ramp (Harrow, Springbloom, Entish) — ramp + reduce Yuma cost
3. Self-mill (Satyr Wayfinder, Aftermath Analyst, Winding Way) — fills GY fast
4. Extra land drop (Dryad, Oracle, Prismatic Undercurrents) — accelerates
5. Interaction — nice to have, not a keep reason

### Dream curve
- T1: Land
- T2: Land, Satyr Wayfinder (mill 2 lands to GY → Yuma costs 6)
- T3: Land, Harrow (sac land to GY → Yuma costs 5, you have 4 lands)
- T4: Land, cast Yuma for 5 mana

## Game Simulation Findings (2026-03-18)

### Performance: 3 LLM games, 1 win (won pod without Ureni)
- Dune Chanter is THE make-or-break card — turns every land sac into a 4/2 Plant token
- Zuran Orb + Splendid Reclamation + Dune Chanter = mass token generation + mass landfall
- Overwhelming Stampede (+5/+5 trample to all) was the game-winning finisher
- **Green drought T1-3 is recurring** — deserts don't produce green, Lotus Cobra needs green to cast
- Commander was flung by Brion twice in one game — needs protection

### MVP Cards
- **Dune Chanter** — makes all lands Deserts, every sacrifice triggers Yuma's token creation
- **Zuran Orb** — free sacrifice outlet, 2 life per land + Desert tokens with Dune Chanter
- **Lotus Cobra** — landfall mana enables explosive turns with Harrow/Springbloom

### Underperformers
- **Brass's Tunnel-Grinder** — 3 mana for minimal value, Discover side never flipped
- **Embrace the Unknown** — impulse draw never found a window (always had better 3-mana plays)
- **Stroke of Midnight** — sat in hand, never had the spare 3 mana at instant speed

### Improvement Priorities
1. More untapped green sources early — replace a tapped Desert with a basic Forest
2. Add commander protection (Swiftfoot Boots, Lightning Greaves) — Brion stole and flung Yuma TWICE
3. Consider Bountiful Landscape or similar for smoother early green access
4. The land-sacrifice engine is the win condition — protect Dune Chanter too (only 1 copy)
