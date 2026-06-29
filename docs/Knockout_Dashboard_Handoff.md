# Hand-off — knockout dashboard build script (Cowork → Claude Code)

**Date:** 2026-06-28 · **File:** `scripts/build_knockout_dashboard.py`
**Purpose:** Make Claude Code the single owner of this script and capture the one
uncommitted change made from a Cowork visual-iteration session, so nothing is
lost or clobbered.

---

## 1. Action needed now — commit one working-tree change

`scripts/build_knockout_dashboard.py` is **modified but uncommitted** on top of
commit `29a2bc7` ("ER-10: player jersey numbers — squad table + dashboard #NN").
The local ETL (`scripts/local_etl.sh`) only stages **data artifacts**, never
`scripts/`, so this code edit will sit uncommitted until you commit it.

**The uncommitted change (please review + commit):** fixed-width jersey numbers
so player names left-align in vertical lists. Two parts:

1. New CSS class:
   ```css
   .jn{display:inline-block;width:24px;text-align:right;margin-right:7px;
     color:var(--muted);font-weight:700;font-variant-numeric:tabular-nums}
   ```
2. Rewrote the JS `pn()` helper to use it (replaces your inline-span version):
   ```js
   function pn(p){ const n=(p.number!=null)?('#'+p.number):'';
     return `<span class="jn">${n}</span>${esc(p.name)}`; }
   ```

Why: with the inline span, `#7` and `#10` took different widths, so names didn't
line up down the column. The fixed 24px right-aligned slot makes every name start
at the same x in Who's scoring, Minutes & ratings, and Likely 11. Your Python
`_pn()` (used in the Key man / In form scouting notes) is intentionally left as
the inline `#10 Name` form — those are single inline mentions, no column to align.

Suggested commit: `feat(dashboard): fixed-width jersey numbers so names align`.

After committing, **rebuild** to refresh the published HTML:
`python scripts/build_knockout_dashboard.py` (see §4 re: output path).

## 2. Going forward — ownership & protocol

- **Claude Code is the single writer** of `scripts/build_knockout_dashboard.py`
  (and all of `src/` and the pipeline). It's where commits land and where the
  daily ETL runs.
- **Cowork** is used for fast visual iteration (layout/density/color, rendered
  previews) and will **hand changes to you as diffs/notes** like this one rather
  than committing to the script in parallel.
- Risk this avoids: simultaneous edits to the same file, plus `local_etl.sh`'s
  `git pull --no-rebase -X ours`, which on a conflict keeps the **local** copy and
  can silently drop remote edits to this script.

## 3. What the script does (so edits don't regress intent)

Reads `data/worldcup.db`; emits a self-contained interactive HTML (navy/gold):
clickable knockout bracket → two-team comparison. Key pieces to preserve:

- **Bracket positioning:** `_R32_LEFT` / `_R32_RIGHT` + `bracket_layout()` map each
  R32 fixture to its slot via the W/RU feeders (ported from `src/report_html.py`).
  Renders two columns, 8 left / 8 right, top-quad over bottom-quad. Other rounds
  fall back to a simple grid; R16→Final appear automatically as those fixtures
  enter the `fixture` table.
- **Round tabs (`buildRounds`)** use token matching (`of 16` / `quarter` / `semi`
  / exact `final`) — do **not** revert to an 8-char prefix test (it made R16
  collide with "Round of 32").
- **Comparison top:** `cmp-top` = left (header + model odds, header grows to fill)
  beside right (Tournament profile, country-named navy/gold headers).
- **Scouting read:** `edge_notes()` returns per-team, per-category rows
  (Group form, Goals, Key man, In form, Discipline, Pedigree); empty cells render
  blank by design; rows where both teams are blank are dropped.
- **Layout:** `.layout{align-items:start}` — keeps panes at their own height (no
  stretched white space).
- **Jersey numbers:** data comes from the `squad` join already in `fetch()`;
  display via `pn()` / `.jn` (this hand-off's change) and `_pn()` for notes.

## 4. Output path (relevant to the pending publish work)

The script's default `--out` is the **infographic project's** absolute path
(`…/world_cup_2026_soccer/output/…_knockout_dashboard.html`, timestamped/versioned).
For the daily-build + publish integration (next task), have it also write a
**stable-named** file inside this repo (e.g. `reports/knockout_dashboard.html`)
so there's a fixed URL, and add the build step to `scripts/local_etl.sh` (the real
daily driver) and `daily_ingest.yml` (on-demand). Publishing target (GitHub Pages
vs personal site) is still an open decision — see `DASHBOARD_REQUIREMENTS.md` §10.
