"""
ui.py
-----
The Tkinter desktop interface. Kept in one file for simplicity, but
organized into clear sections: theme, build_*, on_*, refresh_*.

The UI never touches the filesystem or the database directly -- it only
calls into the `Controller` (see main.py) which owns scanning, analysis
and deletion. This keeps the UI a thin, replaceable layer.

Theme changes rebuild the whole widget tree (see rebuild_ui) rather than
trying to live-recolor dozens of individual widgets -- simpler and far
less error-prone than tracking every widget's color role by hand.
"""

import datetime as dt
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from scanner import human_size
from settings import load_settings, save_settings

APP_DIR = os.path.dirname(os.path.abspath(__file__))

CATEGORY_ICON = {
    "Game": "\U0001F3AE",
    "Application": "\U0001F4BB",
    "Installer": "\U0001F4E6",
    "Collection of files": "\U0001F4C1",
    "Documents": "\U0001F4C4",
    "Media": "\U0001F5BC",
    "Archive": "\U0001F5DC",
    "Development project": "\U0001F4BE",
    "Configuration": "\u2699",
    "Cache / temporary data": "\U0001F9F9",
    "Unknown": "\u2753",
}

STATUS_ICON = {
    "Keep": "\U0001F7E2",
    "Review": "\U0001F7E1",
    "Probably unnecessary": "\U0001F7E0",
    "Likely junk": "\U0001F534",
}

STATUS_TAG = {
    "Keep": "status_keep",
    "Review": "status_review",
    "Probably unnecessary": "status_probably",
    "Likely junk": "status_junk",
}

FILTER_OPTIONS = [
    "All", "Likely Junk", "Probably Unnecessary", "Review", "Keep",
    "Games", "Applications", "Installers", "Documents", "Archives", "Duplicates",
]

SORT_OPTIONS = [
    "Size", "Importance", "Junk probability", "Last accessed",
    "Last modified", "Creation date", "Category",
]

THEME_DISPLAY_TO_PREF = {"Auto (System)": "auto", "Light": "light", "Dark": "dark"}
THEME_PREF_TO_DISPLAY = {v: k for k, v in THEME_DISPLAY_TO_PREF.items()}

CHECK_EMPTY = "\u2610"
CHECK_FILLED = "\u2611"


# ----------------------------------------------------------------------
# Theming
# ----------------------------------------------------------------------

LIGHT = {
    "bg": "#f4f5f8", "panel_bg": "#ffffff", "header_bg": "#2d3142", "header_fg": "#ffffff",
    "header_accent": "#b9c6ff", "fg": "#1c1e26", "muted_fg": "#6b7280", "border": "#d7dae1",
    "entry_bg": "#ffffff", "tree_bg": "#ffffff", "tree_fg": "#1c1e26", "tree_alt_bg": "#f7f8fb",
    "select_bg": "#dce6ff", "select_fg": "#1c1e26", "accent": "#4b6ef5", "accent_fg": "#ffffff",
    "accent_active": "#3a5bdb", "danger": "#d64545", "danger_fg": "#ffffff", "danger_active": "#b93636",
    "btn_bg": "#eef0f5", "btn_active": "#e2e6f0",
    "keep": "#e7f6ec", "keep_fg": "#1c7a3d",
    "review": "#fff6dd", "review_fg": "#93720a",
    "probably": "#ffefdd", "probably_fg": "#a05a00",
    "junk": "#fde8e8", "junk_fg": "#c0392b",
    "log_bg": "#1b1f27", "log_fg": "#d7dae0",
    "log_success": "#7fd99a", "log_error": "#f28b82", "log_info": "#8fb4ff",
}

DARK = {
    "bg": "#1a1c22", "panel_bg": "#22252d", "header_bg": "#11131a", "header_fg": "#f4f5f8",
    "header_accent": "#8ca3ff", "fg": "#e7e9ee", "muted_fg": "#9aa0ac", "border": "#3a3f4b",
    "entry_bg": "#2a2e38", "tree_bg": "#20232b", "tree_fg": "#e7e9ee", "tree_alt_bg": "#262a34",
    "select_bg": "#33415c", "select_fg": "#ffffff", "accent": "#6c8cff", "accent_fg": "#0d0e12",
    "accent_active": "#8ca3ff", "danger": "#e05656", "danger_fg": "#ffffff", "danger_active": "#ef7676",
    "btn_bg": "#2a2e38", "btn_active": "#333844",
    "keep": "#1f3b2c", "keep_fg": "#7fd99a",
    "review": "#3a3320", "review_fg": "#e8c96a",
    "probably": "#3a2a1a", "probably_fg": "#f0a860",
    "junk": "#3a1f1f", "junk_fg": "#f28b82",
    "log_bg": "#0f1117", "log_fg": "#d7dae0",
    "log_success": "#7fd99a", "log_error": "#f28b82", "log_info": "#8fb4ff",
}


def detect_system_theme():
    """Return 'dark' or 'light' based on the OS setting. Defaults to
    'light' if it can't be determined (non-Windows, or the registry key
    is missing)."""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value else "dark"
        except OSError:
            return "light"
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2,
            )
            return "dark" if "dark" in result.stdout.lower() else "light"
        except Exception:
            return "light"
    return "light"


class App(tk.Tk):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.title("Dorian - Storage Analyzer")
        self.geometry("1200x820")
        self.minsize(950, 640)

        settings = load_settings()
        self.theme_pref = settings.get("theme", "auto")  # "auto" | "light" | "dark"
        self.theme_name = detect_system_theme() if self.theme_pref == "auto" else self.theme_pref
        self.colors = DARK if self.theme_name == "dark" else LIGHT

        self.selected_folder = None
        self.last_browse_dir = self._default_browse_dir()
        self.tree_data = []          # list of top-level nodes
        self.checked_paths = set()
        self.node_by_path = {}
        self.sort_desc = True
        self.log_visible = False
        self.log_entries = []        # [(line, level), ...] replayed across theme rebuilds
        self.last_summary = None
        self.deep_scan_stop_event = None
        self.scan_stop_event = None

        self._build_all()
        self._log(f"Ready. Theme: {THEME_PREF_TO_DISPLAY[self.theme_pref]} ({self.theme_name}).", "info")

    def _build_all(self):
        self._apply_style()
        self.configure(bg=self.colors["bg"])
        self._build_header()
        self._build_folder_bar()
        self._build_log_panel()
        self._build_progress_bar()
        self._build_summary_bar()
        self._build_filter_bar()
        self._build_results_tree()
        self._build_bottom_bar()

    # ------------------------------------------------------------------
    # Theming / style
    # ------------------------------------------------------------------
    def _apply_style(self):
        c = self.colors
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=c["bg"])
        style.configure("Panel.TFrame", background=c["panel_bg"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=c["bg"], foreground=c["muted_fg"], font=("Segoe UI", 9))

        style.configure(
            "TButton", font=("Segoe UI", 9), padding=6, background=c["btn_bg"],
            foreground=c["fg"], borderwidth=1, relief="flat", bordercolor=c["border"],
            focusthickness=0, focuscolor=c["btn_bg"],
        )
        style.map(
            "TButton",
            background=[("disabled", c["panel_bg"]), ("pressed", c["btn_active"]), ("active", c["btn_active"])],
            foreground=[("disabled", c["muted_fg"])],
        )

        style.configure(
            "Accent.TButton", font=("Segoe UI", 10, "bold"), padding=7,
            background=c["accent"], foreground=c["accent_fg"], borderwidth=0, focuscolor=c["accent"],
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", c["border"]), ("pressed", c["accent_active"]), ("active", c["accent_active"])],
            foreground=[("disabled", c["muted_fg"])],
        )

        style.configure(
            "Danger.TButton", font=("Segoe UI", 9, "bold"), padding=6,
            background=c["danger"], foreground=c["danger_fg"], borderwidth=0, focuscolor=c["danger"],
        )
        style.map(
            "Danger.TButton",
            background=[("disabled", c["border"]), ("pressed", c["danger_active"]), ("active", c["danger_active"])],
            foreground=[("disabled", c["muted_fg"])],
        )

        style.configure(
            "TCombobox", fieldbackground=c["entry_bg"], background=c["entry_bg"],
            foreground=c["fg"], arrowcolor=c["fg"], bordercolor=c["border"],
            lightcolor=c["entry_bg"], darkcolor=c["entry_bg"], padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["entry_bg"]), ("disabled", c["panel_bg"])],
            foreground=[("readonly", c["fg"]), ("disabled", c["muted_fg"])],
            background=[("readonly", c["entry_bg"])],
            arrowcolor=[("disabled", c["muted_fg"])],
        )
        # The Combobox's popup listbox is a plain Tk widget, not styled by
        # ttk -- has to be themed via the option database instead, or it
        # stays white-on-black (or vice versa) regardless of the rest of
        # the app's theme.
        self.option_add("*TCombobox*Listbox.background", c["entry_bg"])
        self.option_add("*TCombobox*Listbox.foreground", c["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", c["select_bg"])
        self.option_add("*TCombobox*Listbox.selectForeground", c["select_fg"])
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 9))

        style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"])
        style.map("TCheckbutton", background=[("active", c["bg"])])

        style.configure("TProgressbar", background=c["accent"], troughcolor=c["panel_bg"],
                         bordercolor=c["panel_bg"], lightcolor=c["accent"], darkcolor=c["accent"])

        style.configure(
            "Treeview", background=c["tree_bg"], fieldbackground=c["tree_bg"],
            foreground=c["tree_fg"], rowheight=26, borderwidth=0, font=("Segoe UI", 9),
        )
        style.configure("Treeview.Heading", background=c["panel_bg"], foreground=c["fg"],
                         font=("Segoe UI", 9, "bold"), padding=6, relief="flat")
        style.map("Treeview.Heading", background=[("active", c["btn_active"])])
        style.map("Treeview", background=[("selected", c["select_bg"])],
                  foreground=[("selected", c["select_fg"])])

        style.configure("Vertical.TScrollbar", background=c["btn_bg"], troughcolor=c["bg"],
                         bordercolor=c["bg"], arrowcolor=c["fg"])

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_header(self):
        c = self.colors
        frame = tk.Frame(self, bg=c["header_bg"])
        frame.pack(fill="x")
        tk.Label(
            frame, text="\u2728 DORIAN", bg=c["header_bg"], fg=c["header_fg"],
            font=("Segoe UI", 18, "bold"), pady=16, padx=4,
        ).pack(side="left", padx=16)
        tk.Label(
            frame, text="Your AI storage analyst \u2014 understands your storage instead of just deleting old things",
            bg=c["header_bg"], fg=c["header_accent"], font=("Segoe UI", 9, "italic"),
        ).pack(side="left", padx=(0, 16))

    def _build_folder_bar(self):
        c = self.colors
        frame = tk.Frame(self, bg=c["bg"], pady=10, padx=14)
        frame.pack(fill="x")
        self.folder_bar_frame = frame

        self.folder_label = tk.Label(frame, text="\U0001F4C1 No folder selected", anchor="w",
                                      bg=c["bg"], fg=c["fg"], font=("Segoe UI", 10))
        self.folder_label.pack(side="left", fill="x", expand=True)

        self.log_toggle_btn = ttk.Button(frame, text="\u25BE Activity Log", command=self.on_toggle_log)
        self.log_toggle_btn.pack(side="right", padx=4)

        theme_box = ttk.Combobox(
            frame, textvariable=None, values=list(THEME_DISPLAY_TO_PREF.keys()),
            state="readonly", width=13,
        )
        self.theme_var = tk.StringVar(value=THEME_PREF_TO_DISPLAY.get(self.theme_pref, "Auto (System)"))
        theme_box.configure(textvariable=self.theme_var)
        theme_box.pack(side="right", padx=4)
        theme_box.bind("<<ComboboxSelected>>", self.on_theme_change)
        tk.Label(frame, text="Theme:", bg=c["bg"], fg=c["fg"]).pack(side="right", padx=(12, 2))

        self.select_btn = ttk.Button(frame, text="Select Folder to Scan", command=self.on_select_folder)
        self.select_btn.pack(side="right", padx=4)
        self.scan_btn = ttk.Button(frame, text="Scan", style="Accent.TButton",
                                    command=self.on_scan, state="disabled")
        self.scan_btn.pack(side="right", padx=4)

    def _build_log_panel(self):
        """A collapsible activity log showing what the app is doing right
        now, and a running history of completed steps (scans, analysis,
        deletions, deep scans) with success/failure status."""
        c = self.colors
        self.log_frame = tk.Frame(self, bg=c["log_bg"], padx=14, pady=8)
        # Not packed until toggled visible.

        header = tk.Frame(self.log_frame, bg=c["log_bg"])
        header.pack(fill="x")
        tk.Label(header, text="Activity Log", bg=c["log_bg"], fg=c["log_fg"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(header, text="(current + past operations)", bg=c["log_bg"], fg=c["muted_fg"],
                 font=("Segoe UI", 8)).pack(side="left", padx=6)
        ttk.Button(header, text="Clear", command=self._clear_log).pack(side="right")

        text_frame = tk.Frame(self.log_frame, bg=c["log_bg"])
        text_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.log_text = tk.Text(
            text_frame, height=8, bg=c["log_bg"], fg=c["log_fg"], insertbackground=c["log_fg"],
            font=("Consolas", 9), wrap="word", borderwidth=0, state="disabled",
        )
        log_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.log_text.tag_configure("info", foreground=c["log_info"])
        self.log_text.tag_configure("success", foreground=c["log_success"])
        self.log_text.tag_configure("error", foreground=c["log_error"])

        for line, level in self.log_entries:
            self._append_log_line(line, level)

    def _build_progress_bar(self):
        c = self.colors
        self.progress_frame = tk.Frame(self, bg=c["bg"], padx=14)

        row = tk.Frame(self.progress_frame, bg=c["bg"])
        row.pack(fill="x", pady=(0, 2))
        self.progress_bar = ttk.Progressbar(row, orient="horizontal", mode="determinate")
        self.progress_bar.pack(side="left", fill="x", expand=True)
        self.cancel_scan_btn = ttk.Button(row, text="Cancel Scan", style="Danger.TButton",
                                           command=self.on_cancel_scan)
        self.cancel_scan_btn.pack(side="left", padx=(8, 0))

        self.progress_status = tk.Label(self.progress_frame, text="", anchor="w", bg=c["bg"],
                                         fg=c["muted_fg"], font=("Segoe UI", 9))
        self.progress_status.pack(fill="x")
        # not packed until a scan starts

    def _build_summary_bar(self):
        c = self.colors
        frame = tk.Frame(self, bg=c["panel_bg"], padx=14, pady=10)
        frame.pack(fill="x", padx=14, pady=(4, 0))
        self.summary_frame = frame
        self.summary_vars = {
            "total": tk.StringVar(value="Total scanned: -"),
            "junk": tk.StringVar(value="Potential junk: -"),
            "items": tk.StringVar(value="Items found: -"),
            "junk_items": tk.StringVar(value="Possible junk items: -"),
        }
        for key in ("total", "junk", "items", "junk_items"):
            tk.Label(frame, textvariable=self.summary_vars[key], font=("Segoe UI", 10, "bold"),
                     bg=c["panel_bg"], fg=c["fg"], padx=16).pack(side="left")

        tk.Label(
            frame, text="\u26A0 Dorian can make mistakes \u2014 always review before deleting.",
            font=("Segoe UI", 8, "italic"), bg=c["panel_bg"], fg=c["muted_fg"],
        ).pack(side="right", padx=8)

    def _build_filter_bar(self):
        c = self.colors
        frame = tk.Frame(self, bg=c["bg"], padx=14, pady=8)
        frame.pack(fill="x")

        tk.Label(frame, text="Filter:", bg=c["bg"], fg=c["fg"]).pack(side="left")
        self.filter_var = tk.StringVar(value="All")
        filter_box = ttk.Combobox(frame, textvariable=self.filter_var, values=FILTER_OPTIONS,
                                   state="readonly", width=20)
        filter_box.pack(side="left", padx=(4, 16))
        filter_box.bind("<<ComboboxSelected>>", lambda e: self.render_tree())

        tk.Label(frame, text="Sort by:", bg=c["bg"], fg=c["fg"]).pack(side="left")
        self.sort_var = tk.StringVar(value="Junk probability")
        sort_box = ttk.Combobox(frame, textvariable=self.sort_var, values=SORT_OPTIONS,
                                 state="readonly", width=18)
        sort_box.pack(side="left", padx=4)
        sort_box.bind("<<ComboboxSelected>>", lambda e: self.render_tree())

        self.sort_dir_btn = ttk.Button(frame, text="\u2193 High to Low", command=self.on_toggle_sort_dir, width=14)
        self.sort_dir_btn.pack(side="left", padx=4)

        ttk.Button(frame, text="Select Recommended", command=self.on_select_recommended).pack(side="right", padx=4)
        ttk.Button(frame, text="Details", command=self.on_details).pack(side="right", padx=4)
        ttk.Button(frame, text="Why?", command=self.on_why).pack(side="right", padx=4)
        ttk.Button(frame, text="Deselect All", command=self.on_deselect_all).pack(side="right", padx=4)
        ttk.Button(frame, text="Select All", command=self.on_select_all).pack(side="right", padx=4)

    def _build_results_tree(self):
        c = self.colors
        frame = tk.Frame(self, bg=c["bg"], padx=14, pady=4)
        frame.pack(fill="both", expand=True)

        columns = ("sel", "category", "size", "importance", "junk", "status")
        self.tree = ttk.Treeview(frame, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Name")
        self.tree.heading("sel", text="")
        self.tree.heading("category", text="Category")
        self.tree.heading("size", text="Size")
        self.tree.heading("importance", text="Importance")
        self.tree.heading("junk", text="Junk %")
        self.tree.heading("status", text="Status")

        self.tree.column("#0", width=380)
        self.tree.column("sel", width=34, anchor="center", stretch=False)
        self.tree.column("category", width=150, anchor="center")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("importance", width=90, anchor="center")
        self.tree.column("junk", width=80, anchor="center")
        self.tree.column("status", width=170, anchor="center")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("info", foreground=c["muted_fg"])
        self.tree.tag_configure("running", foreground=c["log_success"], font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("protected", foreground=c["muted_fg"])
        self.tree.tag_configure("status_keep", background=c["keep"], foreground=c["keep_fg"])
        self.tree.tag_configure("status_review", background=c["review"], foreground=c["review_fg"])
        self.tree.tag_configure("status_probably", background=c["probably"], foreground=c["probably_fg"])
        self.tree.tag_configure("status_junk", background=c["junk"], foreground=c["junk_fg"])

        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Button-3>", self.on_tree_right_click)   # Windows/Linux
        self.tree.bind("<Button-2>", self.on_tree_right_click)   # macOS trackpad

    def _build_bottom_bar(self):
        c = self.colors
        frame = tk.Frame(self, bg=c["panel_bg"], padx=14, pady=12)
        frame.pack(fill="x", padx=14, pady=(0, 14))
        self.selection_label = tk.Label(frame, text="Selected: 0 items (0 B)", font=("Segoe UI", 10, "bold"),
                                         bg=c["panel_bg"], fg=c["fg"])
        self.selection_label.pack(side="left")

        self.permanent_delete_btn = ttk.Button(
            frame, text="\u26A0 Permanently Delete Selected", style="Danger.TButton",
            command=self.on_permanent_delete_selected,
        )
        self.permanent_delete_btn.pack(side="right", padx=(8, 0))

        self.delete_btn = ttk.Button(
            frame, text="\U0001F5D1 Move Selected Items to Recycle Bin", style="Accent.TButton",
            command=self.on_delete_selected,
        )
        self.delete_btn.pack(side="right")

    # ------------------------------------------------------------------
    # Theme switching
    # ------------------------------------------------------------------
    def on_theme_change(self, event=None):
        display = self.theme_var.get()
        self.theme_pref = THEME_DISPLAY_TO_PREF.get(display, "auto")
        save_settings({"theme": self.theme_pref})
        self.theme_name = detect_system_theme() if self.theme_pref == "auto" else self.theme_pref
        self.colors = DARK if self.theme_name == "dark" else LIGHT
        self._log(f"Theme changed to {display} ({self.theme_name}).", "info")
        self.rebuild_ui()

    def rebuild_ui(self):
        """Rebuild the entire widget tree with the current color palette,
        preserving scan results, selection, filters and log history.
        Simpler and much less error-prone than manually re-coloring every
        individual widget.
        """
        filter_val = self.filter_var.get()
        sort_val = self.sort_var.get()
        sort_desc = self.sort_desc
        log_visible = self.log_visible

        for child in self.winfo_children():
            child.destroy()

        self.log_visible = False
        self._build_all()

        self.filter_var.set(filter_val)
        self.sort_var.set(sort_val)
        self.sort_desc = sort_desc
        self.sort_dir_btn.config(text="\u2193 High to Low" if sort_desc else "\u2191 Low to High")

        if self.selected_folder:
            self.folder_label.config(text=f"\U0001F4C1 {self.selected_folder}")
            self.select_btn.config(text="Change Folder")
            self.scan_btn.config(state="normal")

        if self.tree_data:
            self.render_tree()
        if self.last_summary:
            self._update_summary(self.last_summary)

        if log_visible:
            self.on_toggle_log()

    # ------------------------------------------------------------------
    # Activity log
    # ------------------------------------------------------------------
    def _log(self, message, level="info"):
        timestamp = dt.datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.log_entries.append((line, level))
        self._append_log_line(line, level)

    def _append_log_line(self, line, level):
        self.log_text.config(state="normal")
        self.log_text.insert("end", line + "\n", level)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self.log_entries = []
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def on_toggle_log(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_frame.pack(fill="x", padx=14, pady=(0, 4), after=self.folder_bar_frame)
            self.log_toggle_btn.config(text="\u25B4 Activity Log")
        else:
            self.log_frame.pack_forget()
            self.log_toggle_btn.config(text="\u25BE Activity Log")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _default_browse_dir(self):
        """Where the folder-picker should open by default. Windows'
        native dialog otherwise ignores the app's own location and opens
        wherever it last remembered (often C:\\Users\\...\\Documents),
        which is confusing if the app itself lives on a different drive
        (e.g. D:). We default to the root of the drive the app is
        running from instead.
        """
        drive, _ = os.path.splitdrive(APP_DIR)
        if drive:
            root = drive + os.sep
            if os.path.isdir(root):
                return root
        return APP_DIR if os.path.isdir(APP_DIR) else os.path.expanduser("~")

    def on_select_folder(self):
        folder = filedialog.askdirectory(
            title="Select a folder to analyze",
            initialdir=self.last_browse_dir,
        )
        if not folder:
            return
        self.selected_folder = folder
        self.last_browse_dir = folder
        self.folder_label.config(text=f"\U0001F4C1 {folder}")
        self.select_btn.config(text="Change Folder")
        self.scan_btn.config(state="normal")
        self._log(f"Folder selected: {folder}", "info")

    def on_scan(self):
        if not self.selected_folder:
            return
        self.scan_btn.config(state="disabled")
        self.select_btn.config(state="disabled")
        self.scan_stop_event = threading.Event()
        self.cancel_scan_btn.config(state="normal", text="Cancel Scan")
        self.progress_frame.pack(fill="x", padx=14, pady=(0, 4), before=self.summary_frame)
        self.progress_bar["value"] = 0
        self.progress_status.config(text="Starting scan...")
        self._log(f"Scan started: {self.selected_folder}", "info")
        if not self.log_visible:
            self.on_toggle_log()

        threading.Thread(target=self._run_scan_thread, daemon=True).start()

    def on_cancel_scan(self):
        if self.scan_stop_event:
            self.scan_stop_event.set()
        self.cancel_scan_btn.config(state="disabled", text="Cancelling...")
        self.progress_status.config(text="Cancelling scan...")

    def _run_scan_thread(self):
        try:
            self.controller.run_full_scan(
                self.selected_folder,
                progress_callback=self._threadsafe_progress,
                done_callback=self._threadsafe_done,
                error_callback=self._threadsafe_error,
                cancelled_callback=self._threadsafe_cancelled,
                stop_event=self.scan_stop_event,
            )
        except Exception as exc:  # noqa: BLE001
            self._threadsafe_error(str(exc))

    def _threadsafe_progress(self, message, percent):
        self.after(0, self._update_progress, message, percent)

    def _threadsafe_done(self, tree, summary):
        self.after(0, self._on_scan_done, tree, summary)

    def _threadsafe_error(self, message):
        self.after(0, self._on_scan_error, message)

    def _threadsafe_cancelled(self):
        self.after(0, self._on_scan_cancelled)

    def _update_progress(self, message, percent):
        self.progress_bar["value"] = percent
        self.progress_status.config(text=f"{message}  ({percent}%)")
        if percent in (0, 25, 50, 75, 100):
            self._log(f"{message} ({percent}%)", "info")

    def _on_scan_done(self, tree, summary):
        self.progress_frame.pack_forget()
        self.scan_btn.config(state="normal")
        self.select_btn.config(state="normal")
        self.tree_data = tree
        self.checked_paths = set()
        self.node_by_path = {}
        self._index_nodes(tree)
        self.render_tree()
        self.last_summary = summary
        self._update_summary(summary)
        self._log(
            f"Scan complete: {summary['items_found']:,} items analyzed, "
            f"{summary['junk_items']:,} flagged as possible junk "
            f"({human_size(summary['potential_junk_size'])}).",
            "success",
        )

    def _on_scan_error(self, message):
        self.progress_frame.pack_forget()
        self.scan_btn.config(state="normal")
        self.select_btn.config(state="normal")
        self._log(f"Scan failed: {message}", "error")
        messagebox.showerror("Scan failed", message)

    def _on_scan_cancelled(self):
        self.progress_frame.pack_forget()
        self.scan_btn.config(state="normal")
        self.select_btn.config(state="normal")
        self._log("Scan cancelled by user.", "info")
        messagebox.showinfo("Scan cancelled", "The scan was cancelled. Nothing was analyzed or changed.")

    def _index_nodes(self, nodes):
        for node in nodes:
            self.node_by_path[node["path"]] = node
            if node["node_type"] == "folder":
                self._index_nodes(node["children"])

    def _update_summary(self, summary):
        self.summary_vars["total"].set(f"Total scanned: {human_size(summary['total_size'])}")
        self.summary_vars["junk"].set(f"Potential junk: {human_size(summary['potential_junk_size'])}")
        self.summary_vars["items"].set(f"Items found: {summary['items_found']:,}")
        self.summary_vars["junk_items"].set(f"Possible junk items: {summary['junk_items']:,}")

    # ------------------------------------------------------------------
    # Rendering / filtering / sorting
    # ------------------------------------------------------------------
    def on_toggle_sort_dir(self):
        self.sort_desc = not self.sort_desc
        self.sort_dir_btn.config(text="\u2193 High to Low" if self.sort_desc else "\u2191 Low to High")
        self.render_tree()

    def render_tree(self):
        self.tree.delete(*self.tree.get_children(""))
        nodes = self._sort_nodes(self.tree_data)
        for node in nodes:
            self._insert_actionable(node, "")
        self._update_selection_label()

    def _matches_filter(self, node):
        f = self.filter_var.get()
        if f == "All":
            return True
        status = node.get("status")
        category = node.get("category")
        mapping = {
            "Likely Junk": status == "Likely junk",
            "Probably Unnecessary": status == "Probably unnecessary",
            "Review": status == "Review",
            "Keep": status == "Keep",
            "Games": category == "Game",
            "Applications": category == "Application",
            "Installers": category == "Installer",
            "Documents": category == "Documents",
            "Archives": category == "Archive",
            "Duplicates": bool(node.get("is_duplicate")),
        }
        return mapping.get(f, True)

    def _subtree_has_match(self, node):
        if self._matches_filter(node):
            return True
        if node["node_type"] == "folder":
            return any(self._subtree_has_match(c) for c in node["children"])
        return False

    def _sort_key(self, node):
        key = self.sort_var.get()
        return {
            "Size": node.get("size", 0),
            "Importance": node.get("importance", 0),
            "Junk probability": node.get("junk_probability", 0),
            "Last accessed": node.get("accessed", 0),
            "Last modified": node.get("modified", 0),
            "Creation date": node.get("created", 0),
            "Category": node.get("category", ""),
        }.get(key, 0)

    def _sort_nodes(self, nodes):
        visible = [n for n in nodes if self._subtree_has_match(n)]
        return sorted(visible, key=self._sort_key, reverse=self.sort_desc)

    def _insert_actionable(self, node, parent_iid):
        checkbox = CHECK_FILLED if node["path"] in self.checked_paths else CHECK_EMPTY
        icon = CATEGORY_ICON.get(node.get("category"), CATEGORY_ICON["Unknown"])
        status_icon = STATUS_ICON.get(node.get("status"), "")
        dup_count = node.get("duplicate_count") or 0
        dup_mark = f" \u267B {dup_count} other cop{'y' if dup_count == 1 else 'ies'}" if dup_count else ""
        text = f"{icon} {node['name']}{dup_mark}"

        if node.get("is_protected"):
            tags = ["protected"]
        elif node.get("is_running"):
            tags = ["running"]
        else:
            tags = [STATUS_TAG.get(node.get("status"), "status_review")]

        iid = self.tree.insert(
            parent_iid, "end", iid=node["path"], text=text,
            values=(
                checkbox, node.get("category", ""), human_size(node.get("size", 0)),
                f"{node.get('importance', 0)}/100", f"{node.get('junk_probability', 0)}%",
                f"{status_icon} {node.get('status', '')}".strip(),
            ),
            tags=tags,
        )
        if node.get("is_running"):
            self.tree.insert(iid, "end", text="   \U0001F7E2 Currently running - not selectable",
                              values=("", "", "", "", "", ""), tags=("info",))

        if node["node_type"] == "bundle":
            for child in node.get("children", []):
                self._insert_info_child(child, iid)
        elif node["node_type"] == "folder":
            for child in self._sort_nodes(node["children"]):
                self._insert_actionable(child, iid)

    def _insert_info_child(self, info_node, parent_iid):
        iid = self.tree.insert(
            parent_iid, "end", iid=f"info::{info_node['path']}",
            text=f"   {info_node['name']}",
            values=("", "", human_size(info_node.get("size", 0)), "", "", ""),
            tags=("info",),
        )
        for child in info_node.get("children", []):
            self._insert_info_child(child, iid)

    def _update_selection_label(self):
        total = sum(self.node_by_path[p]["size"] for p in self.checked_paths if p in self.node_by_path)
        self.selection_label.config(text=f"Selected: {len(self.checked_paths)} items ({human_size(total)})")

    # ------------------------------------------------------------------
    # Tree interaction
    # ------------------------------------------------------------------
    def on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        column = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or row.startswith("info::"):
            return
        if column == "#1":  # the "sel" checkbox column
            self._toggle_checked(row)

    def _toggle_checked(self, path):
        node = self.node_by_path.get(path)
        if not node:
            return
        blocked, reason = self._blocked_reason(node)
        if blocked:
            self._show_cannot_select(node, reason)
            return
        if path in self.checked_paths:
            self.checked_paths.discard(path)
        else:
            self.checked_paths.add(path)
        self.tree.set(path, "sel", CHECK_FILLED if path in self.checked_paths else CHECK_EMPTY)
        self._update_selection_label()

    def _blocked_reason(self, node):
        """Returns (blocked: bool, reason: str|None) explaining why an
        item can't be selected, if applicable."""
        if node.get("is_protected"):
            return True, "This is a protected Windows system location and can never be deleted from here."
        if node.get("is_running"):
            return True, "This application/game appears to be running right now, so it can't be deleted safely."
        if node.get("category") == "Unknown" and node.get("status") not in (
            "Probably unnecessary", "Likely junk",
        ):
            return True, "Not enough information is available to confidently judge this item."
        return False, None

    def _show_cannot_select(self, node, reason):
        lines = [reason, ""]
        guess = node.get("ai_guess")
        if guess:
            lines.append(f"Dorian's best guess at what this might be:\n\"{guess}\"")
            lines.append("")
        lines.append(
            "You can still open it or show it in File Explorer (right-click the row) "
            "to decide for yourself."
        )
        self._show_popup("Why can't I select this?", "\n".join(lines))

    def _get_selected_node(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No item selected", "Click a row first, then press this button.")
            return None
        path = sel[0]
        if path.startswith("info::"):
            messagebox.showinfo("No details", "This is just a preview of a bundle's contents.")
            return None
        return self.node_by_path.get(path)

    def on_why(self):
        node = self._get_selected_node()
        if not node:
            return
        why = node.get("why") or [node.get("reason", "No explanation available.")]
        text = "Why is this considered " + node.get("status", "this") + "?\n\n"
        text += "\n".join(f"\u2022 {w}" for w in why)
        if node.get("category") == "Unknown" and node.get("ai_guess"):
            text += f"\n\n\U0001F916 Dorian's best guess: {node['ai_guess']}"
        if node.get("duplicate_count"):
            text += f"\n\n\u267B {node['duplicate_count']} other cop{'y' if node['duplicate_count'] == 1 else 'ies'} found in this scan."
        text += f"\n\nDorian's confidence: {max(node.get('importance', 0), node.get('junk_probability', 0))}%"
        self._show_popup("Why?", text)

    def on_details(self):
        node = self._get_selected_node()
        if not node:
            return

        def fmt(ts):
            try:
                return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return "unknown"

        lines = [
            f"Path: {node['path']}",
            f"Type: {node['node_type']} ({node.get('category', 'Unknown')})",
            f"Size: {human_size(node.get('size', 0))}",
            f"Created: {fmt(node.get('created', 0))}",
            f"Last modified: {fmt(node.get('modified', 0))}",
            f"Last accessed: {fmt(node.get('accessed', 0))}",
            f"Currently running: {'Yes' if node.get('is_running') else 'No'}",
            f"Duplicate copies found (in this scan): {node.get('duplicate_count', 0)}",
            f"Importance: {node.get('importance', 0)}/100",
            f"Junk probability: {node.get('junk_probability', 0)}%",
            f"Status: {node.get('status', '')}",
        ]
        if node.get("category") == "Unknown" and node.get("ai_guess"):
            lines.append(f"\nDorian's best guess: {node['ai_guess']}")
        lines.append(f"\nReason: {node.get('reason', '')}")
        if node["node_type"] == "file":
            lines.append("\n(Right-click this row \u2192 \"Find Duplicates Across Computer\" to search your whole PC for other copies.)")
        self._show_popup("Details", "\n".join(lines))

    def _show_popup(self, title, text):
        c = self.colors
        win = tk.Toplevel(self, bg=c["panel_bg"])
        win.title(title)
        win.geometry("480x400")
        text_widget = tk.Text(win, wrap="word", padx=14, pady=14, font=("Segoe UI", 10),
                               bg=c["panel_bg"], fg=c["fg"], borderwidth=0)
        text_widget.insert("1.0", text)
        text_widget.config(state="disabled")
        text_widget.pack(fill="both", expand=True)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=8)

    # ------------------------------------------------------------------
    # Right-click: open / show in Explorer / deep-scan for duplicates
    # ------------------------------------------------------------------
    def on_tree_right_click(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)

        real_path = row[len("info::"):] if row.startswith("info::") else row
        if not os.path.exists(real_path):
            messagebox.showinfo("Not found", "This item no longer exists on disk.")
            return

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="\U0001F4C2 Show in File Explorer",
                          command=lambda: self._show_in_explorer(real_path))
        menu.add_command(label="\u25B6 Open", command=lambda: self._open_path(real_path))
        if not row.startswith("info::"):
            menu.add_separator()
            menu.add_command(label="Toggle checkbox", command=lambda: self._toggle_checked(real_path))
            menu.add_command(label="Why?", command=self.on_why)
            menu.add_command(label="Details", command=self.on_details)
            node = self.node_by_path.get(real_path)
            if node and node.get("node_type") == "file":
                menu.add_separator()
                menu.add_command(
                    label="\U0001F50D Find Duplicates Across Computer",
                    command=lambda: self.on_deep_scan(real_path),
                )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _show_in_explorer(self, path):
        try:
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", path])
            else:
                subprocess.run(["xdg-open", os.path.dirname(path)])
            self._log(f"Opened Explorer for: {path}", "info")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Couldn't open Explorer", str(exc))

    def _open_path(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606 - Windows-only, user-initiated
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
            self._log(f"Opened: {path}", "info")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Couldn't open item", str(exc))

    # ------------------------------------------------------------------
    # Deep scan: search the whole computer for duplicates of one file
    # ------------------------------------------------------------------
    def on_deep_scan(self, path):
        node = self.node_by_path.get(path)
        if not node or node.get("node_type") != "file":
            messagebox.showinfo(
                "Not supported",
                "Deep scan currently works on individual files, not whole folders or bundles.",
            )
            return
        if not messagebox.askyesno(
            "Deep Scan Duplicates",
            f"This will search your entire computer for other copies of:\n\n{node['name']}\n\n"
            "This can take a while on large drives (it walks every fixed drive). Continue?",
        ):
            return

        self.deep_scan_stop_event = threading.Event()
        progress_win = self._build_deep_scan_progress_window()
        if not self.log_visible:
            self.on_toggle_log()
        self._log(f"Deep scan started for: {node['path']}", "info")

        def progress_cb(current_path, scanned_count):
            self.after(0, self._update_deep_scan_progress, progress_win, current_path, scanned_count)

        def done_cb(matches):
            self.after(0, self._on_deep_scan_done, progress_win, node, matches)

        def error_cb(msg):
            self.after(0, self._on_deep_scan_error, progress_win, msg)

        threading.Thread(
            target=self.controller.deep_scan_duplicates,
            args=(node, progress_cb, done_cb, error_cb, self.deep_scan_stop_event),
            daemon=True,
        ).start()

    def _build_deep_scan_progress_window(self):
        c = self.colors
        win = tk.Toplevel(self, bg=c["panel_bg"])
        win.title("Deep Scan in Progress")
        win.geometry("480x170")
        win.protocol("WM_DELETE_WINDOW", lambda: None)  # must Cancel, not just close
        tk.Label(win, text="Searching your computer for duplicate files...",
                 font=("Segoe UI", 10, "bold"), bg=c["panel_bg"], fg=c["fg"], pady=10).pack()
        pb = ttk.Progressbar(win, mode="indeterminate")
        pb.pack(fill="x", padx=16)
        pb.start(12)
        status = tk.Label(win, text="Starting...", bg=c["panel_bg"], fg=c["muted_fg"],
                           font=("Segoe UI", 9), wraplength=440, justify="left")
        status.pack(pady=8, padx=16, fill="x")
        ttk.Button(win, text="Cancel", style="Danger.TButton",
                   command=lambda: self.deep_scan_stop_event.set()).pack(pady=6)
        win.status_label = status
        win.progress_bar = pb
        return win

    def _update_deep_scan_progress(self, win, path, count):
        if not win.winfo_exists():
            return
        win.status_label.config(text=f"Scanned {count:,} files so far...\n{path}")
        if count % 2000 < 25:
            self._log(f"Deep scan: {count:,} files scanned so far...", "info")

    def _close_deep_scan_window(self, win):
        try:
            win.progress_bar.stop()
            win.destroy()
        except tk.TclError:
            pass

    def _on_deep_scan_done(self, win, node, matches):
        self._close_deep_scan_window(win)
        if matches is None:
            self._log("Deep scan cancelled.", "info")
            messagebox.showinfo("Cancelled", "Deep scan was cancelled.")
            return
        self._log(
            f"Deep scan complete: found {len(matches)} duplicate cop{'y' if len(matches) == 1 else 'ies'} "
            f"of {node['name']}.", "success",
        )
        if not matches:
            messagebox.showinfo("No duplicates found", f"No other copies of \"{node['name']}\" were found on your computer.")
            return
        self._show_deep_scan_results(node, matches)

    def _on_deep_scan_error(self, win, msg):
        self._close_deep_scan_window(win)
        self._log(f"Deep scan failed: {msg}", "error")
        messagebox.showerror("Deep scan failed", msg)

    def _show_deep_scan_results(self, original_node, matches):
        """Lets the user pick exactly which copies to remove: keep the
        original and delete the rest (the default), delete everything
        including the original, or any custom combination.
        """
        c = self.colors
        win = tk.Toplevel(self, bg=c["panel_bg"])
        win.title("Duplicates Found")
        win.geometry("680x500")

        total_extra = sum(m["size"] for m in matches)
        tk.Label(
            win,
            text=f"Found {len(matches)} other cop{'y' if len(matches) == 1 else 'ies'} of "
                 f"\"{original_node['name']}\" on your computer ({human_size(total_extra)} total).\n"
                 f"Check the items you want to remove -- the original (from your scanned folder) "
                 f"is unchecked by default.",
            font=("Segoe UI", 10, "bold"), bg=c["panel_bg"], fg=c["fg"], wraplength=640,
            justify="left", anchor="w", padx=12, pady=10,
        ).pack(fill="x")

        tk.Label(
            win, text="\u26A0 Matches are based on file content hashing, which is reliable but not "
                      "infallible \u2014 double-check before deleting.",
            font=("Segoe UI", 9, "italic"), bg=c["panel_bg"], fg=c["muted_fg"],
            wraplength=640, justify="left", anchor="w", padx=12,
        ).pack(fill="x")

        tv = ttk.Treeview(win, columns=("sel", "size", "path"), show="headings", height=14)
        tv.heading("sel", text="")
        tv.heading("size", text="Size")
        tv.heading("path", text="Location")
        tv.column("sel", width=34, anchor="center", stretch=False)
        tv.column("size", width=90, anchor="e")
        tv.column("path", width=520, anchor="w")

        list_frame = tk.Frame(win, bg=c["panel_bg"])
        list_frame.pack(fill="both", expand=True, padx=12)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        tv.pack(in_=list_frame, side="left", fill="both", expand=True)
        vsb.pack(in_=list_frame, side="right", fill="y")

        checked = set()
        row_info = {}

        def add_row(row_path, size, is_original, checked_default):
            label = row_path + ("   (original \u2014 the one you scanned from)" if is_original else "")
            iid = tv.insert("", "end", values=(CHECK_FILLED if checked_default else CHECK_EMPTY,
                                                human_size(size), label))
            row_info[iid] = {"path": row_path, "size": size}
            if checked_default:
                checked.add(iid)

        add_row(original_node["path"], original_node["size"], True, False)
        for m in matches:
            add_row(m["path"], m["size"], False, True)

        def toggle(event):
            if tv.identify_region(event.x, event.y) != "cell":
                return
            if tv.identify_column(event.x) != "#1":
                return
            row = tv.identify_row(event.y)
            if not row:
                return
            if row in checked:
                checked.discard(row)
            else:
                checked.add(row)
            tv.set(row, "sel", CHECK_FILLED if row in checked else CHECK_EMPTY)

        tv.bind("<Button-1>", toggle)

        btn_frame = tk.Frame(win, bg=c["panel_bg"])
        btn_frame.pack(fill="x", pady=10, padx=12)

        def act(permanent):
            chosen = [row_info[iid] for iid in checked]
            if not chosen:
                messagebox.showinfo("Nothing selected", "Check at least one item first.")
                return
            verb = "permanently delete" if permanent else "move to the Recycle Bin"
            if not messagebox.askyesno(
                "Confirm",
                f"Are you sure you want to {verb} {len(chosen)} item(s) totalling "
                f"{human_size(sum(i['size'] for i in chosen))}?",
            ):
                return
            nodes = [{
                "path": i["path"], "name": os.path.basename(i["path"]), "size": i["size"],
                "category": "Duplicate", "is_running": False, "extension": os.path.splitext(i["path"])[1].lower(),
                "status": "Likely junk",
            } for i in chosen]
            results = self.controller.delete_items(nodes, permanent=permanent)
            for result_path, ok, err in results:
                if ok:
                    self._log(f"{'Permanently deleted' if permanent else 'Moved to Recycle Bin'}: {result_path}", "success")
                    self.node_by_path.pop(result_path, None)
                    self._remove_from_tree_data(self.tree_data, result_path)
                else:
                    self._log(f"Failed to delete {result_path}: {err}", "error")
            self.render_tree()
            win.destroy()
            if not self.log_visible:
                self.on_toggle_log()
            messagebox.showinfo("Done", f"Processed {len(chosen)} item(s). See the Activity Log for details.")

        ttk.Button(btn_frame, text="Move Checked to Recycle Bin", style="Accent.TButton",
                   command=lambda: act(False)).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Permanently Delete Checked", style="Danger.TButton",
                   command=lambda: act(True)).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Close", command=win.destroy).pack(side="right", padx=4)

    # ------------------------------------------------------------------
    # Bulk selection
    # ------------------------------------------------------------------
    def on_select_all(self):
        for path, node in self.node_by_path.items():
            blocked, _ = self._blocked_reason(node)
            if blocked or not self._matches_filter(node):
                continue
            self.checked_paths.add(path)
        self.render_tree()
        self._log(f"Selected all visible items ({len(self.checked_paths)} total).", "info")

    def on_deselect_all(self):
        self.checked_paths.clear()
        self.render_tree()
        self._log("Deselected all items.", "info")

    def on_select_recommended(self):
        count = 0
        for path, node in self.node_by_path.items():
            blocked, _ = self._blocked_reason(node)
            if blocked:
                continue
            if node.get("status") in ("Probably unnecessary", "Likely junk"):
                self.checked_paths.add(path)
                count += 1
        self.render_tree()
        self._log(f"Selected {count} recommended item(s).", "info")
        messagebox.showinfo("Selection updated", f"Selected {count} recommended item(s). Nothing has been deleted yet.")

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------
    def on_delete_selected(self):
        self._delete_flow(permanent=False)

    def on_permanent_delete_selected(self):
        self._delete_flow(permanent=True)

    def _delete_flow(self, permanent):
        if not self.checked_paths:
            messagebox.showinfo("Nothing selected", "Select at least one item first.")
            return
        nodes = [self.node_by_path[p] for p in self.checked_paths if p in self.node_by_path]
        total_size = sum(n["size"] for n in nodes)
        c = self.colors

        confirm = tk.Toplevel(self, bg=c["panel_bg"])
        confirm.title("Confirm permanent deletion" if permanent else "Confirm deletion")
        confirm.geometry("520x430")

        if permanent:
            tk.Label(
                confirm,
                text="\u26A0 This will PERMANENTLY delete the following items.\n"
                     "They will NOT go to the Recycle Bin and cannot be recovered.",
                font=("Segoe UI", 11, "bold"), fg=c["danger"], bg=c["panel_bg"], justify="left",
                anchor="w", padx=12, pady=8, wraplength=490,
            ).pack(fill="x")
        else:
            tk.Label(confirm, text="You are about to move:", font=("Segoe UI", 11, "bold"),
                     bg=c["panel_bg"], fg=c["fg"], anchor="w", padx=12, pady=8).pack(fill="x")

        listbox = tk.Listbox(confirm, bg=c["entry_bg"], fg=c["fg"], borderwidth=0)
        for n in nodes:
            listbox.insert("end", f"{n['name']}  \u2014  {human_size(n['size'])}")
        listbox.pack(fill="both", expand=True, padx=12)
        tk.Label(confirm, text=f"Total: {human_size(total_size)}", font=("Segoe UI", 10, "bold"),
                 bg=c["panel_bg"], fg=c["fg"], pady=8).pack()

        tk.Label(
            confirm,
            text="\u26A0 Dorian's recommendations can be wrong. Double-check this list before continuing.",
            font=("Segoe UI", 9, "italic"), bg=c["panel_bg"], fg=c["muted_fg"], wraplength=490,
        ).pack(pady=(0, 4))

        confirm_var = tk.BooleanVar(value=False)
        if permanent:
            ttk.Checkbutton(
                confirm, variable=confirm_var,
                text="I understand this cannot be undone.",
            ).pack(pady=(0, 4))

        btn_frame = tk.Frame(confirm, bg=c["panel_bg"], pady=10)
        btn_frame.pack()
        ttk.Button(btn_frame, text="Cancel", command=confirm.destroy).pack(side="left", padx=8)

        def do_confirm():
            if permanent and not confirm_var.get():
                messagebox.showwarning(
                    "Please confirm", "Check the box to confirm you understand this cannot be undone.",
                )
                return
            self._confirm_delete(nodes, confirm, permanent)

        ttk.Button(
            btn_frame,
            text="Permanently Delete" if permanent else "Move to Recycle Bin",
            style="Danger.TButton" if permanent else "Accent.TButton",
            command=do_confirm,
        ).pack(side="left", padx=8)

    def _confirm_delete(self, nodes, confirm_window, permanent):
        confirm_window.destroy()
        results = self.controller.delete_items(nodes, permanent=permanent)
        succeeded = [p for p, ok, _ in results if ok]
        failed = [(p, err) for p, ok, err in results if not ok]

        by_path = {n["path"]: n for n in nodes}
        for path, ok, err in results:
            name = by_path[path]["name"]
            if ok:
                self._log(f"{'Permanently deleted' if permanent else 'Moved to Recycle Bin'}: {name}", "success")
            else:
                self._log(f"Failed to delete {name}: {err}", "error")

        for path in succeeded:
            self.checked_paths.discard(path)
            self.node_by_path.pop(path, None)
            self._remove_from_tree_data(self.tree_data, path)

        self.render_tree()

        verb = "Permanently deleted" if permanent else "Moved"
        suffix = "" if permanent else " to the Recycle Bin"
        msg = f"{verb} {len(succeeded)} item(s){suffix}."
        if failed:
            msg += f"\n\n{len(failed)} item(s) could not be removed:\n"
            msg += "\n".join(f"- {p}: {err}" for p, err in failed[:5])
        if not self.log_visible:
            self.on_toggle_log()
        messagebox.showinfo("Deletion complete", msg)

    def _remove_from_tree_data(self, nodes, path):
        for i, node in enumerate(nodes):
            if node["path"] == path:
                nodes.pop(i)
                return True
            if node["node_type"] == "folder":
                if self._remove_from_tree_data(node["children"], path):
                    return True
        return False
