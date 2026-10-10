#!/usr/bin/env python3
"""
Book Translator - Gemini Edition
Translates a PDF book page-by-page (whole page, single request) into Arabic
using the Gemini API, then builds an RTL Arabic PDF.

Usage:
    python translate_book.py --input "book.pdf" --output "كتاب.pdf"
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from fpdf import FPDF
from google import genai
from google.genai import types
import pdfplumber


DEFAULT_MODEL = "gemini-flash-lite-latest"
DEFAULT_TEMPERATURE = 0.6
REQUEST_SPACING = 4.0
MAX_OUTPUT_TOKENS = 4096
MAX_RETRIES = 3
RETRY_BACKOFF = 20

AZURE_TO_LANG = "ar"


def load_env_file(path: str = ".env") -> None:
    """Minimal .env loader: sets missing env vars from a local .env file.

    Checks the current directory and, when frozen, the EXE's directory.
    """
    candidates = [Path(path)]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / path)
    for p in candidates:
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            pass


load_env_file()

SYSTEM_PROMPT = """أنت مترجم أدبي محترف متخصص في ترجمة الروايات من الإنجليزية إلى العربية.
ترجم النص المرفق كاملاً كما هو، صفحةً متصلة، بأسلوب أدبي سلس ورصين يحافظ على جمال النص الأصلي.
قواعد صارمة:
- لا تُلخّص ولا تحذف أي جملة ولا تضف أي محتوى غير موجود في النص الأصلي.
- حافظ على المعنى الدقيق والحوارات والشخصيات ونبرة السرد والترقيم المنطقي.
- أعِد النص العربي المترجم فقط، بلا أي مقدمة أو تعليق أو علامات اقتباس حوله."""


class QuotaExhausted(Exception):
    """Raised when the Gemini free-tier daily/minute quota is exhausted."""


def clean_page_text(text: str) -> str:
    """Whole-page, no newlines: collapse every whitespace run into one space."""
    return re.sub(r"\s+", " ", text or "").strip()


def extract_text_from_pdf(input_path: str) -> list[str]:
    pages = []
    with pdfplumber.open(input_path) as pdf:
        for page in enumerate(pdf.pages):
            i = page[0]
            page_obj = page[1]
            text = page_obj.extract_text() or ""
            pages.append(text)
    return pages


def parse_pages(pages_str: str, total: int) -> set[int]:
    if not pages_str:
        return set(range(total))
    selected = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            selected.update(range(int(start) - 1, min(int(end), total)))
        else:
            idx = int(part) - 1
            if 0 <= idx < total:
                selected.add(idx)
    return selected


class GeminiBackend:
    """Pluggable translation backend: one call per whole page."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 temperature: float = DEFAULT_TEMPERATURE,
                 thinking_budget: int | None = None):
        self.model = model
        self.temperature = temperature
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=temperature,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            safety_settings=[
                types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH)
                for c in (
                    types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                )
            ],
        )
        if thinking_budget is not None:
            self.config.thinking_config = types.ThinkingConfig(thinking_budget=thinking_budget)
        try:
            self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        except Exception as e:
            raise RuntimeError(
                f"Cannot create Gemini client: {e}\n"
                "Make sure GEMINI_API_KEY (or GOOGLE_API_KEY) is set, or pass a key."
            ) from e

    def _is_quota_error(self, e: Exception) -> bool:
        msg = str(e)
        return "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()

    def _is_retryable(self, e: Exception) -> bool:
        msg = str(e)
        for token in ("500", "503", "UNAVAILABLE", "INTERNAL", "timeout", "timed out", "connection"):
            if token in msg:
                return True
        return False

    def translate_page(self, text: str, log=None) -> str:
        log = log or (lambda m: print(m, flush=True))
        cleaned = clean_page_text(text)
        if not cleaned:
            return ""

        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=cleaned,
                    config=self.config,
                )
                result = (response.text or "").strip()
                if result:
                    return result
                last_err = RuntimeError(f"Empty response (finish_reason={response.candidates[0].finish_reason if response.candidates else 'unknown'})")
            except Exception as e:
                if self._is_quota_error(e):
                    raise QuotaExhausted(str(e)) from e
                if not self._is_retryable(e):
                    raise RuntimeError(f"Gemini API error (not retrying): {e}") from e
                last_err = e

            wait = RETRY_BACKOFF * (attempt + 1)
            log(f"    Retry {attempt + 1}/{MAX_RETRIES} after error: {last_err}")
            log(f"    Waiting {wait}s...")
            time.sleep(wait)

        raise RuntimeError(f"Translation failed after {MAX_RETRIES} retries: {last_err}")


class AzureBackend:
    """Azure Translator backend: neural MT, free tier 2M chars/month."""

    ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"

    def __init__(self, key: str | None = None, region: str | None = None):
        self.key = key or os.environ.get("AZURE_TRANSLATOR_KEY")
        self.region = region or os.environ.get("AZURE_TRANSLATOR_REGION") or "global"
        if not self.key:
            raise RuntimeError(
                "Azure Translator key not found. Set AZURE_TRANSLATOR_KEY (and AZURE_TRANSLATOR_REGION) "
                "in your environment or .env file."
            )

    def translate_page(self, text: str, log=None) -> str:
        cleaned = clean_page_text(text)
        if not cleaned:
            return ""

        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(
                    self.ENDPOINT,
                    params={"api-version": "3.0", "from": "en", "to": AZURE_TO_LANG},
                    headers={
                        "Ocp-Apim-Subscription-Key": self.key,
                        "Ocp-Apim-Subscription-Region": self.region,
                        "Content-Type": "application/json",
                    },
                    json=[{"Text": cleaned[:10000]}],
                    timeout=60,
                )
                if response.status_code == 200:
                    data = response.json()
                    return data[0]["translations"][0]["text"].strip()
                last_err = RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
            except Exception as e:
                last_err = e
            wait = RETRY_BACKOFF * (attempt + 1)
            if log:
                log(f"    Azure retry {attempt + 1}/{MAX_RETRIES}: {last_err}")
            time.sleep(wait)

        raise RuntimeError(f"Azure translation failed after {MAX_RETRIES} retries: {last_err}")


def progress_path_for(output_path: str) -> Path:
    return Path(output_path).with_suffix(Path(output_path).suffix + ".progress.jsonl")


def init_progress(output_path: str, input_path: str) -> None:
    """Start a fresh progress file tagged with the source book identity."""
    try:
        size = Path(input_path).stat().st_size
    except OSError:
        size = -1
    p = progress_path_for(output_path)
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"_meta": True, "input": str(Path(input_path).resolve()), "size": size}, ensure_ascii=False) + "\n")


def load_progress(output_path: str, input_path: str | None = None) -> dict[int, str]:
    """Return {page_index: translated_text}. Empty if the progress belongs to a different book."""
    p = progress_path_for(output_path)
    done: dict[int, str] = {}
    if not p.exists():
        return done
    meta_ok = input_path is None
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("_meta"):
                if input_path is not None:
                    try:
                        size = Path(input_path).stat().st_size
                    except OSError:
                        size = -1
                    if rec.get("input") == str(Path(input_path).resolve()) and rec.get("size") == size:
                        meta_ok = True
                continue
            if "page" in rec:
                done[rec["page"]] = rec.get("text", "")
    return done if meta_ok else {}


def append_progress(output_path: str, page_index: int, text: str) -> None:
    p = progress_path_for(output_path)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"page": page_index, "text": text}, ensure_ascii=False) + "\n")


def clear_progress(output_path: str) -> None:
    p = progress_path_for(output_path)
    if p.exists():
        p.unlink()


class ArabicPDF(FPDF):
    """RTL Arabic PDF using fpdf2's built-in HarfBuzz text shaping.

    Logical-order Arabic is passed straight to multi_cell; the shaping
    engine handles presentation forms and bidi per line, so sentence
    and line order stays top-to-bottom in reading order.
    """

    def __init__(self, title: str = ""):
        super().__init__()
        self.book_title = title
        self.add_font("Noto", "", r"C:\Windows\Fonts\arial.ttf")
        self.set_text_shaping(use_shaping_engine=True, direction="rtl", language="ar")
        self.set_auto_page_break(auto=True, margin=25)
        self.set_margins(left=20, top=20, right=20)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Noto", size=9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, self.book_title, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.line(20, self.get_y(), self.w - 20, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-20)
        self.set_draw_color(200, 200, 200)
        self.line(20, self.get_y(), self.w - 20, self.get_y())
        self.ln(3)
        self.set_font("Noto", size=9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, str(self.page_no()), align="C")

    def add_translated_page(self, text: str):
        self.add_page()
        self.set_font("Noto", size=12)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 8, text, align="R")


def build_pdf(page_texts: list[str], output_path: str, title: str = "") -> None:
    pdf = ArabicPDF(title=title)
    for text in page_texts:
        if text and text.strip():
            pdf.add_translated_page(text)
    pdf.output(output_path)


def run_translation(
    input_path: str,
    output_path: str,
    api_key: str | None = None,
    backend: str = "gemini",
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    pages: str = "",
    title: str = "",
    spacing: float = REQUEST_SPACING,
    resume: bool = True,
    log_callback=None,
    status_callback=None,
    progress_callback=None,
) -> dict:
    """Translate the whole book. Returns summary dict.

    Raises QuotaExhausted (progress saved) when the daily quota runs out.
    """
    log = log_callback or (lambda m: print(m, flush=True))
    status = status_callback or (lambda t: None)
    progress = progress_callback or (lambda cur, tot: None)

    in_path = Path(input_path)
    out_path = Path(output_path)
    if not in_path.exists():
        raise FileNotFoundError(f"File not found: {input_path}")
    if in_path.resolve() == out_path.resolve():
        raise ValueError("Output file must be different from the input file.")

    if backend == "azure":
        translator = AzureBackend()
        log("Backend: Azure Translator")
    else:
        translator = GeminiBackend(api_key=api_key, model=model, temperature=temperature)
        log(f"Backend: Gemini ({model})")

    status("Extracting text...")
    log(f"Extracting text from: {in_path.name}")
    all_pages = extract_text_from_pdf(str(in_path))
    selected = parse_pages(pages, len(all_pages))
    target = [i for i in sorted(selected) if all_pages[i].strip()]

    for i, t in enumerate(all_pages):
        if not t.strip():
            log(f"  Page {i + 1}: no extractable text (image-only?), skipped.")

    already_done = {}
    prog_file = progress_path_for(str(out_path))
    if resume and prog_file.exists():
        already_done = load_progress(str(out_path), str(in_path))
        if not already_done:
            log("Ignoring saved progress: it belongs to a different book.")
    if not already_done:
        if prog_file.exists():
            clear_progress(str(out_path))
        init_progress(str(out_path), str(in_path))

    todo = [i for i in target if i not in already_done]
    log(f"Model: {model} | Pages selected: {len(target)} | Already done: {len(target) - len(todo)} | Remaining: {len(todo)}")

    total = len(target)
    done_count = total - len(todo)
    start_time = time.time()

    for n, page_idx in enumerate(todo, start=1):
        status(f"Translating page {page_idx + 1} ({done_count + n}/{total})...")
        progress(done_count + n, total)
        log(f"Translating page {page_idx + 1}/{len(all_pages)}...")

        cleaned = clean_page_text(all_pages[page_idx])
        if not cleaned:
            append_progress(str(out_path), page_idx, "")
            continue

        t0 = time.time()
        try:
            arabic = translator.translate_page(all_pages[page_idx], log=log)
        except QuotaExhausted as e:
            append_progress(str(out_path), page_idx, "")
            log(f"\nDaily quota exhausted at page {page_idx + 1}. Progress saved.")
            log("Re-run this same command after the quota resets (midnight Pacific) to continue.")
            raise QuotaExhausted(str(e)) from e

        append_progress(str(out_path), page_idx, arabic)
        dt = time.time() - t0
        remaining = len(todo) - n
        eta = (dt + spacing) * remaining
        log(f"    Page {page_idx + 1} done in {dt:.1f}s | ETA: {eta / 60:.1f} min")

        if n < len(todo):
            time.sleep(spacing)

    progress(total, total)
    status("Building PDF...")
    done_map = load_progress(str(out_path), str(in_path))
    page_indices = sorted(set(done_map.keys()) | selected)
    page_texts = [done_map.get(i, "") for i in page_indices]
    build_pdf(page_texts, str(out_path), title=title)

    elapsed = time.time() - start_time
    log(f"\nDone! Output saved to: {out_path}")
    log(f"Pages translated: {sum(1 for t in page_texts if t.strip())} | New pages this run: {len(todo)} | Time: {elapsed / 60:.1f} min")
    log("Progress file kept — re-run with more pages later to extend this same PDF.")
    return {"total": total, "new": len(todo), "output": str(out_path)}


def test_one_page(input_path: str, page_number: int = 1, api_key: str | None = None,
                  backend: str = "gemini",
                  model: str = DEFAULT_MODEL, temperature: float = DEFAULT_TEMPERATURE) -> tuple[str, str]:
    """Translate a single page for quality testing. Returns (english, arabic)."""
    pages = extract_text_from_pdf(input_path)
    if not 1 <= page_number <= len(pages):
        raise ValueError(f"Page {page_number} out of range (book has {len(pages)} pages)")
    english = clean_page_text(pages[page_number - 1])
    if backend == "azure":
        translator = AzureBackend()
    else:
        translator = GeminiBackend(api_key=api_key, model=model, temperature=temperature)
    arabic = translator.translate_page(pages[page_number - 1])
    return english, arabic


def main():
    parser = argparse.ArgumentParser(description="Translate a PDF book to Arabic with Gemini")
    parser.add_argument("--input", "-i", required=True, help="Input PDF path")
    parser.add_argument("--output", "-o", default="translated.pdf", help="Output PDF path")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL, help=f"Gemini model (default: {DEFAULT_MODEL})")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--pages", "-p", type=str, default="", help="Page range, e.g. '20-44' or '1,3,5-8'")
    parser.add_argument("--title", "-t", type=str, default="", help="Book title for header")
    parser.add_argument("--spacing", type=float, default=REQUEST_SPACING, help="Seconds between requests (default: 4)")
    parser.add_argument("--backend", "-b", choices=["gemini", "azure"], default="gemini", help="Translation backend (default: gemini)")
    parser.add_argument("--fresh", action="store_true", help="Ignore saved progress and start over")
    args = parser.parse_args()

    try:
        run_translation(
            input_path=args.input,
            output_path=args.output,
            backend=args.backend,
            model=args.model,
            temperature=args.temperature,
            pages=args.pages,
            title=args.title,
            spacing=args.spacing,
            resume=not args.fresh,
        )
    except QuotaExhausted:
        sys.exit(2)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
