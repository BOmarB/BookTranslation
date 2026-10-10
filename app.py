#!/usr/bin/env python3
"""
Book Translator GUI - Gemini edition
Drag & drop a PDF -> full-page translation into Arabic -> RTL PDF
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


MODEL_OPTIONS = [
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-3.8-flash",
    "gemini-2.5-flash",
]


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Book Translator - Gemini")
        self.geometry("720x660")
        self.minsize(640, 600)
        self.resizable(True, True)
        self.configure(bg="#1e1e2e")

        self.pdf_path = tk.StringVar()
        self.output_name = tk.StringVar(value="")
        self.pages_str = tk.StringVar()
        self.title_str = tk.StringVar()
        self.model_var = tk.StringVar(value=tb.DEFAULT_MODEL)
        self.temp_var = tk.StringVar(value=str(tb.DEFAULT_TEMPERATURE))
        self.backend_var = tk.StringVar(value="gemini")

        self.is_running = False
        self._build_ui()

    def _build_ui(self):
        BG = "#1e1e2e"
        FG = "#cdd6f4"
        ACCENT = "#89b4fa"
        GREEN = "#a6e3a1"
        ENTRY_BG = "#313244"
        SUBTLE = "#6c7086"

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor=ENTRY_BG, background=ACCENT, borderwidth=0)

        tk.Label(
            self, text="Book Translator", font=("Segoe UI", 18, "bold"),
            bg=BG, fg=FG,
        ).pack(pady=(16, 2))
        tk.Label(
            self, text="PDF  →  Arabic  ·  full-page translation with Gemini",
            font=("Segoe UI", 9), bg=BG, fg=SUBTLE,
        ).pack()

        # API key status
        key_found = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        key_text = "✓ Gemini API key found in environment" if key_found else "⚠ No API key — set GEMINI_API_KEY (aistudio.google.com/apikey)"
        key_color = GREEN if key_found else "#f9e2af"
        tk.Label(self, text=key_text, font=("Segoe UI", 9), bg=BG, fg=key_color).pack(pady=(6, 0))

        drop = tk.Frame(self, bg=ENTRY_BG, highlightbackground=ACCENT, highlightthickness=1, height=72)
        drop.pack(fill="x", padx=30, pady=(10, 4))
        drop.pack_propagate(False)
        drop.drop_target_register(DND_FILES)
        drop.dnd_bind("<<Drop>>", self.on_drop)

        self.drop_label = tk.Label(
            drop, text="Drop PDF here or click Browse",
            font=("Segoe UI", 11), bg=ENTRY_BG, fg=SUBTLE, cursor="hand2",
        )
        self.drop_label.pack(expand=True)
        self.drop_label.bind("<Button-1>", lambda e: self.browse_file())

        tk.Button(
            self, text="Browse...", command=self.browse_file,
            bg=ACCENT, fg=BG, font=("Segoe UI", 9, "bold"),
            relief="flat", padx=16, pady=3, cursor="hand2",
        ).pack(pady=(4, 8))

        form = tk.Frame(self, bg=BG)
        form.pack(fill="x", padx=30)

        rows = [
            ("Output name:", self.output_name),
            ("Pages:", self.pages_str),
            ("Book title:", self.title_str),
        ]
        for label_text, var in rows:
            row = tk.Frame(form, bg=BG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label_text, width=16, anchor="w", bg=BG, fg=FG,
                     font=("Segoe UI", 10)).pack(side="left")
            tk.Entry(row, textvariable=var, bg=ENTRY_BG, fg=FG,
                     insertbackground=FG, relief="flat", font=("Segoe UI", 10)).pack(
                side="left", fill="x", expand=True, ipady=3)

        tk.Label(
            form, text="leave empty = whole book   ·   40 = one page   ·   1-40 or 60-80 = range   ·   40,60-62 = mix",
            font=("Segoe UI", 8), bg=BG, fg=SUBTLE, anchor="w",
        ).pack(fill="x", pady=(0, 4))

        row = tk.Frame(form, bg=BG)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Backend:", width=16, anchor="w", bg=BG, fg=FG,
                 font=("Segoe UI", 10)).pack(side="left")
        backend_menu = ttk.Combobox(
            row, textvariable=self.backend_var, state="readonly",
            values=["gemini", "azure"], font=("Segoe UI", 10))
        backend_menu.pack(side="left", fill="x", expand=True)
        backend_menu.bind("<<ComboboxSelected>>", lambda e: self._on_backend_change())

        self.model_row = tk.Frame(form, bg=BG)
        self.model_row.pack(fill="x", pady=3)
        tk.Label(self.model_row, text="Model:", width=16, anchor="w", bg=BG, fg=FG,
                 font=("Segoe UI", 10)).pack(side="left")
        model_menu = ttk.Combobox(self.model_row, textvariable=self.model_var, values=MODEL_OPTIONS,
                                  font=("Segoe UI", 10))
        model_menu.pack(side="left", fill="x", expand=True)

        self.temp_row = tk.Frame(form, bg=BG)
        self.temp_row.pack(fill="x", pady=3)
        tk.Label(self.temp_row, text="Temperature:", width=16, anchor="w", bg=BG, fg=FG,
                 font=("Segoe UI", 10)).pack(side="left")
        tk.Entry(self.temp_row, textvariable=self.temp_var, bg=ENTRY_BG, fg=FG,
                 insertbackground=FG, relief="flat", font=("Segoe UI", 10), width=8).pack(side="left")

        buttons = tk.Frame(self, bg=BG)
        buttons.pack(fill="x", padx=30, pady=(12, 6))

        self.btn = tk.Button(
            buttons, text="Translate", command=self.start_translation,
            bg=GREEN, fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
            relief="flat", pady=6, cursor="hand2", activebackground="#94e2d5",
        )
        self.btn.pack(fill="x")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=30)

        self.status = tk.Label(self, text="Ready", font=("Segoe UI", 9), bg=BG, fg=SUBTLE)
        self.status.pack(pady=(4, 0))

        self.log_text = tk.Text(self, height=7, bg=ENTRY_BG, fg=FG,
                                relief="flat", font=("Consolas", 8), state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=30, pady=(6, 12))

    # ---------- helpers ----------

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
        self.drop_label.config(text=Path(path).name, fg="#cdd6f4")

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
        color = "#f38ba8" if running else "#a6e3a1"
        self.btn.config(bg=color)

    def _on_backend_change(self):
        if self.backend_var.get() == "azure":
            self.model_row.pack_forget()
            self.temp_row.pack_forget()
        else:
            self._show_gemini_rows()

    def _show_gemini_rows(self):
        self.model_row.pack(fill="x", pady=3)
        self.temp_row.pack(fill="x", pady=3)

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

    def start_translation(self):
        if self.is_running or not self._validate():
            return
        model, temp = self._model_and_temp()
        if not model:
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

        self.set_running(True)
        self.set_status("Starting...")
        self.progress["value"] = 0
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        thread = threading.Thread(
            target=self._run_worker,
            args=(input_path, output_path, model, temp, pages, title, resume),
            daemon=True,
        )
        thread.start()

    def _run_worker(self, input_path, output_path, model, temp, pages, title, resume):
        try:
            tb.run_translation(
                input_path=input_path,
                output_path=output_path,
                backend=self.backend_var.get(),
                model=model,
                temperature=temp,
                pages=pages,
                title=title,
                resume=resume,
                progress_callback=self.set_progress,
                status_callback=self.set_status,
                log_callback=self.log,
            )
            self.after(0, lambda: messagebox.showinfo(
                "Done", f"Translation complete!\n\nSaved to:\n{output_path}"))
        except tb.QuotaExhausted:
            self.after(0, lambda: messagebox.showwarning(
                "Daily quota reached",
                "Gemini free-tier quota is exhausted.\n\n"
                "All pages translated so far are saved.\n"
                "Re-run tomorrow after midnight (Pacific time) to continue —\n"
                "the app will resume automatically."))
        except Exception as e:
            self.log(traceback.format_exc())
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.set_running(False)
            self.set_status("Ready")


if __name__ == "__main__":
    app = App()
    app.mainloop()
