"""ER-9 squad (shirt) numbers: transform mapping, upsert idempotency, orphans."""
from __future__ import annotations

import db
import integrity
import transform


def _payload():
    return [{"team": {"id": 1, "name": "Alpha"}, "players": [
        {"id": 101, "name": "A. One", "age": 25, "number": 10, "position": "Midfielder", "photo": "x"},
        {"id": 102, "name": "B. Two", "age": 30, "number": None, "position": "Defender", "photo": "y"},
    ]}]


def test_transform_squads_maps_rows_including_null_number():
    players, squad = transform.transform_squads(_payload(), 2026, 1, "T")
    assert {p["player_id"] for p in players} == {101, 102}
    # player rows carry ONLY the squad-endpoint columns, so upserting them can't
    # null richer fields (nationality, firstname, ...) set by /players.
    assert set(players[0]) == {"player_id", "name", "age", "photo"}
    by = {s["player_id"]: s for s in squad}
    assert by[101]["number"] == 10 and by[101]["team_id"] == 1
    assert by[101]["position"] == "Midfielder"
    assert by[102]["number"] is None                       # NULL preserved, never invented
    assert by[101]["season"] == 2026 and by[101]["league_id"] == 1


def test_squad_upsert_idempotent_and_updates_in_place(conn, teams):
    players, squad = transform.transform_squads(_payload(), 2026, 1, "T")
    for _ in range(2):                                      # run twice -> no duplicates
        db.upsert(conn, "player", players, ["player_id"])
        db.upsert(conn, "squad", squad, ["team_id", "player_id", "season", "league_id"])
    assert conn.execute("SELECT COUNT(*) FROM squad").fetchone()[0] == 2
    squad[0]["number"] = 7                                  # a revised number updates in place
    db.upsert(conn, "squad", squad, ["team_id", "player_id", "season", "league_id"])
    assert conn.execute("SELECT number FROM squad WHERE player_id=101").fetchone()[0] == 7
    assert integrity.check_orphans(conn) == []
    assert integrity.check_duplicate_pks(conn) == []


def test_squad_player_upsert_preserves_richer_player_fields(conn, teams):
    # a player already loaded from /players keeps nationality/firstname after a squad upsert
    db.upsert(conn, "player", [{"player_id": 101, "name": "A. One",
                                "nationality": "A", "firstname": "A", "lastname": "One"}],
              ["player_id"])
    players, _ = transform.transform_squads(_payload(), 2026, 1, "T")
    db.upsert(conn, "player", players, ["player_id"])
    row = conn.execute("SELECT nationality, firstname FROM player WHERE player_id=101").fetchone()
    assert row["nationality"] == "A" and row["firstname"] == "A"


def test_squad_orphan_detected(conn, teams):
    conn.execute("PRAGMA foreign_keys = OFF;")              # simulate a load that bypassed FK
    db.upsert(conn, "squad", [{"team_id": 1, "player_id": 999, "number": 9, "position": "F",
                               "season": 2026, "league_id": 1, "captured_at": "T"}],
              ["team_id", "player_id", "season", "league_id"])
    assert any("squad.player_id" in p for p in integrity.check_orphans(conn))
