# Commander Land Cycles — Reference & Cost Package

A reference for every major nonbasic fixing-land cycle used in Commander, ordered
by how the wider Commander community values them. The ordering **reconciles six
sources** (see bottom): The Command Zone's mana-base philosophy, MTGGoldfish's
Commander Clash "Dual Land Tier List" podcast, EpicEDH's dual-land tier guide,
Draftsim's "66 Best Lands," EDHREC's best-lands data, MTGRocks' popularity list,
and TheGamer's cycle ranking.

## How to read this

- **Prices are EUR (Scryfall), fetched 2026-07-05**, for the **Sultai / BUG members**
  of each cycle (UB, GU, BG) — that's what is actionable for the decks in this repo.
  The mechanic and tier apply to every color pair; only the specific card names change.
- **Budget** column uses this repo's rule: **no single card over €10**. ✅ = in budget, ⚠️ = over.
- Ordering reflects a **multiplayer, ~40-life, Bracket ≤3 (long-game)** context — the format
  these decks target. In 1v1 / cEDH some rankings shift (bond lands down, fast lands up).

> **Where the sources agree and disagree** (this drove the tiering):
> - **Universal top tier:** original duals, fetches, shocks, bond lands, triomes — every list.
>   Bond lands rate #1–3 in EDH-specific lists (untapped in multiplayer, no life).
> - **Fast lands are the big divergence:** strong in constructed, but EDH lists rank them
>   *low or omit them* (EpicEDH tier C; unranked by MTGRocks/TheGamer/EDHREC/Draftsim-top).
>   In long games their "untapped only turns 1–3" window is mostly wasted → **demoted to B**.
> - **Slow lands** are repeatedly called "underrated for EDH" (TheGamer #6, EpicEDH B) →
>   they beat fast lands here and sit in **A**.
> - **Surveil lands** get "best cycle since shocks" (Draftsim #8) and Flipside top-5, and
>   **Verge lands** rate above check lands (EDHREC) → both in **A**.
> - MTGGoldfish's tier-list article is a **podcast episode (audio only)** — I crawled it with
>   `playwright-cli` to confirm there's no text tier list to quote; its consensus is folded in.

---

## Tier ordering (best → worst)

| Tier | Cycle | Enters untapped? | Fixing quality | Notes |
|------|-------|------------------|----------------|-------|
| **S** | Original dual lands (ABUR) | Always | Perfect (2 basic types) | Zero drawback; price-prohibitive |
| **S** | Fetch lands | n/a (fetches) | Perfect | Thins deck, feeds landfall/graveyard; costs life + €€€ |
| **S** | Shock lands | Yes (2 life) | Excellent (2 basic types) | Most-played EDH dual (EDHREC); the premium workhorse |
| **S** | Bond lands (Battlebond) | Yes if 2+ opponents | Excellent | *Always* untapped in EDH, no life — rated #1–3 in EDH lists |
| **S** | Triomes | Tapped | Excellent (3 colors, 2 types) | Best 3+ color fixing; fetchable + cycling; only knock is ETB tapped |
| **A** | Check lands | Yes if you control the typed land | Excellent | Near-always untapped in 2–3 colors; cheap; weaker at 4–5 colors |
| **A** | Pain lands | Always | Very good (+ colorless) | 1 life for color; life is cheap in EDH |
| **A** | Verge lands | Yes if you control a relevant type | Very good | Newer; "better than check lands in most cases" (EDHREC) |
| **A** | Surveil lands | Tapped | Excellent (2 types + selection) | "Best dual cycle since shocks" (Draftsim); fetchable |
| **A** | Slow lands | Yes once you control 2+ lands (T3+) | Good | **Beats fasts in long games** — untapped on late drops/topdecks |
| **A** | Horizon lands | Always (1 life to tap) | Good | Sac-to-draw flood insurance; EpicEDH A-tier |
| **B** | Fast lands | Yes (first 3 turns only) | Good early | **Tapped from turn 4+**; weak in long EDH games (EpicEDH tier C) |
| **B** | Filter lands (Shadowmoor/Eventide) | Always | Flexible double-output | Need a colored input to make color; conditional |
| **B** | Battle / tango lands | Yes if you control 2+ basics | Good | Slow on a basic-light base |
| **B** | Pathway lands (MDFC) | Always | One color only | Flexible-untapped, but only one color per drop |
| **C** | Scry lands (Temples) | Tapped | Good (scry 1) | ETB tapped is the whole cost |
| **C** | Tri-lands (wedge taplands) | Tapped | Excellent (3 colors) | Cheap 3-color tapland; no types/cycling (unlike Triomes) |
| **C** | Bicycle / cycling duals | Tapped | Good (2 types) | Cycles away in flood |
| **C** | Refuge / gain lands | Tapped | Good (+2 life) | Bottom of the tapped-dual pile |
| **D** | Bounce (Karoo) lands | Tapped | Good (2 mana) | Returns a land; ramps but card-light |
| **D** | Odyssey filter lands | Always | Conditional | No colorless mode; need generic input |
| **D** | Depletion lands | Tapped | Burst / every-other-turn | Combo-only; see bottom section |
| **—** | Channel & creature / man-lands | Varies | Utility, not fixing | Ranked top-5 by some sources *as utility* (Otawara, Creeping Tar Pit) |

---

## Cycle detail (Sultai / BUG members + costs)

### S — Original dual lands (ABUR)
`{T}: Add A or B.` Two basic land types, always untapped, no drawback. The gold standard.
- Underground Sea (UB), Tropical Island (GU), Bayou (BG) — **~€300–700 each ⚠️** (Reserved List; not repo-legal on price)

### S — Fetch lands
`{T}, Pay 1 life, Sacrifice: Search for a land with a basic type.` Best fixing in the game — grab a shock/dual/triome, thin the deck, trigger landfall, fuel graveyard themes.
| Land | Colors (fetches) | EUR | Budget |
|------|------|-----|--------|
| Polluted Delta | Island/Swamp | 18.03 | ⚠️ |
| Misty Rainforest | Forest/Island | 25.32 | ⚠️ |
| Verdant Catacombs | Forest/Swamp | 22.78 | ⚠️ |

Command Zone caveat: only worth it if you actually run fetchable targets; otherwise `Fabled Passage`/`Evolving Wilds` do the job cheaply.

### S — Shock lands
`As it enters, pay 2 life or it's tapped.` Two basic types → fetchable and check-land-enabling. The single most-played dual cycle in EDH per EDHREC.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Watery Grave | UB | 10.16 | ⚠️ (just over) |
| Breeding Pool | GU | 10.23 | ⚠️ (just over) |
| Overgrown Tomb | BG | 8.94 | ✅ |

### S — Bond lands (Battlebond / Commander Legends)
`Enters untapped if you have 2+ opponents.` = always untapped in multiplayer, no life cost. Rated #1–3 for EDH by TheGamer, MTGRocks, EpicEDH.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Morphic Pool | UB | 26.02 | ⚠️ |
| Rejuvenating Springs | GU | 6.98 | ✅ |
| Undergrowth Stadium | BG | 4.88 | ✅ |

### S — Triomes
`Tapped; three colors; two basic land types; cycling {3}.` Premier fixing for 3+ colors — the only tapped cycle sources still rank top-5, thanks to fetchability + flood insurance.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Zagoth Triome | BUG | 18.12 | ⚠️ |

### A — Check lands (M10 / Innistrad)
`Enters tapped unless you control a land of the named basic type(s).` Near-always untapped in 2–3 colors; dirt cheap. Weakens as color count rises (needs the specific basic type in play).
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Drowned Catacomb | UB | 1.24 | ✅ |
| Hinterland Harbor | GU | 0.31 | ✅ |
| Woodland Cemetery | BG | 0.86 | ✅ |

### A — Pain lands
`{T}: Add {C}. {T}: Add A or B, deal 1 damage to you.` Always untapped; colorless mode is a bonus; life is cheap in EDH.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Underground River | UB | 1.96 | ✅ |
| Yavimaya Coast | GU | 0.46 | ✅ |
| Llanowar Wastes | BG | 0.89 | ✅ |

### A — Verge lands (Foundations / Aetherdrift, 2024+)
`{T}: Add A. {T}: Add B — only if you control a land of the right type.` Untapped, unlocks fast on a fixed base; EDHREC rates them above check lands.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Gloomlake Verge | UB | 10.43 | ⚠️ (just over) |
| Willowrush Verge | GU | 6.18 | ✅ |
| *(no BG verge printed in this cycle yet)* | BG | — | — |

### A — Surveil lands (Murders at Karlov Manor)
`Enters tapped; surveil 1.` Two basic types (fetchable) + card selection. Draftsim calls the cycle "the best dual land cycle printed since the shock lands"; the only cost is ETB tapped (fine in long EDH games).
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Undercity Sewers | UB | 20.29 | ⚠️ |
| Hedge Maze | GU | 12.01 | ⚠️ |
| Underground Mortuary | BG | 14.99 | ⚠️ |

### A — Slow lands (Midnight Hunt / Crimson Vow)
`Enters tapped unless you control 2+ other lands.` Tapped only as one of your first two lands; **untapped from turn 3 on, including topdecks**. In long Bracket 1–3 games most land drops happen once you already control 3+ lands, so slows come in untapped *more often* than fast lands (tapped from turn 4+) — hence ranked **above fasts** here. "Underrated in Commander" (TheGamer).
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Shipwreck Marsh | UB | 5.03 | ✅ |
| Dreamroot Cascade | GU | 0.71 | ✅ |
| Deathcap Glade | BG | 1.78 | ✅ |

### A — Horizon lands (Modern Horizons 1–2)
`{T}, Pay 1 life: Add A or B. {1}, {T}, Sacrifice: Draw a card.` Always-untapped fixing plus flood insurance; EpicEDH A-tier.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Waterlogged Grove | GU | 1.59 | ✅ |
| Nurturing Peatland | BG | 5.23 | ✅ |
| *(no UB horizon land)* | UB | — | — |

### B — Fast lands (Scars / Kaladesh / MOM)
`Enters tapped unless you control 2 or fewer other lands.` Untapped turns 1–3, but **tapped on any land drop from turn 4 onward**. EDH-focused lists rank these low (EpicEDH tier C) because long games waste the early window. Only pull ahead in fast/cEDH metas.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Darkslick Shores | UB | 2.56 | ✅ |
| Botanical Sanctum | GU | 1.72 | ✅ |
| Blooming Marsh | BG | 2.67 | ✅ |

### B — Filter lands (Shadowmoor / Eventide)
`{T}: Add {C}. {A/B}, {T}: Add two mana in A/B.` Flexible double-color output, always untapped — but need one colored input to make color (dead as a lone opener). EpicEDH B-tier.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Sunken Ruins | UB | 6.71 | ✅ |
| Flooded Grove | GU | 0.34 | ✅ |
| Twilight Mire | BG | 0.53 | ✅ |

### B — Battle / tango lands (Battle for Zendikar)
`Enters tapped unless you control 2+ basic lands.`
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Sunken Hollow | UB | 0.22 | ✅ |
| *(no GU or BG tango land)* | — | — | — |

### B — Pathway lands (Zendikar Rising / Kaldheim, MDFC)
Modal double-faced: pick one color when you play it; always untapped. TheGamer ranks these highly (#4) for flexibility, but they only make one color per land drop.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Clearwater Pathway | UB | 5.01 | ✅ |
| Barkchannel Pathway | GU | 4.58 | ✅ |
| Darkbore Pathway | BG | 6.12 | ✅ |

### C — Scry lands / Temples (Theros)
`Enters tapped; scry 1.`
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Temple of Deceit | UB | 0.22 | ✅ |
| Temple of Mystery | GU | 0.18 | ✅ |
| Temple of Malady | BG | 0.19 | ✅ |

### C — Tri-lands / wedge taplands (Khans of Tarkir etc.)
`Enters tapped; taps for any of three colors.` No basic types or cycling (that's what separates them from Triomes).
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Opulent Palace | BUG | 0.23 | ✅ |

### C — Bicycle / cycling duals (Amonkhet)
`Enters tapped; two basic types; cycling {2}.`
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Fetid Pools | UB | 0.20 | ✅ |
| *(no GU or BG bicycle land)* | — | — | — |

### C — Refuge / gain lands (Khans "Refuges")
`Enters tapped; gain 1 life.`
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Dismal Backwater | UB | 0.07 | ✅ |
| Thornwood Falls | GU | 0.06 | ✅ |
| Jungle Hollow | BG | 0.06 | ✅ |

### D — Bounce / Karoo lands (Ravnica, e.g. Dimir Aqueduct)
`Enters tapped; return a land you control to hand; taps for 2 mana (A+B).` Ramps, but a card down.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Dimir Aqueduct | UB | 0.21 | ✅ |
| Simic Growth Chamber | GU | 0.21 | ✅ |
| Golgari Rot Farm | BG | 0.19 | ✅ |

### D — Odyssey filter lands
`{1}, {T}: Add A B.` No colorless mode, no self-sufficiency — needs generic mana input.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Darkwater Catacombs | UB | 0.22 | ✅ |
| Overflowing Basin | GU | 0.21 | ✅ |
| Viridescent Bog | BG | 0.30 | ✅ |

### — Channel & creature / man-lands (utility, not core fixing)
Orthogonal to fixing — valued as spells-on-a-land or evasive threats. Several sources rank
these top-5 *as utility* (Channel lands like Otawara; man-lands become creatures).
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| Creeping Tar Pit | UB | 0.42 | ✅ |
| Lumbering Falls | GU | 0.20 | ✅ |
| Hissing Quagmire | BG | 0.52 | ✅ |

---

## Depletion lands — documented, **not recommended** for value decks

Two families, and they interact with a **proliferate** deck in *opposite* ways.

### Burst depletion (Mercadian Masques)
`Enters tapped with 2 depletion counters. {T}, remove a counter: add A A. Sacrifice when empty.`
Burst mana (4 total, then dies). **Proliferate is positive** — adds a counter = an extra use — but they enter tapped, are mono-colored, and sacrifice themselves. Combo/storm only.
| Land | Makes | EUR | Budget |
|------|-------|-----|--------|
| Peat Bog | {B}{B} | 1.85 | ✅ |
| Saprazzan Skerry | {U}{U} | 1.98 | ✅ |
| Hickory Woodlot | {G}{G} | 3.92 | ✅ |

### Ice Age depletion
`{T}: Add A or B, put a depletion counter; doesn't untap while it has one; upkeep removes one.`
Produces mana only **every other turn**, and **proliferate is anti-synergy** (adds counters = stays tapped longer). Avoid in a counters deck.
| Land | Colors | EUR | Budget |
|------|--------|-----|--------|
| River Delta | UB | 0.96 | ✅ |
| *(Timberline Ridge, Lava Tubes, Land Cap, Veldt are off-color)* | — | — | — |

**Why they're skipped here:** they enter tapped (against an untapped-manabase plan), fix poorly
(mono-color or every-other-turn), self-sacrifice (hurts land count / landfall), and — for the burst
family — the proliferate "synergy" competes with proliferate you'd rather point at +1/+1 counters.

---

## Sources
- [MTGGoldfish — Commander Clash Podcast: Dual Land Tier List (ep. 028)](https://www.mtggoldfish.com/articles/commander-clash-podcast-028-dual-land-tier-list) — podcast (audio)
- [MTGGoldfish — Commander Clash Podcast: Dual Land Tier List (ep. 249)](https://www.mtggoldfish.com/articles/commander-clash-podcast-249-dual-land-tier-list) — podcast (audio; crawled via playwright-cli)
- [EpicEDH — Ultimate Dual Land Guide for Commander](https://epicedh.com/dual-lands-edh/) — explicit A/B/C tier list
- [Draftsim — The 66 Best Lands in Commander, Ranked](https://draftsim.com/mtg-commander-lands/)
- [EDHREC — The Best MTG Lands of 2025 for Commander](https://edhrec.com/articles/the-best-mtg-lands-of-2025-for-commander) — play-rate data
- [MTGRocks — Top 5 Most Popular Land Cycles in Commander](https://mtgrocks.com/top-5-best-popular-land-cycles-in-commander/) — EDHREC popularity
- [TheGamer — Best Land Cycles to Use in a Commander Deck](https://www.thegamer.com/magic-gathering-command-deck-best-land-cycles/)
- [Flipside Gaming — The Best Land Cycles for Commander](https://flipsidegaming.com/blogs/magic-blog/the-best-land-cycles-for-commander)

*Prices: Scryfall EUR, 2026-07-05. Cycle mechanics per Scryfall oracle text.*
