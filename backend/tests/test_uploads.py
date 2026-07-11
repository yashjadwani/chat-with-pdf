from app.api.routes.documents import looks_like_pdf, sanitize_filename


class TestLooksLikePdf:
    def test_accepts_pdf_magic(self):
        assert looks_like_pdf(b"%PDF-1.7\n...") is True

    def test_accepts_pdf_with_leading_whitespace_or_bom(self):
        assert looks_like_pdf(b"\r\n  %PDF-1.4") is True

    def test_rejects_non_pdf(self):
        assert looks_like_pdf(b"<html>not a pdf</html>") is False

    def test_rejects_empty(self):
        assert looks_like_pdf(b"") is False


class TestSanitizeFilename:
    def test_strips_path_components(self):
        assert sanitize_filename("../../etc/passwd", "fallback.pdf") == "passwd"

    def test_strips_windows_path_components(self):
        assert sanitize_filename(r"C:\Users\x\report.pdf", "fallback.pdf") == "report.pdf"

    def test_replaces_unsafe_characters(self):
        assert sanitize_filename("a b<c>:d.pdf", "fallback.pdf") == "a b_c__d.pdf"

    def test_removes_control_characters(self):
        assert sanitize_filename("re\x00port\x1f.pdf", "fallback.pdf") == "report.pdf"

    def test_falls_back_when_empty(self):
        assert sanitize_filename("", "fallback.pdf") == "fallback.pdf"
        assert sanitize_filename(None, "fallback.pdf") == "fallback.pdf"
        assert sanitize_filename("///", "fallback.pdf") == "fallback.pdf"

    def test_caps_length(self):
        assert len(sanitize_filename("a" * 500 + ".pdf", "fallback.pdf")) <= 200
