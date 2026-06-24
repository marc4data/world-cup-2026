"""FIFA-correct rank_fifa: head-to-head, fair-play, and API-rank fallback."""
from __future__ import annotations

import db
import integrity
import ranking


def _team(conn, tid):
    db.upsert(conn, "team", [{"team_id": tid, "name": f"T{tid}", "code": f"T{tid}",
              "country": "X", "is_national": 1, "logo": None}], ["team_id"])


def _standing(conn, group, tid, rank, pts, gd, gf):
    db.upsert(conn, "standing", [{
        "season": 2026, "league_id": 1, "group_label": group, "team_id": tid,
        "rank": rank, "played": 1, "win": 0, "draw": 0, "lose": 0,
        "goals_for": gf, "goals_against": gf - gd, "goals_diff": gd, "points": pts,
        "form": None, "description": None}],
        ["season", "league_id", "group_label", "team_id"])


def _fixture(conn, fid, home, away, hg, ag, group="Group A"):
    db.upsert(conn, "fixture", [{
        "fixture_id": fid, "season": 2026, "league_id": 1, "round": "Group Stage - 1",
        "group_label": group, "kickoff_utc": "2026-06-11T19:00:00+00:00",
        "status_short": "FT", "is_finished": 1, "venue_id": None,
        "home_team_id": home, "away_team_id": away, "home_goals": hg, "away_goals": ag,
        "score_ht": None, "score_ft": None}], ["fixture_id"])


def _card(conn, fid, seq, team_id, detail):
    db.upsert(conn, "event", [{
        "fixture_id": fid, "seq": seq, "minute": 50, "extra": None, "team_id": team_id,
        "player_id": None, "player_name": "X", "assist_id": None, "assist_name": None,
        "type": "Card", "detail": detail, "captured_at": "T"}], ["fixture_id", "seq"])


def _ranks(conn):
    return {r["team_id"]: r["rank_fifa"]
            for r in conn.execute("SELECT team_id, rank_fifa FROM standing")}


def test_overall_pts_gd_gf(conn):
    for t, (rk, pts, gd, gf) in {1: (1, 3, 2, 4), 2: (2, 3, 2, 2), 3: (3, 0, -4, 0)}.items():
        _team(conn, t); _standing(conn, "Group A", t, rk, pts, gd, gf)
    ranking.update_rank_fifa(conn, 2026, 1)
    assert _ranks(conn) == {1: 1, 2: 2, 3: 3}   # GF breaks the 3-pt/+2 tie


def test_h2h_breaks_overall_tie(conn):
    for t in (1, 2):
        _team(conn, t)
    _standing(conn, "Group A", 1, 2, 4, 2, 3)   # API ranks team1 second
    _standing(conn, "Group A", 2, 1, 4, 2, 3)   # tied overall (4/+2/3)
    _fixture(conn, 20, 1, 2, 2, 0)              # team1 beat team2 head-to-head
    ranking.update_rank_fifa(conn, 2026, 1)
    assert _ranks(conn) == {1: 1, 2: 2}         # H2H winner first, overriding API rank
    assert integrity.reconcile_rank(conn)       # and the disagreement is flagged


def test_h2h_applied_before_overall_gd_2026(conn):
    """2026 rule: head-to-head is applied BEFORE overall GD/GF. The team with the
    worse overall goal difference still ranks first if it won the head-to-head."""
    for t in (1, 2):
        _team(conn, t)
    _standing(conn, "Group A", 1, 2, 3, 1, 3)   # team1: 3 pts, overall GD +1, GF 3
    _standing(conn, "Group A", 2, 1, 3, 3, 5)   # team2: 3 pts, better overall GD +3, GF 5
    _fixture(conn, 30, 1, 2, 1, 0)              # team1 beat team2 head-to-head
    ranking.update_rank_fifa(conn, 2026, 1)
    assert _ranks(conn) == {1: 1, 2: 2}         # H2H winner first, despite worse overall GD
    # (the pre-2026 "overall GD first" order would have ranked team2 ahead)


def test_h2h_then_overall_for_three_way(conn):
    """3-way points tie: H2H ranks the team that beat the others on top; the two it
    couldn't separate by their mutual result fall to overall GD."""
    for t in (1, 2, 3):
        _team(conn, t)
    _standing(conn, "Group A", 1, 1, 3, 0, 2)   # team1 beat both -> top on H2H
    _standing(conn, "Group A", 2, 2, 3, 2, 4)   # team2 & team3 drew each other ->
    _standing(conn, "Group A", 3, 3, 3, 1, 3)   #   split by overall GD (2 > 1)
    _fixture(conn, 41, 1, 2, 1, 0)              # 1 beat 2
    _fixture(conn, 42, 1, 3, 1, 0)              # 1 beat 3
    _fixture(conn, 43, 2, 3, 1, 1)              # 2 drew 3
    ranking.update_rank_fifa(conn, 2026, 1)
    assert _ranks(conn) == {1: 1, 2: 2, 3: 3}


def test_fairplay_breaks_no_h2h_tie(conn):
    for t in (1, 2, 3):
        _team(conn, t)
    _standing(conn, "Group A", 1, 1, 1, 0, 1)   # API ranks team1 first
    _standing(conn, "Group A", 2, 2, 1, 0, 1)   # tied overall; they never played
    _fixture(conn, 10, 1, 3, 1, 1)              # context fixture for the card (vs team3)
    _card(conn, 10, 0, 1, "Red Card")           # team1 picks up a red
    ranking.update_rank_fifa(conn, 2026, 1)
    rf = _ranks(conn)
    assert rf[2] == 1 and rf[1] == 2            # cleaner team2 promoted above team1
    assert any("team 1" in w or "team 2" in w for w in integrity.reconcile_rank(conn))


def test_full_tie_preserves_api_rank(conn):
    for t in (1, 2):
        _team(conn, t)
    _standing(conn, "Group A", 1, 1, 1, 0, 1)   # fully tied, no H2H, equal fair-play
    _standing(conn, "Group A", 2, 2, 1, 0, 1)
    ranking.update_rank_fifa(conn, 2026, 1)
    assert _ranks(conn) == {1: 1, 2: 2}         # API order kept -> no spurious reorder
    assert integrity.reconcile_rank(conn) == []  # so no false-positive warning
