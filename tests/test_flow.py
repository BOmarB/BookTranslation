import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pdfplumber
from translate_book import TranslatedPDF


def render(pdf) -> str:
    with pdfplumber.open(io.BytesIO(bytes(pdf.output()))) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


def run_privacy_test():
    for name in ("app.py", "translate_book.py"):
        src = (PROJECT_ROOT / name).read_text(encoding="utf-8").lower()
        assert "virustotal" not in src, f"VirusTotal upload path re-added to {name}"
    print("  no VirusTotal upload path OK")


def run_latin_test():
    pdf = TranslatedPDF(title="Test", lang="en")
    pdf.add_entry("hello world", page_number=7)
    text = render(pdf)
    assert "hello world" in text, text
    assert "7" in text, text
    print("  latin page + footer OK")


def run_arabic_test():
    pdf = TranslatedPDF(title="مزرعة الحيوان", lang="ar")
    pdf.add_entry("الحيوانات كلها متساوية", page_number=3)
    text = render(pdf)
    assert text.strip(), "arabic page empty"
    assert "3" in text, text
    print("  arabic page + footer OK")


if __name__ == "__main__":
    run_privacy_test()
    run_latin_test()
    run_arabic_test()
    print("FLOW TESTS PASSED")
