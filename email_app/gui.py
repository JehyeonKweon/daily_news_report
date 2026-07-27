"""GUI for the daily news report. Run: python gui.py  or  python -m email_app.gui"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running this file directly (IDE "Run") — project root must be on sys.path.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from core.config import default_email_recipients, list_categories
from core.models import RunOptions
from email_app.pipeline import run_report


class NewsReportApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("일일 뉴스 리포트")
        self.root.geometry("560x560")
        self.root.minsize(480, 400)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False
        self.cancel_event = threading.Event()

        categories = list_categories()
        if not categories:
            messagebox.showerror(
                "Config error",
                "No categories found.\nAdd a folder under config/ (e.g. config/보안/).",
            )

        frame = ttk.Frame(root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Category").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.category_var = tk.StringVar(value=categories[0] if categories else "")
        self.category_combo = ttk.Combobox(
            frame,
            textvariable=self.category_var,
            values=categories,
            state="readonly" if categories else "disabled",
            width=30,
        )
        self.category_combo.grid(row=0, column=1, sticky=tk.EW, pady=4)

        ttk.Label(frame, text="Articles per feed").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.count_var = tk.StringVar(value="10")
        ttk.Spinbox(
            frame,
            from_=1,
            to=50,
            textvariable=self.count_var,
            width=10,
        ).grid(row=1, column=1, sticky=tk.W, pady=4)

        ttk.Label(frame, text="Last N days").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.days_var = tk.StringVar(value="1")
        ttk.Spinbox(
            frame,
            from_=1,
            to=30,
            textvariable=self.days_var,
            width=10,
        ).grid(row=2, column=1, sticky=tk.W, pady=4)

        self.intl_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="International search",
            variable=self.intl_var,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=2)

        self.kr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="Korean search",
            variable=self.kr_var,
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=2)

        ttk.Label(frame, text="Send to (comma-separated)").grid(
            row=5, column=0, sticky=tk.W, pady=4
        )
        self.email_var = tk.StringVar(value=default_email_recipients())
        ttk.Entry(frame, textvariable=self.email_var, width=40).grid(
            row=5, column=1, sticky=tk.EW, pady=4
        )

        self.start_btn = ttk.Button(frame, text="Start", command=self.on_start)
        self.start_btn.grid(row=6, column=0, columnspan=2, pady=12)

        self.cancel_btn = ttk.Button(
            frame, text="Cancel", command=self.on_cancel, state=tk.DISABLED
        )
        self.cancel_btn.grid(row=6, column=1, sticky=tk.E, pady=12)

        ttk.Label(frame, text="Log").grid(row=7, column=0, sticky=tk.W)
        self.log_text = scrolledtext.ScrolledText(frame, height=14, state=tk.DISABLED)
        self.log_text.grid(row=8, column=0, columnspan=2, sticky=tk.NSEW, pady=4)

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(8, weight=1)

        self.root.after(100, self.poll_log)

    def append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def poll_log(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.append_log(message)
        self.root.after(100, self.poll_log)

    def log(self, message: str) -> None:
        self.log_queue.put(message)

    def on_start(self) -> None:
        if self.running:
            return

        category = self.category_var.get().strip()
        if not category:
            messagebox.showwarning("Input", "Select a category.")
            return

        try:
            article_count = int(self.count_var.get())
        except ValueError:
            messagebox.showwarning("Input", "Article count must be a number.")
            return

        try:
            days_back = int(self.days_var.get())
        except ValueError:
            messagebox.showwarning("Input", "Last N days must be a number.")
            return

        if days_back < 1:
            messagebox.showwarning("Input", "Last N days must be at least 1.")
            return

        if not self.intl_var.get() and not self.kr_var.get():
            messagebox.showwarning("Input", "Select at least one search option.")
            return

        email_to = self.email_var.get().strip()
        if not email_to:
            messagebox.showwarning("Input", "Enter at least one email address.")
            return

        options = RunOptions(
            category=category,
            article_count=article_count,
            international=self.intl_var.get(),
            korean=self.kr_var.get(),
            email_to=email_to,
            days_back=days_back,
        )

        self.running = True
        self.cancel_event.clear()
        self.start_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)
        self.append_log("--- Starting ---")

        def worker() -> None:
            try:
                run_report(options, log=self.log, cancel_event=self.cancel_event)
            except Exception as exc:  # noqa: BLE001
                self.log(f"Error: {exc}")
                self.root.after(0, lambda: messagebox.showerror("Error", str(exc)))
            finally:
                self.root.after(0, self.on_done)

        threading.Thread(target=worker, daemon=True).start()

    def on_done(self) -> None:
        self.running = False
        self.start_btn.configure(state=tk.NORMAL)
        self.cancel_btn.configure(state=tk.DISABLED)

    def on_cancel(self) -> None:
        if not self.running:
            return
        self.append_log("--- Cancelling ---")
        self.cancel_event.set()


def main() -> None:
    root = tk.Tk()
    NewsReportApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
