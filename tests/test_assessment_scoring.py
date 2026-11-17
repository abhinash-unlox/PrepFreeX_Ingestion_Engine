from engines.assessment.scoring import ScoringRule, score_response


def test_mcq_single_scoring():
    rule = ScoringRule(correct=4.0, incorrect=-1.0, unattempted=0.0)

    # Correct response
    correct, marks = score_response("mcq_single", {"positions": [2]}, {"type": "option", "positions": [2]}, rule)
    assert correct is True
    assert marks == 4.0

    # Incorrect response
    correct, marks = score_response("mcq_single", {"positions": [1]}, {"type": "option", "positions": [2]}, rule)
    assert correct is False
    assert marks == -1.0

    # Unattempted response
    correct, marks = score_response("mcq_single", None, {"type": "option", "positions": [2]}, rule)
    assert correct is False
    assert marks == 0.0


def test_numerical_scoring():
    rule = ScoringRule(correct=4.0, incorrect=-1.0, unattempted=0.0)

    # Exact match
    correct, marks = score_response("numerical", {"value": 50}, {"type": "numeric", "value": 50, "tolerance": 0.0}, rule)
    assert correct is True
    assert marks == 4.0

    # Within tolerance
    correct, marks = score_response("numerical", {"value": 50.05}, {"type": "numeric", "value": 50.0, "tolerance": 0.1}, rule)
    assert correct is True
    assert marks == 4.0

    # Outside tolerance
    correct, marks = score_response("numerical", {"value": 52.0}, {"type": "numeric", "value": 50.0, "tolerance": 0.1}, rule)
    assert correct is False
    assert marks == -1.0

