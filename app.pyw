#!/usr/bin/env python3
"""
PDF Book Translator - GUI Version
Drag and drop a PDF, set output name, choose pages, and translate.
"""

import os
import sys
import hashlib
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from fpdf import FPDF
import pdfplumber
import requests
from dotenv import load_dotenv

import textproc
import translator

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

if getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent

CHAR_LIMIT = 4500
FONT_PATH = r"C:\Windows\Fonts\arial.ttf"
ICON_PATH = APP_DIR / "book_icon.ico"
VT_API_URL = "https://www.virustotal.com/api/v3/files"

load_dotenv(APP_DIR / ".env")


def get_vt_api_key() -> str | None:
    key = os.getenv("VT_API_KEY")
    if key:
        return key.strip()
    return None


def calculate_sha256(file_path: str) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def check_virustotal(file_path: str) -> dict:
    api_key = get_vt_api_key()
    if not api_key:
        return {"error": "No VirusTotal API key configured"}

    file_hash = calculate_sha256(file_path)
    headers = {"x-apikey": api_key}
    
    try:
        response = requests.get(f"{VT_API_URL}/{file_hash}", headers=headers, timeout=30)
        if response.status_code == 404:
            return {"error": "File not found in VirusTotal database"}
        response.raise_for_status()
        data = response.json()
        stats = data.get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
        malicious = stats.get("malicious", 0)
        suspicious = stats.get("suspicious", 0)
        harmless = stats.get("harmless", 0)
        undetected = stats.get("undetected", 0)
        
        return {
            "malicious": malicious,
            "suspicious": suspicious,
            "harmless": harmless,
            "undetected": undetected,
            "total": malicious + suspicious + harmless + undetected,
            "hash": file_hash
        }
    except requests.exceptions.Timeout:
        return {"error": "VirusTotal request timed out"}
    except requests.exceptions.RequestException as e:
        return {"error": f"VirusTotal request failed: {e}"}


def extract_text_from_pdf(input_path: str) -> list[str]:
    pages = []
    with pdfplumber.open(input_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return pages


def translate_block(block: str, lang: str) -> str:
    try:
        return translator.translate(block, lang)
    except translator.TranslationFailed:
        return translator.FAIL_MARKER + block


def reshape_arabic(text: str) -> str:
    reshaped = arabic_reshaper.reshape(text)
    return str(get_display(reshaped))


def generate_pdf(translated_pages: list[str], output_path: str, title: str, lang: str):
    class BookPDF(FPDF):
        def __init__(self):
            super().__init__()
            if lang in ("ar", "he") and Path(FONT_PATH).exists():
                self.add_font("Arabic", "", FONT_PATH)
                self._use_arabic = True
            else:
                self._use_arabic = False
            self.set_auto_page_break(auto=True, margin=25)
            self.set_margins(left=20, top=20, right=20)
            self.book_title = title
            self._src_page = None
            self._first_block = False

        def header(self):
            if self.page_no() == 1:
                return
            if self._use_arabic:
                self.set_font("Arabic", size=9)
            else:
                self.set_font("Helvetica", size=9)
            self.set_text_color(120, 120, 120)
            display_title = reshape_arabic(self.book_title) if self.book_title and self._use_arabic else self.book_title
            self.cell(0, 8, display_title, align="C", new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(200, 200, 200)
            self.line(20, self.get_y(), self.w - 20, self.get_y())
            self.ln(6)

        def footer(self):
            self.set_y(-20)
            self.set_draw_color(200, 200, 200)
            self.line(20, self.get_y(), self.w - 20, self.get_y())
            self.ln(3)
            if self._use_arabic:
                self.set_font("Arabic", size=9)
            else:
                self.set_font("Helvetica", size=9)
            self.set_text_color(120, 120, 120)
            num = self._src_page if self._src_page is not None else self.page_no()
            self.cell(0, 8, str(num), align="C")

        def _emit_flow(self, text: str, font_size: float, line_h: float, rtl: bool):
            paragraphs = textproc.split_paragraphs(text)
            if not paragraphs:
                return
            self.set_font("Arabic" if rtl else "Helvetica", size=font_size)
            self.set_text_color(30, 30, 30)
            bottom_limit = self.h - 25
            for para in paragraphs:
                if not para.strip():
                    continue
                display = reshape_arabic(para) if rtl else para
                result = self.multi_cell(0, line_h, display, align="R" if rtl else "L",
                                         dry_run=True, output="LINES")
                lines = result if isinstance(result, list) else []
                need = len(lines) * line_h
                if need > bottom_limit - self.get_y() and not self._first_block:
                    self.add_page()
                    self._first_block = True
                if need > bottom_limit - self.get_y():
                    for sub in textproc.split_sentences(para):
                        sd = reshape_arabic(sub) if rtl else sub
                        self.multi_cell(0, line_h, sd, align="R" if rtl else "L",
                                        new_x="LMARGIN", new_y="NEXT")
                    self._first_block = False
                    continue
                self.multi_cell(0, line_h, display, align="R" if rtl else "L",
                                new_x="LMARGIN", new_y="NEXT")
                self._first_block = False
                self.ln(3)

        def add_page_text(self, text: str, src_page: int | None = None):
            self.add_page()
            self._first_block = True
            if src_page is not None:
                self._src_page = src_page
            self._emit_flow(text, 12, 8, bool(self._use_arabic))

    pdf = BookPDF()
    for idx, page_text in enumerate(translated_pages):
        if page_text.strip():
            pdf.add_page_text(page_text, src_page=idx + 1)
    pdf.output(output_path)


class TranslatorApp:
    def __init__(self):
        if HAS_DND:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.root.title("Book Translator")
        self.root.geometry("520x520")
        self.root.resizable(False, False)

        if ICON_PATH.exists():
            self.root.iconbitmap(ICON_PATH)

        self.input_path = tk.StringVar()
        self.output_name = tk.StringVar(value="translated")
        self.pages_var = tk.StringVar()
        self.lang_var = tk.StringVar(value="ar")
        self.is_translating = False

        self.build_ui()

        if HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self.on_drop)

    def build_ui(self):
        pad = {"padx": 20, "pady": 5}

        title_label = tk.Label(self.root, text="Book Translator", font=("Segoe UI", 16, "bold"))
        title_label.pack(pady=(15, 5))

        file_frame = tk.LabelFrame(self.root, text="PDF File", font=("Segoe UI", 10))
        file_frame.pack(fill="x", **pad)

        file_inner = tk.Frame(file_frame)
        file_inner.pack(fill="x", padx=10, pady=8)

        self.file_label = tk.Label(file_inner, text="No file selected", anchor="w", fg="gray")
        self.file_label.pack(side="left", fill="x", expand=True)

        browse_btn = tk.Button(file_inner, text="Browse", command=self.browse_file, width=10)
        browse_btn.pack(side="right")

        if HAS_DND:
            self.file_label.drop_target_register(DND_FILES)
            self.file_label.dnd_bind("<<Drop>>", self.on_drop)
            drop_hint = tk.Label(self.root, text="(or drag & drop a PDF on the file area)", fg="gray", font=("Segoe UI", 8))
            drop_hint.pack()

        settings_frame = tk.LabelFrame(self.root, text="Settings", font=("Segoe UI", 10))
        settings_frame.pack(fill="x", **pad)

        tk.Label(settings_frame, text="Output file name:", font=("Segoe UI", 10)).pack(anchor="w", padx=10, pady=(8, 0))
        out_entry = tk.Entry(settings_frame, textvariable=self.output_name, font=("Segoe UI", 10))
        out_entry.pack(fill="x", padx=10, pady=2)

        tk.Label(settings_frame, text="Pages (e.g. 1-10 or 1,3,5-8):", font=("Segoe UI", 10)).pack(anchor="w", padx=10, pady=(8, 0))
        pages_entry = tk.Entry(settings_frame, textvariable=self.pages_var, font=("Segoe UI", 10))
        pages_entry.pack(fill="x", padx=10, pady=2)

        tk.Label(settings_frame, text="Translate to:", font=("Segoe UI", 10)).pack(anchor="w", padx=10, pady=(8, 0))
        lang_frame = tk.Frame(settings_frame)
        lang_frame.pack(fill="x", padx=10, pady=(2, 8))

        languages = [("Arabic", "ar"), ("Spanish", "es"), ("French", "fr"),
                     ("German", "de"), ("Turkish", "tr"), ("Hebrew", "he"),
                     ("Hindi", "hi"), ("Portuguese", "pt")]
        for text, val in languages:
            tk.Radiobutton(lang_frame, text=text, variable=self.lang_var, value=val,
                           font=("Segoe UI", 9)).pack(side="left", padx=2)

        self.progress_label = tk.Label(self.root, text="", font=("Segoe UI", 9))
        self.progress_label.pack(**pad)

        self.progress_bar = ttk.Progressbar(self.root, mode="determinate", length=450)
        self.progress_bar.pack(**pad)

        self.translate_btn = tk.Button(self.root, text="Translate", font=("Segoe UI", 12, "bold"),
                                       command=self.start_translate, bg="#4CAF50", fg="white",
                                       width=20, height=2)
        self.translate_btn.pack(pady=10)

    def browse_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if path:
            self.set_file(path)

    def on_drop(self, event):
        path = event.data.strip()
        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        if path.lower().endswith(".pdf"):
            self.set_file(path)
        else:
            messagebox.showerror("Error", "Please drop a PDF file")

    def set_file(self, path: str):
        self.input_path.set(path)
        name = Path(path).stem
        self.output_name.set(f"{name}_translated")
        self.file_label.config(text=Path(path).name, fg="black")

    def parse_pages(self) -> set[int] | None:
        raw = self.pages_var.get().strip()
        if not raw:
            return None

        selected = set()
        for part in raw.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                selected.update(range(int(start) - 1, int(end)))
            else:
                selected.add(int(part) - 1)
        return selected

    def start_translate(self):
        if self.is_translating:
            return

        if not self.input_path.get():
            messagebox.showerror("Error", "Please select a PDF file")
            return

        api_key = get_vt_api_key()
        if api_key:
            self.is_translating = True
            self.translate_btn.config(state="disabled", text="Checking VirusTotal...")
            threading.Thread(target=self.check_vt_and_translate, daemon=True).start()
        else:
            self.is_translating = True
            self.translate_btn.config(state="disabled", text="Translating...")
            threading.Thread(target=self.do_translate, daemon=True).start()

    def check_vt_and_translate(self):
        input_path = self.input_path.get()
        self.root.after(0, lambda: self.update_progress("Checking VirusTotal...", 0))
        result = check_virustotal(input_path)
        
        def handle_result():
            if "error" in result:
                self.update_progress(f"VT: {result['error']}", 0)
                messagebox.showwarning("VirusTotal", f"Could not check file:\n{result['error']}")
                self.do_translate()
            else:
                malicious = result.get("malicious", 0)
                suspicious = result.get("suspicious", 0)
                harmless = result.get("harmless", 0)
                undetected = result.get("undetected", 0)
                total = result.get("total", 0)
                file_hash = result.get("hash", "N/A")
                
                self.update_progress(f"VT: {malicious} malicious | {suspicious} suspicious | {harmless} harmless | {total} total", 0)
                
                if malicious > 0 or suspicious > 0:
                    msg = f"Warning: File flagged by VirusTotal!\n\n"
                    msg += f"Malicious: {malicious}/{total}\n"
                    msg += f"Suspicious: {suspicious}/{total}\n"
                    msg += f"Harmless: {harmless}/{total}\n"
                    msg += f"Undetected: {undetected}/{total}\n"
                    msg += f"SHA256: {file_hash}\n\n"
                    msg += "Do you want to continue translation?"
                    
                    proceed = messagebox.askyesno("VirusTotal Warning", msg, icon="warning")
                    if proceed:
                        self.translate_btn.config(text="Translating...")
                        self.do_translate()
                    else:
                        self.reset_translate_button()
                else:
                    msg = f"File appears clean.\n\n"
                    msg += f"Harmless: {harmless}/{total}\n"
                    msg += f"Undetected: {undetected}/{total}\n"
                    msg += f"SHA256: {file_hash}"
                    messagebox.showinfo("VirusTotal", msg)
                    self.translate_btn.config(text="Translating...")
                    self.do_translate()
        
        self.root.after(0, handle_result)

    def reset_translate_button(self):
        self.is_translating = False
        self.translate_btn.config(state="normal", text="Translate")

    def do_translate(self):
        try:
            input_path = self.input_path.get()
            lang = self.lang_var.get()
            output_name = self.output_name.get().strip() or "translated"

            self.update_progress("Extracting text...", 0)
            all_pages = extract_text_from_pdf(input_path)

            page_filter = self.parse_pages()
            if page_filter is not None:
                all_pages = [p if i in page_filter else "" for i, p in enumerate(all_pages)]

            self.update_progress("Cleaning text...", 0)
            cleaned_pages = textproc.clean_pages(all_pages)

            nonempty = [(i, p) for i, p in enumerate(cleaned_pages) if p.strip()]
            if not nonempty:
                messagebox.showerror("Error", "No text found to translate")
                return

            total_units = sum(len(textproc.chunk_text(p, CHAR_LIMIT)) for _, p in nonempty)
            self.update_progress(f"Translating 0/{total_units} units...", 0)

            translated_pages = ["" for _ in cleaned_pages]
            done = 0
            for idx, page_text in nonempty:
                parts = [translate_block(b, lang) for b in textproc.chunk_text(page_text, CHAR_LIMIT)]
                translated_pages[idx] = "\n\n".join(parts)
                done += len(parts)
                pct = int((done / total_units) * 100)
                self.update_progress(f"Translating {done}/{total_units} units...", pct)

            self.update_progress("Generating PDF...", 100)

            output_dir = Path(input_path).parent
            output_path = output_dir / f"{output_name}.pdf"
            generate_pdf(translated_pages, str(output_path), output_name, lang)

            self.update_progress("Done!", 100)
            messagebox.showinfo("Done", f"Saved to:\n{output_path}")

        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.update_progress("Error occurred", 0)

        finally:
            self.is_translating = False
            self.translate_btn.config(state="normal", text="Translate")

    def update_progress(self, text: str, value: int):
        self.progress_label.config(text=text)
        self.progress_bar["value"] = value

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = TranslatorApp()
    app.run()
