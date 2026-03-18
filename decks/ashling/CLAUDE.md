# Ashling, the Limitless — 5-Color Elementals

## Commander
Ashling, the Limitless

## Bracket
3 (Upgraded, upper range)

## Theme
5-color Elemental tribal with ETB/evoke synergies. Ashling grants all Elementals in hand evoke costs equal to their mana value, letting them be cast cheaply for ETB effects, then recurred via Horde of Notions or graveyard synergies.

## Known Issues
- Unreliable mana base for 5 colors
- Not enough card draw
- Mulligan strategy unclear — need to identify ideal opening hands

## Game Simulation Findings (2026-03-18)

### Performance: 5 LLM games, 0 wins (best: 2nd place T9)
- Fastest commander in the portfolio (T3-4 consistently)
- Highest card throughput thanks to evoke-copy engine (Mulldrifter = draw 4, Shriekmaw = kill 2)
- **Always targeted first** because it's the first visible threat at the table
- Gets overwhelmed in mid-game by combined pressure from 3 opponents

### MVP Cards
- **Fury** — free evoke (exile red card), copy kills 4 creatures in one turn
- **Risen Reef** — triggers on every Elemental ETB, draws or ramps every time
- **Blasphemous Act** — with 16+ creatures on board, costs {R}, resets losing positions

### Underperformers
- **Cavalier of Thorns** — {2}{G}{G}{G} is nearly uncastable in 5 colors
- **Mass of Mysteries** — {W}{U}{B}{R}{G} sat in hand every game
- **Haunting Voyage** — too expensive, always discarded early

### Improvement Priorities
1. Add instant-speed protection (Heroic Intervention, Tyvar's Stand) — deck dies to being focused
2. Replace Cavalier of Thorns (GGG) with a castable Elemental
3. Add more untapped red sources — commander costs {2}{R} but red was missing T1-3 repeatedly
4. More cheap card draw to recover after board wipes

### Round 3 Findings (seed 25180)
- Bane of Progress entered as 14/14 destroying 13 artifacts/enchantments — surprise MVP, crippled all 3 opponents
- Died to Living Death + Syr Konrad chain (13 drain from death triggers) — needs instant-speed graveyard hate or Heroic Intervention
- 13 cards in hand by T7 through Risen Reef + evoke-copy engine. The deck generates absurd resources but can't survive focused attention

## Origin
Modified Ashling precon (Elemental Companions Commander - ECC)
