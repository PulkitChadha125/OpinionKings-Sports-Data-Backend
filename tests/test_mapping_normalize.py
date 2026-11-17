from datetime import datetime, timedelta, timezone

from app.services.mapping import best_match, match_score
from app.services.normalize import as_list, extract_result_score, parse_oddspapi_fixture

T = datetime(2026, 11, 20, 19, tzinfo=timezone.utc)


def test_match_score_handles_suffixes_and_order():
    assert match_score("Arsenal FC", "Chelsea", T, "Arsenal", "Chelsea FC", T) >= 0.95
    assert match_score("Arsenal", "Chelsea", T, "Chelsea", "Arsenal", T) >= 0.9
    assert match_score("Arsenal", "Chelsea", T, "Arsenal", "Chelsea", T + timedelta(hours=5)) == 0.0


def test_best_match_threshold():
    target = {"home": "Mumbai Indians", "away": "Chennai Super Kings", "start_time": T}
    cands = [{"home": "Delhi Capitals", "away": "Punjab Kings", "start_time": T},
             {"home": "Mumbai Indians", "away": "Chennai Super Kings", "start_time": T + timedelta(minutes=30)}]
    match, score = best_match(target, cands)
    assert match is cands[1] and score > 0.9


def test_parse_oddspapi_fixture_from_docs_example():
    raw = {"fixtureId": "id1100013270505056", "statusId": 1, "sportId": 11, "sportName": "Basketball",
           "tournamentId": 132, "tournamentName": "NBA", "startTime": 1776729600,
           "participant1Name": "New York Knicks", "participant2Name": "Atlanta Hawks",
           "scores": {"result": {"period": "result", "participant1Score": 61, "participant2Score": 54}}}
    f = parse_oddspapi_fixture(raw)
    assert f["oddspapi_id"] == "id1100013270505056"
    assert f["home"] == "New York Knicks" and f["home_score"] == 61 and f["away_score"] == 54
    assert f["start_time"] == datetime.fromtimestamp(1776729600, tz=timezone.utc)


def test_as_list_variants():
    assert as_list([{"a": 1}]) == [{"a": 1}]
    assert as_list({"data": [{"a": 1}]}) == [{"a": 1}]
    assert as_list({"x": {"a": 1}, "y": {"a": 2}}) == [{"a": 1}, {"a": 2}]
    assert extract_result_score(None) == (None, None)
