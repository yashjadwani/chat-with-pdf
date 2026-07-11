from eval.judge import parse_judge_json


class TestParseJudgeJson:
    def test_plain_json(self):
        raw = '{"faithfulness": 5, "relevance": 4, "correctness": 3, "unsupported_claims": []}'
        verdict = parse_judge_json(raw)
        assert verdict == {
            "faithfulness": 5,
            "relevance": 4,
            "correctness": 3,
            "unsupported_claims": [],
        }

    def test_json_wrapped_in_code_fence(self):
        raw = 'Here is my verdict:\n```json\n{"faithfulness": 3, "relevance": 5, "correctness": 4, "unsupported_claims": ["the fee is $10"]}\n```'
        verdict = parse_judge_json(raw)
        assert verdict["faithfulness"] == 3
        assert verdict["correctness"] == 4
        assert verdict["unsupported_claims"] == ["the fee is $10"]

    def test_json_embedded_in_prose(self):
        raw = 'The answer is mostly grounded. {"faithfulness": 4, "relevance": 4, "correctness": 4, "unsupported_claims": []} Hope that helps.'
        assert parse_judge_json(raw)["faithfulness"] == 4

    def test_numeric_strings_are_coerced(self):
        raw = '{"faithfulness": "5", "relevance": "5", "correctness": "5", "unsupported_claims": []}'
        assert parse_judge_json(raw)["correctness"] == 5

    def test_out_of_range_faithfulness_rejected(self):
        raw = '{"faithfulness": 9, "relevance": 4, "correctness": 3, "unsupported_claims": []}'
        assert parse_judge_json(raw) is None

    def test_out_of_range_correctness_rejected(self):
        raw = '{"faithfulness": 5, "relevance": 4, "correctness": 0, "unsupported_claims": []}'
        assert parse_judge_json(raw) is None

    def test_missing_correctness_rejected(self):
        assert parse_judge_json('{"faithfulness": 5, "relevance": 4}') is None

    def test_garbage_rejected(self):
        assert parse_judge_json("I could not evaluate this.") is None

    def test_non_list_claims_normalized_to_empty(self):
        raw = '{"faithfulness": 5, "relevance": 5, "correctness": 5, "unsupported_claims": "none"}'
        assert parse_judge_json(raw)["unsupported_claims"] == []


class TestRegexFallback:
    def test_markdown_scores_without_json(self):
        raw = "**Faithfulness:** 5/5\n**Relevance:** 4/5\n**Correctness:** 3/5\nUnsupported: none"
        verdict = parse_judge_json(raw)
        assert verdict == {
            "faithfulness": 5,
            "relevance": 4,
            "correctness": 3,
            "unsupported_claims": [],
        }

    def test_malformed_json_trailing_comma(self):
        raw = '{"faithfulness": 4, "relevance": 3, "correctness": 2,}'  # invalid JSON
        verdict = parse_judge_json(raw)
        assert verdict["faithfulness"] == 4
        assert verdict["correctness"] == 2

    def test_prose_scores(self):
        raw = "Faithfulness: 5 out of 5. Relevance: 5. Correctness: 4. Well grounded."
        verdict = parse_judge_json(raw)
        assert verdict["faithfulness"] == 5
        assert verdict["correctness"] == 4

    def test_fallback_rejects_when_correctness_missing(self):
        raw = "Faithfulness is a 4 and relevance a 5, but I couldn't judge the rest."
        assert parse_judge_json(raw) is None

    def test_fallback_leaves_claims_empty(self):
        raw = "faithfulness = 3, relevance = 2, correctness = 4"
        assert parse_judge_json(raw)["unsupported_claims"] == []
