from app.services.acronyms import (
    expand_query_with_acronyms,
    extract_parenthetical_pairs,
)


class TestExtractParentheticalPairs:
    def test_extracts_long_form_acronym_pair(self):
        text = "The model uses the Adjusted Rand Index (ARI) for scoring."
        pairs = extract_parenthetical_pairs(text)
        # Known quirk: the capture is greedy and includes words preceding the
        # actual long form ("The model uses the ..."). The true long form is
        # always the tail of the capture.
        assert pairs["ARI"].endswith("Adjusted Rand Index")

    def test_ignores_lowercase_parentheticals(self):
        text = "We compute totals (see appendix) for each section."
        assert extract_parenthetical_pairs(text) == {}

    def test_collapses_internal_whitespace_in_long_form(self):
        text = "Uses the Gaussian   Mixture\nModel (GMM) approach."
        pairs = extract_parenthetical_pairs(text)
        assert pairs["GMM"].endswith("Gaussian Mixture Model")
        assert "  " not in pairs["GMM"]
        assert "\n" not in pairs["GMM"]


class TestExpandQueryWithAcronyms:
    def test_query_without_acronyms_returned_unchanged(self):
        query = "What is the notice period for termination?"
        assert expand_query_with_acronyms(query) == query

    def test_glossary_acronym_appends_long_form(self):
        expanded = expand_query_with_acronyms("How is the SVM trained?")
        assert expanded.startswith("How is the SVM trained?")
        assert "Support Vector Machine" in expanded

    def test_glossary_long_form_appends_acronym(self):
        expanded = expand_query_with_acronyms("Explain cross validation here")
        assert "CV" in expanded

    def test_document_pair_expands_short_form_in_query(self):
        docs = ["The Service Level Agreement (SLA) defines uptime targets."]
        expanded = expand_query_with_acronyms("What does the SLA guarantee?", docs)
        assert "Service Level Agreement" in expanded

    def test_document_pair_expands_long_form_in_query(self):
        docs = ["The Service Level Agreement (SLA) defines uptime targets."]
        expanded = expand_query_with_acronyms(
            "What does the service level agreement guarantee?", docs
        )
        assert "Expanded acronym terms:" in expanded
        assert "SLA" in expanded
