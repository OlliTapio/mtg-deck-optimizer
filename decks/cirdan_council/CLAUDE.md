# Círdan the Shipwright — Group-Hug Voting Politics

**Commander:** Círdan the Shipwright (Simic, GU)
**Bracket:** 3 (Upgraded), but tuned toward the casual/fun end — not oppressive.
**Budget:** ~€46 total (hard cap €50). Every card ≤ €4.
**Theme:** Voting / group-hug politics for a 4-player pod. The table draws cards and
ramps together; we're built to profit from the shared card flow more than anyone else.

## Design intent (why this build looks the way it does)
Three constraints shaped it, in order:
1. **Synergy over goodstuff** — every card must advance Círdan's plan (vote, draw-payoff,
   cheat-in permanent, blink, or ramp), not just be individually strong. Generic staples
   were deliberately cut: no Cyclonic Rift, Rhystic Study, Counterspell/Swan Song pile,
   Heroic Intervention, Seedborn Muse, Sol Ring-tier value that doesn't touch the theme.
2. **€50 budget** — this is why the expensive blink engines (Displacer Kitten, Thassa
   Deep-Dwelling) and dual-land base are gone. The voting theme is almost entirely cheap,
   so it survived intact.
3. **Fun, not oppressive** — cut the feel-bad pieces: Propaganda (attack tax),
   Stormtide Leviathan (board lock), Woodfall Primus (repeatable land/permanent
   destruction). Mass Disruption is intentionally low (2) — we don't want to wipe the pod;
   River's Rebuke and Bane of Progress are the only board-affecting resets.

## Game plan
Círdan's *secret council* fires on ETB **and** every attack (vigilance): each player votes,
draws per vote received, and anyone with **zero** votes puts a permanent from hand onto the
battlefield free. We bend this our way with **Illusion of Choice** (assign every vote —
flood ourselves with draws, or deny ourselves votes to cheat a fatty in). **Blink**
(Ghostly Flicker, Essence Flux, Blur, Displace, Teferi's Time Twist, Conjurer's Closet)
re-triggers the council and our ETB creatures.

## Benefit from draw — don't stack it (the core principle)
Círdan IS the draw engine (votes = cards every ETB and every attack). So the deck
deliberately does NOT pile on redundant card-draw — especially not symmetric "each player
draws" pieces that just refill opponents. Earlier drafts ran Rites of Flourishing, Dictate
of Kruphix, Folio of Fancies, Otherworld Atlas and big draw-spells (Rishkar's Expertise,
Soul's Majesty, Return of the Wildspeaker); all were cut as redundant draw-stacking.

Instead the deck **converts Círdan's card flow into a board**, two ways:
1. **Payoffs that scale as you draw:** Nadir Kraken and Chasm Skulker grow (and make tokens)
   every draw; Ominous Seas makes 8/8 Krakens; Fathom Mage draws off counters; Managorger
   Hydra grows on spells; Garruk's Uprising / Colossal Majesty are creature-tied, not raw
   engines. Edric (whole table draws on combat damage) is kept as a *political* tool — it
   points opponents at each other — not as selfish draw.
2. **Ways to actually use a full hand:** a fistful of cards is dead without mana, but we
   ramp only to the template count and stay on-curve — see Ramp philosophy below.
   **Michelangelo, Improviser** (cheats a creature/land from hand on combat damage) and
   **Radagast of Rhosgobel** (first creature each turn gets flash + {2} off — deploy at
   instant speed, ambush, dodge sorcery-speed wraths) get permanents down; **Selvala's
   Stampede**, **Court of Bounty**, and Círdan's own no-votes clause drop them for free.
   (Kodama of the East Tree filled this role earlier — cut for budget when Radagast came in.)

## Ramp philosophy
Dedicated mana-ramp is held to the **template (10 pieces), all 2–3 CMC** — we ramp toward a
5-mana commander, so 1-CMC dorks (Llanowar) and 1-CMC rocks (Sol Ring) were cut as too small
and 5-CMC "ramp" (Peregrine Drake) as too slow. The package: Arcane Signet, Talisman of
Curiosity, Fellwar Stone (2-drop rocks); Farseek, Rampant Growth, Sakura-Tribe Elder, Coiling
Oracle (2-drop land/dork); Cultivate, Kodama's Reach, Farhaven Elf (3-drop land-fetch).
NOTE: deck_analyzer's otag "Ramp" count reads ~20 because it also tags **tempting offer**
(Tempt with Discovery — count it separately), monarch-deploy (Court of Bounty, Regal
Behemoth), initiative-ramp (Explore the Underdark), and cheat effects (Selvala's Stampede) as
"ramp." Those are theme cards, not the mana base. No join-forces cards (removed by request).

## Court / Monarch / Initiative package
Courts extend the voting/politics identity: they use *will of the council* templating in
spirit, make you the monarch (passive card flow won through **combat**, not durdle draw —
so it fits "benefit from draw, don't stack it"), and reward Círdan attacking every turn to
defend the crown / the initiative.
- **Court of Bounty** — monarch; each upkeep deploy a creature/land from hand (uses the full
  hand Círdan draws you).
- **Regal Behemoth** — monarch + doubles land mana → cast the fistful of cards.
- **Initiative:** **Explore the Underdark** (take the initiative) and **Tomb of Horrors
  Adventurer** (initiative + copies your second spell each turn), supported by cheap
  venturers **Yuan-Ti Malison** (unblockable, ventures on damage) and **Dungeon Map**. The
  Undercity dungeon is card/board advantage, and both the crown and the initiative change
  hands on combat damage — exactly what a vigilance commander that attacks every turn wants.
- **Skipped:** Court of Cunning (pure mill, off-theme). Court of Vantress was cut for budget
  when the Komas came in — re-add it if the pod wants a third court.

## Make Círdan connect (evasion + protection)
Círdan's attack council, the monarch/initiative (change hands on combat damage), Michelangelo,
Edric, and Yuan-Ti all reward Círdan actually dealing damage — so we protect and unblock him:
- **Canopy Cover** (owned-adjacent buy) — unblockable except by flying/reach, AND can't be
  targeted by opponents' spells/abilities (dodges removal).
- **Bear Umbra** (OWNED) — +2/+2, untap ALL lands whenever he attacks (mana to cast the hand
  Círdan draws / hold up votes), plus Umbra armor (survives destruction/wraths).
- **Akroma's Memorial** (OWNED) — team gets flying (evasion → more triggers), haste (cheated-in
  Komas/fatties swing immediately), + protection from black/red (dodges removal).

## Owned cards (do NOT count against the €50 buy budget)
- Bear Umbra (~€6), Akroma's Memorial (~€19). Out-of-pocket for the rest is ~€49.6.
- **Considered and skipped: Ugin, Eye of the Storms (owned).** Its repeatable removal is a
  *cast trigger* ("whenever you cast a colorless spell, exile a colored permanent") — this GU
  deck casts few colorless spells and *cheats* creatures in rather than casting them, so the
  engine sits dead. It's only generic value here; left out to keep the deck on-identity. Add
  it as pure owned value if desired.

## Top end (cheat targets + hard-cast finishers)
- **Koma, Cosmos Serpent** and **Koma, World-Eater** ({3}{G}{G}{U}{U}) — uncounterable serpent
  top-end. Cheatable via Selvala's Stampede / Court of Bounty / Michelangelo / the no-votes
  clause, or hard-cast off the 10-piece ramp base.
- **Michelangelo, Improviser** ({3}{G}) — 4-mana engine that cheats a creature/land from hand
  each time it connects; also has Sneak to swing in for free.

## Finishers (a couple, non-oppressive)
- **End-Raze Forerunners** — one-shot team overrun.
- **Hydra Broodmaster** — monstrosity floods the board with an army of Hydras.
- **Simic Ascendancy** — quirky alternate win (grow to 20 growth counters); slow, telegraphed, fun.

## Cheat-in targets (for the no-votes clause + Selvala's Stampede)
Terastodon, Rampaging Baloths, Pelakka Wurm, Verdant Sun's Avatar, Hydra Broodmaster,
End-Raze Forerunners, Nessian Wilds Ravager, Polukranos, Krosan Tusker, Colossal Whale.
All chosen cheap; all do something fun on arrival rather than locking the game.

## Bracket 3 compliance
- **Game Changers: 0.** Bracket 3 allows up to 3; we run none (budget + fun tuning).
- No mass land denial, no infinite combos. Genuinely a low-3 / high-2 power level.

## Color identity
All 99 verified within Simic (GU). Watch for near-misses when swapping: Selvala Explorer
Returned (GW), Kwain (WU), and Where Ancients Tread (R) were all rejected during the build
for being off-color — always run the identity check after edits.

## Template deviations (defended)
- **Card Advantage 21/12** — the otag count catches the draw-*payoffs* (Nadir Kraken, Chasm
  Skulker, etc.) plus monarch/vote card flow, not raw draw engines; see "Benefit from draw"
  above.
- **Ramp reads ~20/10 in the otag check but the real mana-ramp package is exactly 10** — see
  Ramp philosophy. The overage is theme cards (tempting offer, monarch, initiative, cheat)
  mis-tagged as ramp.
- **Mass Disruption 2/6** — deliberate, see Design intent #3. A group-hug deck that wipes the
  table isn't fun; our "resets" are River's Rebuke (one-sided) and Bane of Progress.

## Maybeboard / watch list (not in the 100)
Candidates from The Hobbit (hob), Marvel's Spider-Man (spm), and other sets. Ranked:
- **Worlds Within Worlds** {5}{G}{U} (spm) — exile all creatures, everyone redeploys from
  hand, exiled cards go to hand. We have the fullest hand (Círdan) → we redeploy most and
  re-trigger our ETBs while opponents' boards bounce. **Top pick — political reset we abuse.**
- **Wizard's Staff** {1}{U} (hob) — equip Círdan → his secret council triggers TWICE per
  attack (double votes/draws/free drops). Strong; concentrates value on one creature.
- **Elrond, Moon-Reader** {2}{U} (hob) — repeatable instant-speed blink (2 permanents) that
  re-triggers Círdan's council + our ETBs; refills the repeatable-blink slot.
- **Clinquant Skymage** {3}{U} — Bird, flying, permanent +1/+1 counter on every draw; a
  draw-payoff with evasion (joins Nadir Kraken / Chasm Skulker). "The bird that grows on draw."
- **Part in Friendship** {4}{G} (hob) — dead creature → free-cheat a creature from library.
- **Confusticate and Bebother** {2}{U} (hob) — flexible soft-counter or draw-2 (cheap interaction).
- **Riddles in the Dark** {2}{U} (hob) — political draw (opponent chooses the pile); on-flavor but
  it's *more draw* (against the don't-stack-draw rule).
- **Beorn the Fierce** {3}{G}{G} (hob) — 6/6 trample Bears-tribal (anthem + draw-at-3-Bears).
  Only a beater here without a Bear board; belongs to a Bears variant. (Beorn, Reluctant Host
  was considered and dropped — vanilla body, no synergy.)

## Not owned
Brand-new build — every card is currently a buy. See buy_list.txt.
