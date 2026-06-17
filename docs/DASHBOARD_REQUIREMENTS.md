# World Cup 2026 Live Dashboard — Requirements & Architecture

**Status:** Draft v1 for review · **Author input:** Marc Alexander (@Marc4Data) · **Date:** 2026-06-10
**Purpose:** Hand-off spec to guide the build (intended for Claude Code). This document defines *what* to build and *why*; it is deliberately implementation-close so the coding work can proceed with minimal back-and-forth.

> ⚠️ **Timing:** The tournament kicks off **June 11, 2026 — tomorrow.** Live results begin immediately. Phase 1 should prioritize getting a thin end-to-end pipeline live over feature completeness.

> **Note (added to repo 2026-06-17):** This is the original dashboard vision doc. The *data-layer* Enhancement Requests in §14 are tracked and mapped onto this pipeline in [ROADMAP.md](ROADMAP.md). The interactive web frontend (§§4, 8, 9) remains a separate downstream track.

---

## 1. Goal

Evolve the existing static, print-oriented infographic into a **web-first, interactive, daily-updating dashboard** that:

1. Ingests broader live data — results, standings, rosters, injuries, lineups/formations, and model win-probabilities — refreshed **automatically every day** (and around match days, more often).
2. Presents it as a **rich interactive HTML dashboard** (filter, drill-down, hover, navigate), not a fixed print sheet.
3. Is **published** to GitHub Pages at `https://marc4data.github.io/world-cup-2026/` *or* integrated into the existing personal site (decision pending — see §10).

---

## 2. Baseline — what exists today

| Aspect | Current state |
|--------|---------------|
| Output | 3-4 page landscape US-Letter infographic, single self-contained `.html` (~200 KB source; ~8.7 MB published with embedded Plotly + flags + basemap) |
| Build | Deterministic Python build scripts (`_build_vNN.py`), versioned filenames, archived in `/output/archive/` |
| Content | Qualified nations + win-prob bars, world map, host-venue map (Plotly geo), group-stage schedule, knockout bracket |
| Data | **Hardcoded** at build time — Opta (win/advance probabilities), FIFA/Sky (draw + fixtures), worldcuppass (venues/capacity/TV) |
| Orientation | **Print-first, static.** No live data, no interactivity beyond Plotly map hover |
| Spec | `LAYOUT_SPEC.md` (locked layout), self-verify + per-element feedback working agreement |

**What carries forward:** the visual identity (navy/gold branding, original trophy/ball motifs, no FIFA trademarks), the venue map recipe, the data-source relationships, and the deterministic-build discipline.

**What changes:** print-sheet → responsive web app; hardcoded → live data layer; one-shot render → scheduled rebuild pipeline. The existing infographic becomes a **"print / overview" view** within the larger dashboard rather than the whole product.

---

## 3. Scope

### In scope
- Live **results & standings** (group tables, knockout bracket auto-advancing as results land).
- **Fixtures** with status (scheduled / live / FT), kickoff in user-local + Pacific, venue, TV.
- **Rosters / squads** per nation; **injuries & suspensions**; **lineups & formations** when published.
- **Model win/advance probabilities**, recomputed as results come in (see §5.3).
- **Tactics / storylines** layer — short curated editorial notes per team/match (manual-assisted).
- Interactive **venue map**, **world map**, **group explorer**, **bracket**, **team pages**.
- Automated **daily** (and match-day) data refresh + redeploy.
- Retained **print/export** view (the current infographic, regenerated from live data).

### Out of scope (for now)
- User accounts, comments, or any backend database/server (static hosting only).
- Live betting odds / monetization.
- Real-time (sub-minute) websockets — daily + periodic polling is sufficient; live-match minute-by-minute is a stretch goal.
- Native mobile apps (responsive web only).
- Redistribution of any paid provider's bulk data (licensing — see §12).

---

## 4. Recommended architecture

**Static-site + prebuilt-data, refreshed by a scheduled job. No server to run, no database, $0 hosting.**

```
   SCHEDULED JOB (GitHub Actions cron)
   runs daily 06:00 PT + every 30 min on match days
        | 1. pull
        v
   openfootball (free JSON)  +  API-Football (paid)  +  Curated/editorial (markdown)
        | 2. normalize + compute model
        v
   build/ (Python): canonical JSON in /data/*.json, win-prob model, regenerated print infographic
        | 3. commit + push
        v
   GitHub repo -> GitHub Pages (CDN): static HTML/JS/CSS + /data/*.json
        | 4. client fetches /data/*.json
        v
   Browser: interactive dashboard (vanilla JS or lightweight framework)
```

**Why this shape:**
- **GitHub Pages is static-only** — it cannot run server code or call APIs on request. Pre-fetching data into committed JSON at build time is the standard, robust pattern.
- **Secrets stay server-side.** Paid API keys live in GitHub Actions Secrets, never shipped to the browser. The client only ever reads pre-baked JSON.
- **Resilience & history.** Every refresh is a git commit — free audit trail, easy rollback, last-good JSON stays committed.
- **Cost: $0 hosting + one optional ~$19/mo data plan.**

**Alternative considered:** a tiny serverless function (Cloudflare Workers / Vercel) to proxy live data on demand. Rejected for v1 — adds a moving part for marginal benefit, since daily + match-day cron covers the freshness requirement.

---

## 5. Data sources & model

### 5.1 Recommended source stack

| Layer | Source | Cost | Covers | Notes |
|-------|--------|------|--------|-------|
| **Baseline (free)** | openfootball/worldcup.json | Free, no key | Fixtures, results, groups, teams | Zero-risk fallback; start here |
| **Live + rich (paid)** | API-Football | ~$19/mo | Live scores, lineups/formations, injuries, squads, player & match stats, events | Best value for injuries/rosters/lineups |
| **Premium (optional)** | SportMonks | €34+/mo (xG €78+) | Above + xG, expected lineups, suspensions | Upgrade only if xG / expected-lineups become must-haves |
| **Budget alt** | football-data.org | from €12/mo | Fixtures/results/standings | Cheaper but thinner |
| **Model probabilities** | Self-computed (§5.3), anchored to published Opta supercomputer figures | Free | Win/advance % | Opta has no clean free API |
| **Tactics / storylines** | Curated markdown | Free | Short per-team / per-match narrative | Not an API product |
| **Venues / TV** | Existing worldcuppass data (static) | Free | Capacity, allocation, US networks | Already in the build |

**Recommendation:** **openfootball (free baseline) + API-Football ($19/mo)**. Start Phase 1 on openfootball alone, add the API-Football key in Phase 2.

### 5.2 Refresh cadence
- **Daily** full refresh at 06:00 PT (standings, squads, injuries, model recompute).
- **Match-day:** every ~30 min during the live window (results, lineups, statuses). Bracket auto-advances.
- Mind provider rate limits; batch and cache.

### 5.3 Win-probability model
Opta's figures are **published, not served via API**. Two options:

- **A. Manual anchor (Phase 1):** store the published Opta pre-tournament percentages as a static seed; display with clear attribution. Simple, accurate at kickoff, goes stale as matches happen.
- **B. Self-computed model (Phase 2+, recommended):** lightweight **Elo or Poisson/Monte-Carlo** model that starts from the Opta anchor and **updates after every result**, re-simulating the remaining bracket N times to produce live advance/win %.

Label all model output clearly as estimates, not predictions. Keep the model in `build/model/` with documented assumptions.

---

## 6. Canonical data model

The build normalizes every source into versioned JSON files the client consumes. Proposed `/data/`:

```
/data/
  meta.json          # last_updated, data sources, build SHA, tournament phase
  teams.json         # 48 nations: code, name, confederation, FIFA rank, group, colors, flag ref
  venues.json        # 16 venues: id, city, country, capacity, lat/lon, match counts by stage
  fixtures.json      # 104 matches: id, datetime(UTC), stage, group, home, away, venue, status, score, tv
  standings.json     # group tables A-L: P W D L GF GA GD Pts, live rank
  bracket.json       # knockout tree: slots, feeders, resolved teams, results
  squads.json        # per team: players (name, pos, club, number, age, caps)
  injuries.json      # per team: player, status, reason, source date
  lineups.json       # per match when published: formation, XI, bench
  probabilities.json # per team: win%, reach_final%, reach_sf%, ... + model version + as_of
  storylines.json    # curated notes: scope (team|match|day), title, body(md), date
```

**Principles:** stable IDs across files; every file carries `as_of` / `source`; small enough to fetch a few on page load; never embed secrets.

---

## 7. Update pipeline

1. **GitHub Actions workflow** (`.github/workflows/refresh.yml`) on `schedule:` cron(s).
2. Steps: checkout → set up Python → run `build/refresh.py` (pull sources using `${{ secrets.API_FOOTBALL_KEY }}`) → normalize to `/data/*.json` → run model → regenerate print infographic → commit & push (skip if no diff).
3. Push to `main` triggers the **Pages deploy**.
4. **Manual trigger** (`workflow_dispatch`) for on-demand refresh.
5. **Failure handling:** if a source errors, keep last-good JSON, log a warning into `meta.json` (`stale: true`), still deploy.

---

## 8. Dashboard information architecture & features

Single-page app with section nav; each section is a "view" over the JSON.

1. **Overview / Home** — tournament status, today's matches, "last updated" badge, biggest model movers, headline storyline. Current infographic lives here as a printable overview.
2. **Groups** — interactive A-L tables, live standings, sortable; click a group → its matches + mini bracket implications.
3. **Schedule / Fixtures** — filter by day / group / team / venue / TV; local + Pacific time; live status; click a match → detail.
4. **Bracket** — interactive R32-Final, auto-advancing; hover a slot for model odds.
5. **Teams** — one page per nation: squad, injuries/suspensions, fixtures, form, model odds, storyline notes.
6. **Venues** — the Plotly venue map + capacity/allocation table; click a venue → its matches.
7. **Predictions / Model** — win & advance probabilities, movement over time (sparklines), methodology + disclaimer.
8. **Map** — world map of 48 nations by confederation, linked to team pages.

**Cross-cutting UX:** responsive; deep links; visible freshness indicator; print stylesheet preserved; accessibility; fast first paint.

---

## 9. Tech stack

| Concern | Recommendation | Why |
|---------|---------------|-----|
| **Site type** | Static site on GitHub Pages | Free, fits prebuilt-data model |
| **Frontend** | Vanilla JS + small modules; light framework only if warranted | Avoids over-engineering v1 |
| **Charts** | Keep Plotly for geo maps; lighter libs for sparklines | Reuse venue-map recipe |
| **Bracket** | Inline SVG, data-driven | Reuse existing bracket |
| **Build/ingest** | Python | Matches existing build scripts |
| **Styling** | CSS (navy/gold) + print stylesheet | Preserve brand identity |
| **CI/CD** | GitHub Actions (cron + deploy) | Native to Pages |

**Open question:** single-file vs multi-file static site. For an interactive app, **multi-file is recommended**; the infographic export can still be self-contained.

---

## 10. Publishing & hosting — decision needed

- **A. Dedicated repo `world-cup-2026`** → `https://marc4data.github.io/world-cup-2026/`. Cleanest separation, simplest Actions. **Recommended.**
- **B. Section of the existing personal site.** Better for one canonical presence; needs the personal-site repo to assess.

**Recommendation:** ship v1 in a dedicated repo, optionally embed/link from the personal site later.

---

## 11. Phased delivery plan

- **Phase 0 — Repo & pipeline skeleton (½ day).** Repo, Pages, Actions cron stub, `/data/` schema with seeded JSON, "hello dashboard" shell. *Exit: live URL renders from JSON.*
- **Phase 1 — Live results MVP (1-2 days).** openfootball → fixtures/results/standings/bracket → Overview + Schedule + Groups + Bracket. *Exit: standings & bracket auto-update.*
- **Phase 2 — Rich data (2-3 days).** API-Football → squads, injuries, lineups → Team pages + match detail. *Exit: rosters/injuries live.*
- **Phase 3 — Model & predictions (2-3 days).** Elo/Poisson + Monte-Carlo, seeded from Opta anchor. *Exit: live, reproducible win/advance %.*
- **Phase 4 — Storylines, polish, parity (ongoing).**

---

## 12. Risks & open questions

- **Data licensing.** Paid APIs permit use but restrict bulk redistribution. Display derived/normalized data, not raw dumps. **Review ToS before Phase 2 ships publicly.**
- **Rate limits.** The prebuilt-JSON pattern keeps us under them.
- **Model credibility.** Label clearly as estimates; show methodology.
- **Timing pressure.** Phase 1 on free openfootball is the fastest path to live.
- **IP/branding.** No FIFA trademarks; original motifs.
- **Open: hosting** (§10) — your decision.
- **Open: paid data budget** — approve ~$19/mo API-Football, or stay free-only?

---

## 13. Hand-off notes

- Reuse: `LAYOUT_SPEC.md`, the venue-map recipe, navy/gold brand system, deterministic build discipline, the SVG bracket.
- Keep the versioned-filename + archive convention for the print export.
- First build action: scaffold repo + `/data/` schema + a green Actions run (Phase 0).

---

## 14. Data-depth enhancement requests (Viz storytelling)

**Added 2026-06-16.** Goal: give the dashboard more to drill into — match-level event detail, authoritative venue data, venue and team history, and contextual media — so each view tells a richer story. These extend §5 and §6. ER-6 (news) precedes ER-7 (highlights) because news links are a far lighter lift than rights-managed video embeds.

### 14.1 Summary

| ID | Enhancement | Source | Cost | Lift | New/changed data file |
|----|-------------|--------|------|------|------------------------|
| **ER-1** | Match event timeline (goals + assists, cards, subs, VAR) | API-Football `/fixtures/events` | included in $19/mo | Low-Med | `events.json` (new) |
| **ER-2** | Team + player match stats (shots, possession, fouls, ratings) | API-Football `/fixtures/statistics`, `/fixtures/players` | included | Med | `matchstats.json` (new) |
| **ER-3** | Authoritative venue capacities | FIFA confirmed-capacities; cross-check Wikidata | Free | Low | `venues.json` (extend) |
| **ER-4** | Venue enrichment — image, opening year, location, short history | Wikidata (QID) + Wikimedia Commons | Free | Med | `venues.json` (extend) |
| **ER-5** | Team World Cup history — titles, appearances, best finishes | jfjelstul/worldcup or Kaggle WC 1930-2026 (static) | Free | Low-Med | `team_history.json` (new) |
| **ER-6** | Per-match news links (1-3 articles per fixture) | Sportmonks News, or GNews / NewsAPI | Free → paid | Low | `news.json` (new) |
| **ER-7** | Goal highlight clips (embed, not host) | Scorebat Video API (free) or Highlightly | Free → paid | Med-High | `highlights.json` (new) |

### 14.2 Detail & acceptance notes

**ER-1 — Match event timeline.** Ingest `/fixtures/events` per fixture; store minute, team, player, type (Goal/Card/Subst/VAR), `detail`, and `assist` for goals. *Acceptance: every completed fixture has an ordered event list; goals show scorer + assist.*

**ER-2 — Team & player match stats.** Ingest `/fixtures/statistics` (team totals) and `/fixtures/players` (per-player minutes, rating, passes, duels). *Acceptance: match-detail view renders both teams' stat lines + top-rated players.*

**ER-3 — Authoritative venue capacities.** Use FIFA's June 2026 confirmed figures (e.g. Mexico City 80,824; NY/NJ 80,663; Dallas 70,649; LA 70,492; KC 69,045; Houston 68,777; Atlanta 68,239; Miami 64,478; Boston 64,146; Monterrey 51,243; Guadalajara 45,664; Toronto 43,036; Vancouver 52,497; + Philadelphia, SF Bay, Seattle). Cross-check Wikidata. *Acceptance: all 16 venues carry a sourced capacity with `as_of`/`source`.*

**ER-4 — Venue enrichment.** From each venue's Wikidata QID pull image (Wikimedia Commons), opening year, coordinates, and a short history blurb. *Acceptance: each venue has an attributed image + ≥1 history fact.*

**ER-5 — Team World Cup history.** Load a static historical dataset (jfjelstul/worldcup or Kaggle WC 1930-2026): titles, appearances, best finish, last appearance. *Acceptance: each qualified nation's page shows WC pedigree + this cycle's form.*

**ER-6 — Per-match news links.** Attach 1-3 article links per fixture keyed on team names + date (GNews/NewsAPI free tier or Sportmonks News). *Acceptance: each fixture shows ≥1 relevant, dated article link; no dead links.*

**ER-7 — Goal highlight clips.** Attach an embeddable clip per goal via Scorebat's free JSON feed (or Highlightly). **Embed the provider's player — do not download or self-host.** Degrade gracefully when no clip exists. *Acceptance: where a clip is available it embeds; missing clips hide silently.* **Open: confirm embeds-only and which provider.**

### 14.3 Open decisions for these ERs
1. **Paid news/clip tiers** — free tiers cover most at $0; Sportmonks News and Highlightly are paid. Approve any paid tier, or stay free-only?
2. **Clips = embeds only?** Recommended yes (rights). Confirm.
3. **Static vs. live refresh** — venue enrichment (ER-3/4) and team history (ER-5) are static (load once). News (ER-6) and events/stats (ER-1/2) refresh on the match-day cadence. Confirm this split.

### 14.4 Suggested sequencing against §11 phases
- **Phase 2 (rich data):** ER-1, ER-2, ER-3 (quick win).
- **Phase 2.5 / 4 (enrichment & polish):** ER-4, ER-5, ER-6.
- **Phase 4+ (stretch):** ER-7.

---

### Two decisions needed (§10, §12)
1. **Hosting:** dedicated `world-cup-2026` repo (recommended), or integrate into the existing personal site?
2. **Data budget:** approve ~$19/mo for API-Football, or stay free-only?
