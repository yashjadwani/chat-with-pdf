import json

from eval.results import _doc_label, save_run


class TestDocLabel:
    def test_single_document_uses_its_id(self):
        assert _doc_label(["doc-a", "doc-a", "doc-a"]) == "doc-a"

    def test_multiple_documents_labelled_multi(self):
        assert _doc_label(["doc-a", "doc-b"]) == "multi"


class TestSaveRun:
    def test_writes_summary_then_case_records(self, tmp_path, monkeypatch):
        import eval.results as results_module

        monkeypatch.setattr(results_module, "EVAL_DIR", tmp_path)

        path = save_run(
            kind="retrieval",
            k=5,
            dataset="eval/dataset.json",
            document_ids=["doc-a", "doc-a"],
            summary_metrics={"pipeline": {"hit": 1.0}},
            case_records=[{"id": "c1", "document_id": "doc-a", "question": "q?"}],
        )

        assert path.parent == tmp_path / "results"
        assert path.name.startswith("results_retrieval_doc-a_")
        assert path.suffix == ".jsonl"

        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert lines[0]["record"] == "run"
        assert lines[0]["kind"] == "retrieval"
        assert lines[0]["num_cases"] == 1
        assert lines[1]["record"] == "case"
        assert lines[1]["id"] == "c1"

    def test_filenames_do_not_collide_across_kinds(self, tmp_path, monkeypatch):
        import eval.results as results_module

        monkeypatch.setattr(results_module, "EVAL_DIR", tmp_path)

        common = dict(k=5, dataset="d", document_ids=["doc-a"], summary_metrics={}, case_records=[])
        retrieval_path = save_run(kind="retrieval", **common)
        judge_path = save_run(kind="judge", **common)

        assert retrieval_path != judge_path
