from eval.metrics import hit_at_k, mean, mrr_at_k, page_recall_at_k

CASE = {"relevant_pages": [7], "answer_substrings": ["thirty (30) days"]}
RESULTS = [
    (3, "irrelevant text"),
    (7, "some clause"),
    (9, "requires thirty (30) days notice"),
]


class TestHitAtK:
    def test_hit_when_relevant_in_top_k(self):
        assert hit_at_k(RESULTS, CASE, 5) == 1.0

    def test_miss_when_relevant_outside_top_k(self):
        assert hit_at_k(RESULTS, CASE, 1) == 0.0

    def test_substring_match_is_case_insensitive(self):
        case = {"relevant_pages": [], "answer_substrings": ["E5-SMALL"]}
        assert hit_at_k([(1, "uses multilingual-e5-small")], case, 5) == 1.0


class TestMrrAtK:
    def test_reciprocal_rank_of_first_relevant(self):
        assert mrr_at_k(RESULTS, CASE, 5) == 0.5

    def test_zero_when_no_relevant_result(self):
        assert mrr_at_k([(1, "nothing"), (2, "here")], CASE, 5) == 0.0


class TestPageRecallAtK:
    def test_fraction_of_gold_pages_found(self):
        case = {"relevant_pages": [7, 9, 11], "answer_substrings": []}
        assert page_recall_at_k(RESULTS, case, 5) == 2 / 3

    def test_none_when_case_has_no_gold_pages(self):
        case = {"relevant_pages": [], "answer_substrings": ["x"]}
        assert page_recall_at_k(RESULTS, case, 5) is None


class TestMean:
    def test_ignores_none_values(self):
        assert mean([1.0, None, 0.0]) == 0.5

    def test_empty_input_is_zero(self):
        assert mean([]) == 0.0
        assert mean([None]) == 0.0
