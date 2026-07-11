from eval.judge import parse_judge_json


class TestParseJudgeJson:
    def test_plain_json(self):
        raw = '{"faithfulness": 5, "relevance": 4, "unsupported_claims": []}'
        verdict = parse_judge_json(raw)
        assert verdict == {"faithfulness": 5, "relevance": 4, "unsupported_claims": []}

    def test_json_wrapped_in_code_fence(self):
        raw = 'Here is my verdict:\n```json\n{"faithfulness": 3, "relevance": 5, "unsupported_claims": ["the fee is $10"]}\n```'
        verdict = parse_judge_json(raw)
        assert verdict["faithfulness"] == 3
        assert verdict["unsupported_claims"] == ["the fee is $10"]

    def test_json_embedded_in_prose(self):
        raw = 'The answer is mostly grounded. {"faithfulness": 4, "relevance": 4, "unsupported_claims": []} Hope that helps.'
        assert parse_judge_json(raw)["faithfulness"] == 4

    def test_numeric_strings_are_coerced(self):
        raw = '{"faithfulness": "5", "relevance": "5", "unsupported_claims": []}'
        assert parse_judge_json(raw)["faithfulness"] == 5

    def test_out_of_range_score_rejected(self):
        raw = '{"faithfulness": 9, "relevance": 4, "unsupported_claims": []}'
        assert parse_judge_json(raw) is None

    def test_missing_keys_rejected(self):
        assert parse_judge_json('{"faithfulness": 5}') is None

    def test_garbage_rejected(self):
        assert parse_judge_json("I could not evaluate this.") is None

    def test_non_list_claims_normalized_to_empty(self):
        raw = '{"faithfulness": 5, "relevance": 5, "unsupported_claims": "none"}'
        assert parse_judge_json(raw)["unsupported_claims"] == []
