# Brion Stoutarm — Threaten & Throw

## Commander
Brion Stoutarm — {2}{R}{W} 4/4 Giant Warrior, Lifelink. {R}, {T}, Sacrifice another creature: Deal damage equal to the sacrificed creature's power to target player or planeswalker. The lifelink means you gain life equal to the damage dealt.

## Bracket
2 (Core) — no Game Changers, no infinite combos, no mass land denial, no extra turns. The deck is powerful but linear and interactive — opponents always see it coming.

## Theme
Boros threaten-and-throw. Steal opponents' creatures with Threaten effects, attack with them, then sacrifice them to Brion to fling them at someone's face. Gain massive life from Brion's lifelink. Repeat.

## Design Principles
- 21 steal effects ensure you always have something to throw
- Permanent-based sacrifice outlets (Goblin Bombardment, Altar of Dementia, Makeshift Munitions) as backup when Brion is unavailable
- Fling effects (Fling, Thud, Kazuul's Fury, Soul's Fire) for redundancy
- Lifegain payoffs (Well of Lost Dreams, Sunbond, Cradle of Vitality) turn Brion's lifelink into card draw and power
- Budget: no single card over €10

## Key Synergies
- **Steal + Brion**: Steal their 8/8, swing, then throw for 8 damage and gain 8 life
- **Adarkar Valkyrie + Brion**: Point Valkyrie at the stolen creature, throw it, it dies and returns permanently under your control
- **Mimic Vat**: When thrown creatures die, imprint them. Pay 3 to make hasty copies to throw every turn
- **Flameshadow Conjuring**: When your creatures ETB, pay R for a hasty copy to throw
- **Feldon of the Third Path**: Make copies of dead creatures from your GY to throw
- **Angrath's Marauders**: Doubles ALL damage from Brion's fling ability
- **Sunhome**: Give Brion double strike — his combat damage has lifelink too
- **Sunforger**: Tutors Fling, Soul's Fire, Chaos Warp, Swords to Plowshares, Boros Charm, Act of Aggression at instant speed
- **Humble Defector**: Draw 2, give to opponent, steal back with a Threaten effect

## Known Issues
- Brion is the primary engine — without him, the deck is a pile of Threaten effects with nothing to do
- Only 2 board wipes — but stealing IS removal in this deck
- Card draw is limited, lifegain payoffs (Well of Lost Dreams) help
- Red-heavy (46 red pips vs 17 white) — mana base reflects this with more Mountains
- Threaten effects are dead cards against creatureless decks or token swarms (small tokens aren't worth throwing)

## Mulligan Strategy

Goal: cast Brion turn 3-4, start stealing and throwing by turn 4-5. Brion costs {2}{R}{W}.

### Auto-keep
- 3+ lands with both R and W + a 2 CMC mana rock — Brion turn 3, threaten-and-throw turn 4.
- 3+ lands + Sol Ring — Brion turn 2, start throwing turn 3.
- 3 lands + ramp + threaten effect — perfect curve into the gameplan.

### Good keep
- 3-4 lands with a sacrifice outlet and steal effects — even if Brion comes later, you have the engine.
- 2 lands + 2 mana rocks — risky but fast if you hit land drop 3.
- 4 lands + Sunforger or Well of Lost Dreams — value engine online when Brion arrives.

### Mulligan
- 1 land even with ramp — Brion needs colored mana.
- No red sources — 46 red pips, can't function without red.
- All steal effects, no ramp or sacrifice outlets — need the infrastructure first.
- All high-CMC cards (5+) with no acceleration — too slow for Bracket 2 games.

### Priority order for opening hand
1. Mountain or RW dual (non-negotiable — red is primary color)
2. Plains or W source (need W for Brion and white spells)
3. 2 CMC mana rock (Sol Ring, Signet, Diamond — accelerates Brion)
4. Threaten effect (have one ready for when Brion lands)
5. Sacrifice outlet (Goblin Bombardment — cheap backup for Brion)
6. Protection (Lightning Greaves — keep Brion alive)

### Dream curves
**Fast start:**
- T1: Mountain, Sol Ring
- T2: Plains, Brion Stoutarm
- T3: Land, Act of Treason on opponent's biggest creature, attack, throw with Brion for massive damage + life

**Normal start:**
- T1: Land, Wayfarer's Bauble
- T2: Land, crack Bauble, Boros Signet
- T3: Land, Brion Stoutarm
- T4: Kari Zev's Expertise (steal + free cast a 2-drop), attack, throw

**Value start:**
- T1: Land
- T2: Land, Lightning Greaves
- T3: Land, Brion, equip Greaves (shroud + haste — protected immediately)
- T4: Steal, attack, throw, repeat

## Game Simulation Findings (2026-03-18)

### Performance: 4 LLM games, 1 win (Round 2 Pod B seed 10132)
- Steal-and-fling is the most interactive mechanic in the portfolio — great table politics
- The Akroan War was the best play across all games (steal Miirym, Chapter II destroyed Brigid's whole board)
- Captivating Crew as repeatable steal for {2}{R} is the deck's best engine piece
- **Card draw is the bottleneck** — runs out of gas after first wave of steal effects

### MVP Cards
- **The Akroan War** — Chapter I stole Yuma/Miirym, Chapter II wiped boards, devastating 3-for-1
- **Captivating Crew** — repeatable steal every turn, backbone of mid-game
- **Brion Stoutarm** — flung stolen Yuma for 6 + gained 6 life, flung Miirym for 6 + 6 life

### Underperformers
- **Thornbite Staff** — never equipped (Brion has shroud from Greaves), 2+4 mana to equip non-Shaman
- **Kazuul's Fury** — redundant fling when Brion is on board, worse than a basic land
- **Wear // Tear** — no good targets in most games

### Improvement Priorities
1. Add more card draw (Tome of Legends, Mask of Memory, Well of Lost Dreams with lifelink)
2. Replace Thornbite Staff with something useful (Sunforger for instant tutoring?)
3. Add 1-2 more 2-CMC mana rocks — 1.6 average mulligans indicates mana issues
4. Consider Soul Warden / Authority of the Consuls for incremental lifegain

### Round 2 Findings (confirmed)
- Brion won by stealing+flinging Mothman (15/15) and Yuma's commander — validates the steal-and-throw gameplan
- Mimic Vat imprinting Mothman gave repeatable hasty flying tokens — great tech
- Akroan War Chapter II destroyed Brigid's board AGAIN (8 creatures → 2)
- Fling spell is redundant when Brion is on board with Greaves — consider cutting

## Origin
Custom build — Boros threaten-and-throw theme
