from backend.app.services.semantic_search import parse_query


def test_deterministic_search_parser():
    distracted = parse_query("Show when more than 10 students were distracted")
    assert {key: distracted[key] for key in ("metric", "operator", "value")} == {"metric": "distracted_students", "operator": ">", "value": 10.0}
    assert distracted["parser"] == "deterministic" and distracted["confidence"] == 1.0
    attendance = parse_query("Find classes where attendance was below 75%")
    assert {key: attendance[key] for key in ("metric", "operator", "value")} == {"metric": "attendance", "operator": "<", "value": 75.0}


def test_search_parser_session_and_time_constraints():
    parsed = parse_query("engagement below 50 in session 12 after 30 seconds")
    assert parsed["session_id"] == 12
    assert parsed["time_from"] == 30
