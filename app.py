#!/usr/bin/env python3
"""
Book Translator GUI
Drag & drop a PDF -> whole-page translation (Gemini / NVIDIA / custom API)
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
    "custom": [],
}
BACKENDS = ["gemini", "nvidia", "custom"]
LANG_NAMES = {"ar": "Arabic", "fr": "French", "en": "English"}
LANG_LABELS = [f"{name} ({code})" for code, name in LANG_NAMES.items()]

# UI palette (module level so dialogs created outside _build_ui can use it).
BG = "#1e1e2e"
FG = "#cdd6f4"
ACCENT = "#89b4fa"
GREEN = "#a6e3a1"
RED = "#f38ba8"
ENTRY_BG = "#313244"
SUBTLE = "#6c7086"


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
        self.extra_context_var = tk.BooleanVar(value=False)
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

        tk.Checkbutton(
            form, text="Extra context: continuity note of earlier pages (1 request)",
            variable=self.extra_context_var, bg=BG, fg=SUBTLE, selectcolor=ENTRY_BG,
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
        tk.Button(row, text="Connect…", command=self._open_connect,
                  bg=ENTRY_BG, fg=FG, font=("Segoe UI", 8), relief="flat",
                  padx=6, pady=1, cursor="hand2").pack(side="left", padx=(6, 0))

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
            text = "✓ Gemini key found — click Connect… to change it" if found else "⚠ No Gemini key — click Connect… to add one"
        elif backend == "nvidia":
            found = bool(os.environ.get("NVIDIA_API_KEY"))
            text = "✓ NVIDIA key found — click Connect… to change it" if found else "⚠ No NVIDIA key — click Connect… to add one"
        else:  # custom
            base = os.environ.get("CUSTOM_BASE_URL")
            key = os.environ.get("CUSTOM_API_KEY")
            found = bool(base)
            if base and key:
                text = f"✓ Custom endpoint: {base}"
            elif base:
                text = f"✓ Custom endpoint: {base} (no key — fine for local servers)"
            else:
                text = "⚠ No custom endpoint — click Connect… to set the base URL + key"
        self.key_label.config(text=text, fg=GREEN if found else WARN)

    def _open_connect(self):
        backend = self.backend_var.get()
        win = tk.Toplevel(self)
        win.title("Connect — " + {"gemini": "Gemini", "nvidia": "NVIDIA"}.get(backend, "Custom API"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        body = tk.Frame(win, bg=BG)
        body.pack(padx=16, pady=14, fill="x")
        entries: dict[str, tk.Entry] = {}

        def add_field(key: str, label: str, hint: str = ""):
            tk.Label(body, text=label, anchor="w", bg=BG, fg=FG,
                     font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(6, 1))
            e = tk.Entry(body, bg=ENTRY_BG, fg=FG, insertbackground=FG,
                         relief="flat", font=("Segoe UI", 9), width=52)
            e.insert(0, os.environ.get(key, ""))
            e.pack(fill="x", ipady=3)
            if hint:
                tk.Label(body, text=hint, anchor="w", bg=BG, fg=SUBTLE,
                         font=("Segoe UI", 7)).pack(fill="x")
            entries[key] = e

        if backend == "gemini":
            add_field("GEMINI_API_KEY", "Gemini API key",
                      "Free key: aistudio.google.com → Get API key")
        elif backend == "nvidia":
            add_field("NVIDIA_API_KEY", "NVIDIA API key",
                      "Free key: build.nvidia.com (model meta/muse-glimmer-30b)")
        else:
            add_field("CUSTOM_BASE_URL", "API base URL",
                      "e.g. https://api.openai.com/v1 · https://openrouter.ai/api/v1 · "
                      "http://localhost:11434/v1 (Ollama)")
            add_field("CUSTOM_API_KEY", "API key",
                      "Leave empty for local servers that need no key")

        tk.Label(body, text=f"Saved to: {self._env_path()}", anchor="w", bg=BG,
                 fg=SUBTLE, font=("Segoe UI", 7)).pack(fill="x", pady=(10, 0))

        def save():
            pairs = {k: e.get().strip() for k, e in entries.items() if e.get().strip()}
            if backend == "custom" and not pairs.get("CUSTOM_BASE_URL"):
                messagebox.showerror("Missing base URL",
                                     "Enter your API base URL first.", parent=win)
                return
            if backend != "custom" and not pairs:
                messagebox.showerror("Missing key", "Enter the API key.", parent=win)
                return
            p = self._save_env(pairs)
            self._refresh_key_status()
            messagebox.showinfo("Connected", f"Saved to:\n{p}", parent=win)
            win.destroy()

        btns = tk.Frame(body, bg=BG)
        btns.pack(fill="x", pady=(12, 0))
        tk.Button(btns, text="Save", command=save, bg=GREEN, fg="#1e1e2e",
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=14, pady=3,
                  cursor="hand2").pack(side="right")
        tk.Button(btns, text="Cancel", command=win.destroy, bg=ENTRY_BG, fg=FG,
                  font=("Segoe UI", 9), relief="flat", padx=10, pady=3,
                  cursor="hand2").pack(side="right", padx=(0, 6))
        win.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - win.winfo_width()) // 2)
        y = self.winfo_rooty() + 120
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        next(iter(entries.values())).focus_set()
        win.grab_set()

    def _env_path(self) -> Path:
        """The .env the app reads: next to the EXE when frozen, else the project dir."""
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent / ".env"
        return Path(__file__).resolve().parent / ".env"

    def _save_env(self, pairs: dict[str, str]) -> Path:
        """Write/refresh KEY=value lines in the .env and apply them right away."""
        p = self._env_path()
        lines: list[str] = []
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
        keys = set(pairs)
        kept = [ln for ln in lines
                if not ("=" in ln and ln.strip().split("=", 1)[0].strip() in keys)]
        for k, v in pairs.items():
            kept.append(f"{k}={v}")
        p.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
        for k, v in pairs.items():
            os.environ[k] = v
        return p

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
        self.model_row.pack(fill="x", pady=1)
        self.temp_row.pack(fill="x", pady=1)
        opts = MODEL_OPTIONS.get(backend, [])
        self.model_combo.config(values=opts)
        current = self.model_var.get()
        if backend == "custom":
            # the model id belongs to the user's provider — clear other backends' ids
            if any(current in v for v in MODEL_OPTIONS.values()):
                self.model_var.set("")
        elif opts and current not in opts:
            self.model_var.set(opts[0])
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
        model = self.model_var.get().strip()
        if self.backend_var.get() == "custom" and not model:
            messagebox.showerror(
                "Error",
                "Enter your provider's model id (e.g. gpt-4o-mini,\n"
                "or meta/muse-glimmer-30b for NVIDIA endpoints).")
            return None, None
        return model or tb.DEFAULT_MODEL, temp

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

    def _ask_locked_pdf(self, path: str) -> str:
        """Ask before saving when the output PDF is open in another program.

        Blocks until the user clicks OK. Returns "retry": the save then tries
        the same name once more — if the viewer was closed it saves normally,
        if it is still open a _2 copy is written. Safe to call from the worker
        thread: the dialog itself runs on the Tk thread.
        """
        def ask():
            messagebox.showwarning(
                "PDF is open — close it to save normally",
                "The output PDF is open in another program:\n\n"
                f"{path}\n\n"
                "• Close that file now, then click OK — the PDF will be "
                "saved to the same file.\n"
                "• Or click OK without closing it — the PDF will be saved "
                "as a new copy instead:\n"
                f"  {tb._increment_path(path)}")

        if threading.current_thread() is threading.main_thread():
            ask()
            return "retry"

        result = {"action": "copy"}
        done = threading.Event()

        def ask_and_set():
            try:
                ask()
                result["action"] = "retry"
            finally:
                done.set()

        self.after(0, ask_and_set)
        done.wait()
        return result["action"]

    def save_progress_to_pdf(self):
        if self.is_running:
            return
        if not self._validate():
            return
        path = self.pdf_path.get()
        out = self.output_path_for()
        try:
            pages, images, actual = tb.merge_progress_to_pdf(
                path, out, title=self.title_str.get().strip(), lang=self._lang_code(),
                locked_callback=self._ask_locked_pdf)
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

        if self.backend_var.get() == "custom" and not os.environ.get("CUSTOM_BASE_URL"):
            messagebox.showerror(
                "Custom endpoint not set",
                "Click the Connect… button next to Backend and enter your\n"
                "API base URL and key first.")
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
                extra_context=self.extra_context_var.get(),
                should_stop=self.stop_event.is_set,
                should_cancel=self.cancel_event.is_set,
                progress_callback=self.set_progress,
                status_callback=self.set_status,
                log_callback=self.log,
                locked_callback=self._ask_locked_pdf,
            )
            actual_path = summary.get("output") or output_path
            relocated_note = ""
            try:
                if (os.path.normcase(os.path.abspath(actual_path))
                        != os.path.normcase(os.path.abspath(output_path))):
                    relocated_note = (
                        "\n\n⚠ Saved under a different name — the original file is\n"
                        "open in another program. Close it and re-run to update\n"
                        "the original (progress is kept), or rename this file.")
            except OSError:
                pass
            if summary.get("cancelled"):
                self.after(0, lambda: messagebox.showinfo(
                    "Cancelled",
                    "Cancelled — nothing was saved.\n\n"
                    "The PDF and saved progress are exactly as they were\n"
                    "before this run."))
            elif summary.get("stopped"):
                self.after(0, lambda: messagebox.showinfo(
                    "Stopped & saved",
                    f"Stopped. {summary.get('pages_in_output', 0)} pages are already in:\n{actual_path}{relocated_note}\n\n"
                    "Re-run with the same settings to continue."))
            else:
                self.after(0, lambda: messagebox.showinfo(
                    "Done",
                    f"Translation complete!\n\n{summary.get('pages_in_output', 0)} pages · "
                    f"{summary.get('images', 0)} images\nSaved to:\n{actual_path}{relocated_note}"))
        except tb.QuotaExhausted:
            self.after(0, lambda: messagebox.showwarning(
                "Daily quota reached — partial PDF saved",
                "The model's free-tier quota is exhausted.\n\n"
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
