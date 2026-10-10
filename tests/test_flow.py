import io
import re
import sys

sys.path.insert(0, r"C:\Users\yachk\Downloads\Projects\Book-trans")

import pdfplumber
from translate_book import ArabicPDF, GenericPDF


def run_latin_test():
    paras = [
        "aaaaaaaa " * 2200,
        "bbbbbbbb " * 300,
        "cccccccc " * 1800,
        "dddddddd " * 200,
        "eeeeeeee " * 2500,
    ]
    pdf = GenericPDF("en", title="Test")
    pdf.add_translated_page("\n\n".join(paras[0:3]), src_page=1)
    pdf.add_translated_page("\n\n".join(paras[3:5]), src_page=2)
    data = bytes(pdf.output())

    with pdfplumber.open(io.BytesIO(data)) as doc:
        sheets = []
        for i, pg in enumerate(doc.pages, 1):
            raw = pg.extract_text() or ""
            body_lines = []
            footer = None
            for line in raw.splitlines():
                if line.strip() == "Test":
                    continue
                if re.fullmatch(r"\s*\d{1,4}\s*", line):
                    footer = int(line.strip())
                    continue
                body_lines.append(line)
            body = re.sub(r"\s+", " ", " ".join(body_lines)).strip()
            sheets.append((i, footer, body, raw))

    expected = re.sub(r"\s+", " ", "\n\n".join(paras)).strip()
    pos = 0
    for num, footer, body, _ in sheets:
        assert body, f"sheet {num} empty"
        while pos < len(expected) and expected[pos] == " ":
            pos += 1
        seg = expected[pos : pos + len(body)]
        assert body == seg, (
            f"sheet {num}: body not contiguous continuation\n body={body[:60]!r}\n expected@{pos}={expected[pos:pos+60]!r}"
        )
        pos += len(body)
        assert footer is not None, f"sheet {num}: missing footer"
        assert footer in (1, 2), f"sheet {num}: footer {footer} should be src page"
        print(f"  latin sheet {num}: footer={footer} len={len(body)} OK")

    while pos < len(expected) and expected[pos] == " ":
        pos += 1
    assert pos == len(expected), f"text loss: consumed {pos}/{len(expected)}"
    # fresh page per input page => sheet 1 footer must be 1 and sheet that starts
    # page 2 (first sheet with footer 2) must begin with paragraph[3]'s head "dddd"
    first_two = [s for s in sheets if s[1] == 2][0]
    assert first_two[2].startswith("dddd"), "page 2 did not start at paragraph boundary"
    print("  fresh-page paragraph-start check OK")
    print("LATIN PAGINATION TEST PASSED")


def run_arabic_test():
    paras_ar = [
        "الحيوانات كلها متساوية ولكن بعضها أكثر مساواة من غيرها. " * 120,
        "لقد تم استلام البيض الأربعة وقرارهم القرار الحكيم. " * 50,
        "وقامت جميع الحيوانات بالدخول إلى الحظيرة الكبيرة والنقاش الحاد. " * 120,
    ]
    pdf = ArabicPDF(title="مزرعة الحيوان")
    pdf.add_translated_page("\n\n".join(paras_ar), src_page=3)
    pdf.add_translated_page(paras_ar[2], src_page=4)
    data = bytes(pdf.output())

    with pdfplumber.open(io.BytesIO(data)) as doc:
        assert len(doc.pages) >= 2, "RTL should overflow to multiple sheets"
        for i, pg in enumerate(doc.pages, 1):
            raw = pg.extract_text() or ""
            foot = [l.strip() for l in raw.splitlines() if re.fullmatch(r"\d{1,4}", l.strip())]
            assert foot, f"arabic sheet {i}: no footer"
            assert int(foot[-1]) in (3, 4), f"arabic sheet {i}: footer {foot} wrong"
            body = re.sub(r"\s+", "", raw)
            assert len(body) > 40, f"arabic sheet {i}: no body"
            print(f"  arabic sheet {i}: footer={foot[-1]} body_chars={len(body)} OK")

    print("ARABIC PAGINATION TEST PASSED")


if __name__ == "__main__":
    run_latin_test()
    run_arabic_test()