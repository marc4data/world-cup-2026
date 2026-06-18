# Standings `rank` — Data Lineage & Tiebreaker

**Date:** 2026-06-17 · **Scope:** `standing.rank` (table.field) · **Status:** Documented finding

> **TL;DR.** `standing.rank` is passed through from API-Football, not computed by us.
> The API's tiebreaker is **Points → Goal Difference → Goals For**, and it stops there —
> beyond that it does **not** implement the official FIFA check-down (head-to-head, fair
> play, drawing of lots), and its deep-tie ordering is arbitrary/undocumented. This is
> harmless early in the tournament but matters at the end of the group stage, where exact
> rank decides who advances.

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

| # | Criterion |
|---|---|
| 1 | Points in all group matches |
| 2 | **Overall** goal difference |
| 3 | **Overall** goals scored |
| — | *if still level, apply to matches among only the tied teams:* |
| 4 | Head-to-head points |
| 5 | Head-to-head goal difference |
| 6 | Head-to-head goals scored |
| 7 | (re-apply 4–6 if a subset is still tied) |
| 8 | Fair-play points (fewest cards) |
| 9 | Drawing of lots (FIFA) |

The World Cup uses **overall GD/GF first** (steps 2–3), *then* head-to-head — unlike the Euros,
which do head-to-head first. So the API's `pts → GD → GF` matches FIFA for the first three
steps; it just does not carry the chain further.

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
