# Roadmap — Enhancement Requests (ER) backlog

Formal backlog for the data-depth Enhancement Requests from
`DASHBOARD_REQUIREMENTS.md` §14, mapped onto **this** repo's pipeline. This is the
source of truth for ER status; day-to-day uncertainties stay in `OPEN_ITEMS.md`.

## How this repo relates to the dashboard vision

The dashboard doc describes a **web frontend** (GitHub Pages, vanilla JS, `/data/*.json`).
This repo is the **data layer** that frontend needs — API-Football → SQLite with
integrity, idempotent loads, and report/export surfaces. Most ERs are *ingestion*
work and slot straight into our existing pattern (table → transform → integrity →
ingest CLI → tests → report/export). The web app is a **separate downstream track**
(its own repo per dashboard §10-A); when it exists, we add a JSON export step
mirroring `export_excel.py`.

Two relevant decisions from the dashboard doc are **already settled here:** the paid
API-Football plan (we're on Pro) and the repo (this one, `world-cup-2026`).

## ER status

Status: 🟢 proposed · 🟡 in progress · ✅ done. "Fits now?" = implementable in this
pipeline today without the web frontend.

| ID | Enhancement | Maps to (this repo) | Source | Fits now? | Lift | Status |
|----|-------------|---------------------|--------|-----------|------|--------|
| **ER-1** | Match event timeline (goals/assists, cards, subs, VAR) | `event` table + `/fixtures/events` ingest | API-Football (Pro) | ✅ yes | Low–Med | ✅ **done** |
| **ER-2** | Team + player match stats | `fixture_player_stat` (M7) + `fixture_team_stat` ← `/fixtures/statistics` (incl. xG) | API-Football (Pro) | ✅ yes | Med | ✅ **done** |
| **ER-3** | Authoritative venue capacities | `venue.capacity` ← `venues_geo.csv` | FIFA figures + Wikidata | ✅ yes | Low | ✅ **done** |
| **ER-4** | Venue enrichment (image, year, history) | `venue` columns ← `venues_enrich.csv` (fetched by `venue_enrich.py`) | Wikidata QID + Commons + Wikipedia | ✅ yes (static) | Med | ✅ **done** |
| **ER-5** | Team World Cup history (titles, appearances) | `team_history` table ← `team_history.csv` (static) | curated seed; verify vs jfjelstul | ✅ yes | Low–Med | ✅ **done** (curated seed) |
| **ER-6** | Per-match news links | `news` table ← `news_ingest.py` (GNews) | GNews (key stored) | ✅ yes | Low | ✅ **done** |
| **ER-7** | Goal highlight clips (embed) | frontend feature; optional `highlights` table | Scorebat (free) | ❌ frontend-centric | Med–High | 🟢 proposed |
| **ER-8** | ESPN/FIFA match cross-reference (IDs + content deep-links) | `fixture` cols `espn_game_id`/`fifa_id_match`/`fifa_match_num` + `fixture_links` view ← `espn_fifa_xref.csv` (static) | ESPN + FIFA public APIs | ✅ yes (static) | Low–Med | ✅ **done** (group; 72/72) |

> **ER-8 note.** Full handoff in `docs/ESPN_FIFA_Xref_Requirements.md`; the 72-row static
> dataset (`data/espn_fifa_xref.csv`) is produced and verified (72/72 group matches).
> Rights-safe deep links (incl. ESPN highlights URL + FIFA match-centre), so it doubles
> as a link-only precursor to ER-7's embeds and ships without the web frontend.

## Recommended sequencing (data layer first)

1. **ER-3 — venue capacities** (quick win; `venue.capacity` already exists, just NULL).
2. **ER-1 — match events** (high storytelling value; same `/fixtures/...` pattern as M7).
3. **ER-2 completion — team match stats** (`fixture_team_stat`; player half already shipped).
4. **ER-5 — team WC history** (static dataset; no live cadence).
5. **ER-4 — venue enrichment** (Wikidata; static, attribution matters).
6. **ER-6 — news links** (needs a news API key + ToS check).
7. **ER-8 — ESPN/FIFA cross-reference** (static, one-time load like ER-3/4/5; no daily-cron cost; data + spec ready).
8. **ER-7 — highlights** (belongs with the web frontend; embeds-only, rights-safe).

Each is independently shippable as a milestone (table + transform + integrity + ingest
+ tests + a report/export surface), reviewed like M1–M7. Static-load ERs (3/4/5) run
once, not on the daily cron; live ERs (1/2/6) ride the match-day cadence.

## Out of scope here (separate track)

The interactive web dashboard itself (§§4, 8, 9 of the dashboard doc) — frontend,
Pages deploy, JSON contract, win-probability model. Revisit once the data-layer ERs
land; this repo would feed it via a `/data/*.json` export.
