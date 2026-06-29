import pytest

from src.scoring.event import parse_event_response


def test_parse_event_response_rejects_out_of_range_score():
    with pytest.raises(ValueError, match="score"):
        parse_event_response('{"score": 130, "reason": "x", "risks": []}')


def test_parse_event_response_requires_string_risks():
    with pytest.raises(ValueError, match="risks"):
        parse_event_response('{"score": 50, "reason": "x", "risks": [1]}')


def test_parse_event_response_rejects_long_reason():
    payload = '{"score": 50, "reason": "' + "长" * 61 + '", "risks": []}'
    with pytest.raises(ValueError, match="reason"):
        parse_event_response(payload)


def test_parse_event_response_returns_auditable_result():
    result = parse_event_response(
        '{"score": 55, "reason": "消息影响有限", "risks": []}',
        model="test-model",
        evidence=[{"title": "证据"}],
    )
    assert result.available is True
    assert result.score == 55
    assert result.model == "test-model"
    assert result.evidence == [{"title": "证据"}]


def test_parse_event_response_rejects_operation_instruction():
    with pytest.raises(ValueError, match="operation instruction"):
        parse_event_response(
            '{"score": 80, "reason": "建议立即加仓", "risks": []}'
        )
