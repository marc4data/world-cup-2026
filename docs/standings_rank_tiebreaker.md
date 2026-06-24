# Standings `rank` — Data Lineage & Tiebreaker

**Date:** 2026-06-17 · **Scope:** `standing.rank` (table.field) · **Status:** Documented finding

> **TL;DR.** `standing.rank` is passed through from API-Football, not computed by us.
> The API's tiebreaker is **Points → Goal Difference → Goals For**, and it stops there —
> beyond that it does **not** implement the official FIFA check-down (for 2026: head-to-head
> first, then overall GD/GF, then fair play, then FIFA World Ranking), and its deep-tie
> ordering is arbitrary/undocumented. Note the API even applies overall GD/GF *before*
> head-to-head, which is itself wrong for 2026. We compute `standing.rank_fifa` correctly in
> `src/ranking.py`. This is harmless early but matters at the end of the group stage, where
> exact rank decides who advances.

## Field lineage

`standing.rank` comes straight through from API-Football — we do not compute it:

```
/standings  ->  response[0].league.standings[group][team].rank  ->  standing.rank
```

(see `src/transform.py` `transform_standings`). Our API guide documents that `/standings`
*returns* `rank`, `points`, `goalsDiff`, `all{…}`, `form` — but **neither our docs nor
API-Football's docs define the tiebreaker algorithm.** The provider hands us a pre-computed
`rank`.

## What the API actually does (empirically, from live data)

Checking every group with point-ties, the demonstrable check-down is:

**1. Points (desc) → 2. Goal difference (desc) → 3. Goals For (desc)**

Confirmed cleanly in e.g. Group A (MEX +2 over KOR +1) and Group H (GF 1 ranked above GF 0).

**But it stops there — and beyond GF the order is arbitrary.** Several groups had teams level
on all three (they had not met yet, so head-to-head cannot apply at matchday 1):

- **Group G:** NZL ranked **above** IRN (both 1 pt, GD 0, GF 2)
- **Group B:** SUI > CAN > QAT > BIH (all 1 / 0 / 1)

That ordering is **not** alphabetical, **not** FIFA ranking (FIFA rank would put Iran well
above New Zealand — the opposite), and **not** head-to-head. It is an undocumented provider
fallback (likely feed order / internal team id). **API-Football does not implement the full
FIFA tiebreaker.**

## Official FIFA World Cup 2026 tiebreaker (the real rule)

> **2026 changed the order.** For 2018/2022 the World Cup applied overall GD/GF *before*
> head-to-head. **For 2026, FIFA moved head-to-head first** (researched + confirmed against
> FIFA, FOX, ESPN, Wikipedia — see Sources). Our `src/ranking.py` was corrected on
> 2026-06-24 to match.

### A — Ranking teams **within a group**

| # | Criterion | Scope |
|---|---|---|
| 1 | Greatest points | all group matches |
| 2 | Greatest points | **head-to-head**, among the tied teams only |
| 3 | Superior goal difference | head-to-head |
| 4 | Most goals scored | head-to-head |
| — | *if a subset is still level, re-apply 2–4 to just that subset (recompute the mini-table)* | |
| 5 | Superior goal difference | all group matches |
| 6 | Most goals scored | all group matches |
| 7 | Highest team-conduct ("fair play") score | all group matches |
| 8 | FIFA/Coca-Cola Men's World Ranking (most recent) | — |

So the API's `pts → GD → GF` matches FIFA only for **step 1** now; from there FIFA goes to
head-to-head before overall GD/GF. Step 8 is the **FIFA World Ranking**, not the old
"drawing of lots." We don't load FIFA rankings, so `rank_fifa` uses the API rank as a
deterministic stand-in for step 8 (it only triggers when teams are identical through step 7).

**Team-conduct (fair-play) points:** single yellow −1, second yellow (→red) −3, direct red −4,
yellow + later direct red −5. Our `event.detail` only distinguishes Yellow/Red, so
`CARD_POINTS` (Yellow −1, Red −3) is an approximation of this scheme.

### B — Ranking the **third-placed** teams (across groups)

These teams are in different groups and never meet, so there is **no head-to-head**:

| # | Criterion |
|---|---|
| 1 | Points |
| 2 | Goal difference |
| 3 | Goals scored |
| 4 | Team-conduct score |
| 5 | FIFA World Ranking |

The **8 best of the 12** third-placed teams reach the Round of 32.

### C — Round-of-32 assignment

The winners of groups **A, B, D, E, G, I, K, L** are each paired with one of the eight
qualifying third-placed teams (which specific third is set by FIFA's published lookup
table, keyed on *which* groups the eight thirds come from). The other four winners
(C, F, H, J) face runners-up.

> ✅ Verified match-by-match (2026-06-24) against the Wikipedia knockout-stage page and the
> ESPN schedule: our bracket template (`report_html.py` `_R32_LEFT`/`_R32_RIGHT`/`_TREE_*`)
> is correct for all 16 R32 pairings and 8 R16 feeders — including **M85 = Winner B vs a
> third**. (An earlier note here claiming "Winner C" came from an unreliable secondary
> summary and was wrong.) Per-match R32 dates/venues were corrected to the official schedule.
> Caveat: our M-numbers are bracket-positional, not FIFA's chronological match numbers.

### Sources

- [FIFA — groups, qualification & tie-breakers](https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/groups-how-teams-qualify-tie-breakers)
- [FOX Sports — group-stage & third-place tiebreakers](https://www.foxsports.com/stories/soccer/fifa-world-cup-group-stage-third-place-tiebreakers)
- [ESPN — group stage explained](https://www.espn.com/soccer/story/_/id/48703925/world-cup-group-stage-explained-tiebreakers-third-place-teams)
- [Wikipedia — 2026 FIFA World Cup](https://en.wikipedia.org/wiki/2026_FIFA_World_Cup)

## The gap, and recommendation

- Our integrity reconciliation currently verifies **points only** (recomputed 3/1/0), **not the
  rank ordering** — so a wrong deep-tie rank from the API would not be flagged today.
- Early-tournament this rarely matters (deep ties resolve as matches play and GD/GF separate
  teams). It matters at the **end of the group stage**, where exact rank decides advancement.
- For official, defensible ranking we should **compute rank ourselves** from fixtures:
  pts → overall GD → overall GF → head-to-head (pts/GD/GF among tied) → fair-play (we have cards
  in the `event` table) — stored as `rank_fifa` alongside the API `rank`, with an integrity check
  flagging mismatches.
- The API standing row also carries a `description` field (qualification status, e.g.
  "Promotion - …") that we do **not** currently store — easy to add for the bracket/advancement view.
