"""ER-4: fetch venue enrichment from Wikidata + Wikipedia (run occasionally).

Writes a static `data/venues_enrich.csv` (committed) that the ingest merges into
the `venue` table. Separate, manual step — venue facts are static, so we don't hit
Wikidata on the daily cron. Re-run only when venues or facts change.

Per venue: search Wikidata for the QID, batch-fetch entities in one call, then pull
the image (P18 -> Commons Special:FilePath), opening year (P1619 official opening,
else P571 inception), and a short history blurb (English Wikipedia summary). All
freely licensed + attributed. A QID_OVERRIDES map can pin any venue search gets wrong.

    python src/venue_enrich.py            # -> data/venues_enrich.csv
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from config import VENUES_ENRICH_CSV, VENUES_GEO_CSV

WD_API = "https://www.wikidata.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
COMMONS_FILE = "https://commons.wikimedia.org/wiki/Special:FilePath/"
HEADERS = {"User-Agent": "WorldCup2026-Pipeline/1.0 (github.com/marc4data/world-cup-2026; data project)"}

# Pin a QID here only if search picks the wrong entity (verified by hand).
QID_OVERRIDES: dict[str, str] = {}


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    retry = Retry(total=5, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",), respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _search_qid(session, name):
    r = session.get(WD_API, params={
        "action": "wbsearchentities", "search": name, "language": "en",
        "format": "json", "limit": 1, "type": "item"}, timeout=30)
    r.raise_for_status()
    hits = r.json().get("search", [])
    return (hits[0]["id"], hits[0].get("label", "")) if hits else (None, "")


def _batch_entities(session, qids):
    out = {}
    for i in range(0, len(qids), 40):  # API allows up to 50 ids/call
        chunk = [q for q in qids[i:i + 40] if q]
        if not chunk:
            continue
        r = session.get(WD_API, params={
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": "claims|sitelinks|labels", "format": "json"}, timeout=30)
        r.raise_for_status()
        out.update(r.json().get("entities", {}))
        time.sleep(0.5)
    return out


def _claim_value(claims, prop):
    try:
        return claims[prop][0]["mainsnak"]["datavalue"]["value"]
    except (KeyError, IndexError, TypeError):
        return None


def _year_from(claims):
    for prop in ("P1619", "P571"):  # official opening, else inception
        v = _claim_value(claims, prop)
        if isinstance(v, dict) and v.get("time"):
            try:
                return int(v["time"][1:5])
            except ValueError:
                pass
    return None


def _image_url(claims):
    fname = _claim_value(claims, "P18")
    return COMMONS_FILE + quote(fname.replace(" ", "_")) if fname else None


def _history(session, entity):
    title = (entity.get("sitelinks", {}).get("enwiki", {}) or {}).get("title")
    if not title:
        return None
    try:
        r = session.get(WIKI_SUMMARY + quote(title.replace(" ", "_")), timeout=30)
        if r.status_code == 200:
            extract = (r.json().get("extract") or "").strip()
            return extract[:400] or None
    except requests.RequestException:
        return None
    return None


def fetch_enrichment(geo_csv=VENUES_GEO_CSV, out_csv=VENUES_ENRICH_CSV) -> list[dict]:
    session = _session()
    with open(geo_csv, newline="") as fh:
        names = [r["name"] for r in csv.DictReader(fh)]

    # 1) resolve QIDs (override or search)
    name_qid, name_label = {}, {}
    for name in names:
        if name in QID_OVERRIDES:
            name_qid[name], name_label[name] = QID_OVERRIDES[name], "(override)"
        else:
            qid, label = _search_qid(session, name)
            name_qid[name], name_label[name] = qid, label
        time.sleep(0.4)

    # 2) one batched entity fetch
    entities = _batch_entities(session, list(name_qid.values()))

    # 3) extract + Wikipedia history
    rows = []
    for name in names:
        qid = name_qid[name]
        ent = entities.get(qid, {}) if qid else {}
        claims = ent.get("claims", {})
        rows.append({
            "name": name, "wikidata_qid": qid or "",
            "image_url": _image_url(claims) or "",
            "opening_year": _year_from(claims) or "",
            "description": (_history(session, ent) or "").replace("\n", " "),
        })
        print(f"  {name:26s} {qid or '??':10s} [{name_label[name][:22]:22s}] "
              f"year={rows[-1]['opening_year'] or '-':>5} img={'Y' if rows[-1]['image_url'] else 'n'} "
              f"hist={len(rows[-1]['description'])}c")
        time.sleep(0.4)

    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["name", "wikidata_qid", "image_url",
                                           "opening_year", "description"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out_csv} ({len(rows)} venues)")
    return rows


if __name__ == "__main__":
    sys.exit(0 if fetch_enrichment() else 1)
