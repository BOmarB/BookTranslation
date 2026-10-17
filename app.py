#!/usr/bin/env python3
"""
Book Translator GUI
Drag & drop a PDF -> whole-page translation (Gemini / Azure / Google-free)
-> RTL Arabic PDF (also French / English), images kept, original page numbers.
"""

import os
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from tkinterdnd2 import DND_FILES, TkinterDnD

import translate_book as tb


MODEL_OPTIONS = {
    "gemini": [
        "gemini-flash-lite-latest",
        "gemini-3-flash-preview",
        "gemini-3.8-flash",
        "gemini-2.5-flash",
    ],
    "nvidia": [
        "meta/muse-glimmer-30b",
    ],
}
BACKENDS = ["gemini", "azure", "nvidia", "google-free"]
LANG_NAMES = {"ar": "Arabic", "fr": "French", "en": "English"}
LANG_LABELS = [f"{name} ({code})" for code, name in LANG_NAMES.items()]


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Book Translator")
        screen_h = self.winfo_screenheight()
        win_h = min(700, max(480, screen_h - 150))
        self.geometry(f"720x{win_h}")
        self.minsize(620, 520)
        self.configure(bg="#1e1e2e")

        self.pdf_path = tk.StringVar()
        self.output_name = tk.StringVar(value="")
        self.pages_str = tk.StringVar()
        self.title_str = tk.StringVar()
        self.model_var = tk.StringVar(value=tb.DEFAULT_MODEL)
        self.temp_var = tk.StringVar(value=str(tb.DEFAULT_TEMPERATURE))
        self.backend_var = tk.StringVar(value="gemini")
        self.lang_var = tk.StringVar(value="Arabic (ar)")

        self.is_running = False
        self.stop_event = threading.Event()
        self.cancel_event = threading.Event()
        self.force_var = tk.BooleanVar(value=False)
        self.page_count = 0
        self.vt_stats = None

        self._set_icon()
        self._build_ui()

    # ---------- setup ----------

    def _set_icon(self):
        candidates = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).parent / "book_trans.ico")
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                candidates.append(Path(meipass) / "book_trans.ico")
        else:
            candidates.append(Path(__file__).parent / "book_trans.ico")
        for c in candidates:
            if c.exists():
                try:
                    self.iconbitmap(str(c))
                except Exception:
                    pass
                break

    def _build_ui(self):
        BG = "#1e1e2e"
        FG = "#cdd6f4"
        ACCENT = "#89b4fa"
        GREEN = "#a6e3a1"
        RED = "#f38ba8"
        ENTRY_BG = "#313244"
        SUBTLE = "#6c7086"

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor=ENTRY_BG, background=ACCENT, borderwidth=0)

        tk.Label(
            self, text="Book Translator", font=("Segoe UI", 13, "bold"),
            bg=BG, fg=FG,
        ).pack(pady=(10, 1))
        tk.Label(
            self, text="PDF  →  full-page translation  ·  images kept  ·  original page numbers",
            font=("Segoe UI", 8), bg=BG, fg=SUBTLE,
        ).pack()

        self.key_label = tk.Label(self, text="", font=("Segoe UI", 8), bg=BG, fg=GREEN)
        self.key_label.pack(pady=(2, 0))

        drop = tk.Frame(self, bg=ENTRY_BG, highlightbackground=ACCENT, highlightthickness=1, height=44)
        drop.pack(fill="x", padx=24, pady=(5, 3))
        drop.pack_propagate(False)
        drop.drop_target_register(DND_FILES)
        drop.dnd_bind("<<Drop>>", self.on_drop)

        self.drop_label = tk.Label(
            drop, text="Drop PDF here or click Browse",
            font=("Segoe UI", 10), bg=ENTRY_BG, fg=SUBTLE, cursor="hand2",
        )
        self.drop_label.pack(expand=True)
        self.drop_label.bind("<Button-1>", lambda e: self.browse_file())

        tk.Button(
            self, text="Browse...", command=self.browse_file,
            bg=ACCENT, fg=BG, font=("Segoe UI", 8, "bold"),
            relief="flat", padx=10, pady=1, cursor="hand2",
        ).pack(pady=(3, 3))

        self.vt_label = tk.Label(self, text="VirusTotal: —", font=("Segoe UI", 8),
                                 bg=BG, fg=SUBTLE, cursor="hand2")
        self.vt_label.pack()
        self.vt_label.bind("<Button-1>", lambda e: self._rescan())

        form = tk.Frame(self, bg=BG)
        form.pack(fill="x", padx=24)

        def entry_row(label, var, width=14):
            row = tk.Frame(form, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, width=width, anchor="w", bg=BG, fg=FG,
                     font=("Segoe UI", 9)).pack(side="left")
            tk.Entry(row, textvariable=var, bg=ENTRY_BG, fg=FG,
                     insertbackground=FG, relief="flat", font=("Segoe UI", 9)).pack(
                side="left", fill="x", expand=True, ipady=2)
            return row

        entry_row("Output name:", self.output_name)
        entry_row("Pages:", self.pages_str)
        entry_row("Book title:", self.title_str)

        tk.Label(
            form, text="leave empty = whole book   ·   40 = one page   ·   1-40 or 60-80 = range   ·   40,60-62 = mix",
            font=("Segoe UI", 8), bg=BG, fg=SUBTLE, anchor="w",
        ).pack(fill="x", pady=(0, 2))

        tk.Checkbutton(
            form, text="Redo selected pages (ignore their saved progress)",
            variable=self.force_var, bg=BG, fg=SUBTLE, selectcolor=ENTRY_BG,
            activebackground=BG, activeforeground=FG, font=("Segoe UI", 8),
            cursor="hand2",
        ).pack(anchor="w", pady=(0, 2))

        row = tk.Frame(form, bg=BG)
        row.pack(fill="x", pady=1)
        tk.Label(row, text="Backend:", width=14, anchor="w", bg=BG, fg=FG,
                 font=("Segoe UI", 9)).pack(side="left")
        backend_menu = ttk.Combobox(row, textvariable=self.backend_var, state="readonly",
                                    values=BACKENDS, font=("Segoe UI", 9))
        backend_menu.pack(side="left", fill="x", expand=True)
        backend_menu.bind("<<ComboboxSelected>>", lambda e: self._on_backend_change())

        row = tk.Frame(form, bg=BG)
        row.pack(fill="x", pady=1)
        tk.Label(row, text="Language:", width=14, anchor="w", bg=BG, fg=FG,
                 font=("Segoe UI", 9)).pack(side="left")
        ttk.Combobox(row, textvariable=self.lang_var, state="readonly",
                     values=LANG_LABELS, font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)

        # model + temperature rows (gemini / nvidia)
        self.model_row = tk.Frame(form, bg=BG)
        self.model_row.pack(fill="x", pady=1)
        tk.Label(self.model_row, text="Model:", width=14, anchor="w", bg=BG, fg=FG,
                 font=("Segoe UI", 9)).pack(side="left")
        self.model_combo = ttk.Combobox(self.model_row, textvariable=self.model_var,
                                        values=MODEL_OPTIONS["gemini"], font=("Segoe UI", 9))
        self.model_combo.pack(side="left", fill="x", expand=True)

        self.temp_row = tk.Frame(form, bg=BG)
        self.temp_row.pack(fill="x", pady=1)
        tk.Label(self.temp_row, text="Temperature:", width=14, anchor="w", bg=BG, fg=FG,
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Entry(self.temp_row, textvariable=self.temp_var, bg=ENTRY_BG, fg=FG,
                 insertbackground=FG, relief="flat", font=("Segoe UI", 9), width=7).pack(side="left")
        tk.Label(self.temp_row, text="0 = literal · 0.6 = balanced · 1 = creative",
                 font=("Segoe UI", 7), bg=BG, fg=SUBTLE).pack(side="left", padx=(8, 0))

        buttons = tk.Frame(self, bg=BG)
        buttons.pack(fill="x", padx=24, pady=(6, 4))

        self.btn = tk.Button(
            buttons, text="Translate", command=self.start_translation,
            bg=GREEN, fg="#1e1e2e", font=("Segoe UI", 9, "bold"),
            relief="flat", pady=3, cursor="hand2", activebackground="#94e2d5",
        )
        self.btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.stop_btn = tk.Button(
            buttons, text="Stop & Save", command=self.request_stop,
            bg=RED, fg="#1e1e2e", font=("Segoe UI", 9, "bold"),
            relief="flat", pady=3, cursor="hand2", state="disabled",
        )
        self.stop_btn.pack(side="left", padx=(3, 3))

        self.cancel_btn = tk.Button(
            buttons, text="Cancel", command=self.request_cancel,
            bg=ENTRY_BG, fg=FG, font=("Segoe UI", 9, "bold"),
            relief="flat", pady=3, cursor="hand2", state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=(3, 3))

        self.save_btn = tk.Button(
            buttons, text="Save progress\n& PDF", command=self.save_progress_to_pdf,
            bg=ENTRY_BG, fg=FG, font=("Segoe UI", 9),
            relief="flat", pady=4, cursor="hand2",
        )
        self.save_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=24)

        self.status = tk.Label(self, text="Ready", font=("Segoe UI", 8), bg=BG, fg=SUBTLE)
        self.status.pack(pady=(2, 0))

        self.log_text = tk.Text(self, height=10, bg=ENTRY_BG, fg=FG,
                                relief="flat", font=("Consolas", 9), state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=24, pady=(3, 6))

        self._refresh_key_status()

    # ---------- helpers ----------

    def _lang_code(self) -> str:
        label = self.lang_var.get()
        for code, name in LANG_NAMES.items():
            if label.startswith(name):
                return code
        return tb.DEFAULT_LANG

    def _refresh_key_status(self):
        backend = self.backend_var.get()
        GREEN = "#a6e3a1"
        WARN = "#f9e2af"
        if backend == "gemini":
            found = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
            text = "✓ Gemini key found in environment/.env" if found else "⚠ No Gemini key — set GEMINI_API_KEY or add .env"
        elif backend == "azure":
            found = bool(os.environ.get("AZURE_TRANSLATOR_KEY"))
            text = "✓ Azure key found in environment/.env" if found else "⚠ No Azure key — set AZURE_TRANSLATOR_KEY or add .env"
        elif backend == "nvidia":
            found = bool(os.environ.get("NVIDIA_API_KEY"))
            text = "✓ NVIDIA key found in environment/.env" if found else "⚠ No NVIDIA key — set NVIDIA_API_KEY or add .env"
        else:
            found = True
            text = "✓ Google-free needs no key"
        self.key_label.config(text=text, fg=GREEN if found else WARN)

    def browse_file(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.set_pdf(path)

    def on_drop(self, event):
        path = event.data.strip("{}")
        if path.lower().endswith(".pdf"):
            self.set_pdf(path)
        else:
            messagebox.showerror("Error", "Please drop a PDF file.")

    def set_pdf(self, path):
        self.pdf_path.set(path)
        self.output_name.set(Path(path).stem + "_translated")
        self.drop_label.config(text=f"{Path(path).name}  (counting pages...)",
                               fg="#cdd6f4")
        self.page_count = 0
        self.vt_stats = None
        self.vt_label.config(text="VirusTotal: scanning...", fg="#89b4fa")
        threading.Thread(target=self._book_info_worker, args=(path,), daemon=True).start()

    def _book_info_worker(self, path):
        pages = 0
        try:
            pages = tb.count_pages(path)
        except Exception:
            pages = 0

        def upd():
            name = Path(path).name
            if pages:
                self.drop_label.config(text=f"{name}  ({pages} pages)")
            else:
                self.drop_label.config(text=name)
        self.after(0, upd)

        result = tb.vt_scan_file(path)
        stats = result.get("stats")

        def vt_upd():
            if result.get("error") == "no key":
                self.vt_label.config(text="VirusTotal: no key (skipped)", fg="#6c7086")
                self.vt_stats = None
            elif result.get("error"):
                self.vt_label.config(text=f"VirusTotal: error ({result['error'][:40]})", fg="#f9e2af")
                self.vt_stats = None
            else:
                flagged = (stats.get("malicious", 0) or 0) + (stats.get("suspicious", 0) or 0)
                total = sum(stats.values()) if stats else 0
                self.vt_stats = stats
                if flagged:
                    self.vt_label.config(
                        text=f"VirusTotal: ⚠ {flagged} of {total} engines flagged — click to re-scan",
                        fg="#f38ba8")
                else:
                    self.vt_label.config(
                        text=f"VirusTotal: ✓ clean ({total} engines)", fg="#a6e3a1")
        self.after(0, vt_upd)

    def _rescan(self):
        path = self.pdf_path.get()
        if not path or not Path(path).exists():
            return
        self.vt_label.config(text="VirusTotal: re-scanning...", fg="#89b4fa")
        threading.Thread(target=self._book_info_worker, args=(path,), daemon=True).start()

    def output_path_for(self) -> str:
        out_name = self.output_name.get().strip() or "translated"
        if not out_name.endswith(".pdf"):
            out_name += ".pdf"
        out_dir = Path(self.pdf_path.get()).parent
        return str(out_dir / out_name)

    def log(self, text):
        def _update():
            self.log_text.config(state="normal")
            self.log_text.insert("end", text + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.after(0, _update)

    def set_status(self, text):
        self.after(0, lambda: self.status.config(text=text))

    def set_progress(self, current, total):
        def _update():
            pct = (current / total * 100) if total else 0
            self.progress["value"] = pct
        self.after(0, _update)

    def set_running(self, running):
        self.is_running = running
        state = "disabled" if running else "normal"
        self.btn.config(state=state)
        self.save_btn.config(state=state)
        self.stop_btn.config(state="normal" if running else "disabled")
        self.cancel_btn.config(state="normal" if running else "disabled")
        color = "#f38ba8" if running else "#a6e3a1"
        self.btn.config(bg=color)

    def _on_backend_change(self):
        backend = self.backend_var.get()
        if backend in MODEL_OPTIONS:
            self.model_row.pack(fill="x", pady=1)
            self.temp_row.pack(fill="x", pady=1)
            opts = MODEL_OPTIONS[backend]
            self.model_combo.config(values=opts)
            if self.model_var.get() not in opts:
                self.model_var.set(opts[0])
        else:
            self.model_row.pack_forget()
            self.temp_row.pack_forget()
        self._refresh_key_status()

    def _validate(self) -> bool:
        input_path = self.pdf_path.get()
        if not input_path or not Path(input_path).exists():
            messagebox.showwarning("Warning", "Please select a valid PDF file.")
            return False
        return True

    def _model_and_temp(self):
        try:
            temp = float(self.temp_var.get())
        except ValueError:
            messagebox.showerror("Error", "Temperature must be a number (e.g. 0.6)")
            return None, None
        return self.model_var.get().strip() or tb.DEFAULT_MODEL, temp

    # ---------- actions ----------

    def request_stop(self):
        if not self.is_running:
            return
        self.stop_event.set()
        self.set_status("Stopping after this page...")
        self.log("Stop requested — finishing current page, then saving.")

    def request_cancel(self):
        if not self.is_running:
            return
        self.cancel_event.set()
        self.set_status("Cancelling...")
        self.log("Cancel requested — nothing from this run will be saved.")

    def save_progress_to_pdf(self):
        if self.is_running:
            return
        if not self._validate():
            return
        path = self.pdf_path.get()
        out = self.output_path_for()
        try:
            pages, images, actual = tb.merge_progress_to_pdf(
                path, out, title=self.title_str.get().strip(), lang=self._lang_code())
        except Exception as e:
            messagebox.showerror("Cannot merge", str(e))
            return
        self.log(f"Merged progress into {actual} ({pages} pages, {images} images)")
        messagebox.showinfo(
            "Saved",
            f"Progress merged into the PDF:\n\n{actual}\n\n{pages} pages · {images} images")

    def start_translation(self):
        if self.is_running or not self._validate():
            return
        model, temp = self._model_and_temp()
        if not model or temp is None:
            return

        if self.vt_stats:
            flagged = self.vt_stats.get("malicious", 0) + self.vt_stats.get("suspicious", 0)
            if flagged > 0:
                go = messagebox.askyesno(
                    "VirusTotal warning",
                    f"{flagged} security engines flagged this file.\n\nTranslate it anyway?")
                if not go:
                    return

        input_path = self.pdf_path.get()
        output_path = self.output_path_for()
        pages = self.pages_str.get().strip()
        title = self.title_str.get().strip()

        resume = True
        prog = tb.progress_path_for(output_path)
        if prog.exists():
            done = len(tb.load_progress(output_path, input_path))
            if done > 0:
                resume = messagebox.askyesno(
                    "Previous progress found",
                    f"{done} pages were already translated for this book.\n\n"
                    "Yes = skip translated pages and extend this PDF\n"
                    "No = start over from page 1")

        self.stop_event.clear()
        self.cancel_event.clear()
        self.set_running(True)
        self.set_status("Starting...")
        self.progress["value"] = 0
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        thread = threading.Thread(
            target=self._run_worker,
            args=(input_path, output_path, model, temp, pages, title, resume,
                  self.force_var.get()),
            daemon=True,
        )
        thread.start()

    def _run_worker(self, input_path, output_path, model, temp, pages, title, resume, force):
        try:
            summary = tb.run_translation(
                input_path=input_path,
                output_path=output_path,
                backend=self.backend_var.get(),
                model=model,
                temperature=temp,
                lang=self._lang_code(),
                pages=pages,
                title=title,
                resume=resume,
                force=force,
                should_stop=self.stop_event.is_set,
                should_cancel=self.cancel_event.is_set,
                progress_callback=self.set_progress,
                status_callback=self.set_status,
                log_callback=self.log,
            )
            if summary.get("cancelled"):
                self.after(0, lambda: messagebox.showinfo(
                    "Cancelled",
                    "Cancelled — nothing was saved.\n\n"
                    "The PDF and saved progress are exactly as they were\n"
                    "before this run."))
            elif summary.get("stopped"):
                self.after(0, lambda: messagebox.showinfo(
                    "Stopped & saved",
                    f"Stopped. {summary.get('pages_in_output', 0)} pages are already in:\n{output_path}\n\n"
                    "Re-run with the same settings to continue."))
            else:
                self.after(0, lambda: messagebox.showinfo(
                    "Done",
                    f"Translation complete!\n\n{summary.get('pages_in_output', 0)} pages · "
                    f"{summary.get('images', 0)} images\nSaved to:\n{output_path}"))
        except tb.QuotaExhausted:
            self.after(0, lambda: messagebox.showwarning(
                "Daily quota reached — partial PDF saved",
                "Gemini free-tier quota is exhausted.\n\n"
                "Everything translated so far has been merged into the PDF already.\n"
                "Re-run tomorrow after midnight (Pacific) to continue —\n"
                "translated pages are skipped automatically."))
        except tb.TransientFailure:
            self.after(0, lambda: messagebox.showwarning(
                "Model overloaded — partial PDF saved",
                "The model is under heavy load and stayed unavailable after retries.\n\n"
                "Everything translated so far has been merged into the PDF already.\n"
                "Wait a few minutes and re-run to continue —\n"
                "translated pages are skipped automatically.\n\n"
                "Tip: switching the Model dropdown to another model can help,\n"
                "since overloads often affect one model at a time."))
        except Exception as e:
            self.log(traceback.format_exc())
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.set_running(False)
            self.set_status("Ready")


if __name__ == "__main__":
    app = App()
    app.mainloop()
