"""
app.py
------
ibmi-compliance-checker - IBM i (AS400) Configuration Review Tool - Tkinter GUI.

Run with:  python app.py

Workflow:
  1. Connection tab - choose ODBC or SSH, enter authenticated credentials, Connect.
  2. Checks tab - Run All Checks, watch live progress, review results in the table.
  3. Click any row to see full evidence + recommendation in the detail pane.
  4. Export to HTML and/or CSV.

This tool is READ-ONLY: every check either runs a SELECT query (ODBC) or a
retrieval/display command (SSH). Nothing here modifies the target system.
Use only against systems you are explicitly authorized to test.

Created by dunne-dee.
"""

import os
import sys
import threading
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from connectors import IBMiODBCConnector, IBMiSSHConnector, ConnectionError_
from checks_engine import load_checks, run_all_checks
from report_generator import generate_html, generate_csv


PRODUCT_NAME = "ibmi-compliance-checker"
APP_TITLE = "IBM i (AS400) Configuration Review Tool"
CREATED_BY = "dunne-dee"
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# ---- design tokens (shared visual identity with the HTML report) ----
INK = "#0E1420"
INK_2 = "#1B2536"
PAPER = "#F5F6F8"
CARD = "#FFFFFF"
LINE = "#E3E7EE"
TEXT = "#171B24"
MUTED = "#5B6472"
FAINT = "#8A93A3"
BRAND = "#0C7C82"
BRAND_DARK = "#0A6469"
BRAND_LIGHT = "#9FE8E5"

STATUS_COLORS = {
    "PASS": "#167C3D",
    "FAIL": "#B42318",
    "REVIEW": "#A15C07",
    "ERROR": "#55606A",
}
STATUS_BG = {
    "PASS": "#EAF7EF",
    "FAIL": "#FDECEA",
    "REVIEW": "#FCF3E3",
    "ERROR": "#EEF0F3",
}

FONT_SANS = "Segoe UI"
FONT_SERIF = "Georgia"
FONT_MONO = "Consolas"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{PRODUCT_NAME} — {APP_TITLE}")
        self.geometry("1220x740")
        self.minsize(900, 560)
        self.configure(bg=PAPER)

        self._logo_images = {}  # keep PhotoImage refs alive
        self._load_assets()

        self.odbc_connector = None
        self.ssh_connector = None
        self.connected_mode = None
        self.checks = []
        self.results = []
        self.checks_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checks_config.json")

        self._build_style()
        self._build_layout()
        self._load_checks_quiet()

    # ---------- assets ----------

    def _load_assets(self):
        try:
            icon_path = os.path.join(ASSETS_DIR, "logo_256.png")
            if os.path.exists(icon_path):
                icon_img = tk.PhotoImage(file=icon_path)
                self._logo_images["icon"] = icon_img
                self.iconphoto(True, icon_img)
        except Exception:
            pass
        try:
            header_path = os.path.join(ASSETS_DIR, "logo_56.png")
            if os.path.exists(header_path):
                self._logo_images["header"] = tk.PhotoImage(file=header_path)
        except Exception:
            pass

    # ---------- styling ----------

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # base surfaces
        style.configure("TFrame", background=PAPER)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Header.TFrame", background=INK)
        style.configure("Footer.TFrame", background=PAPER)

        # labels
        style.configure("TLabel", background=PAPER, foreground=TEXT, font=(FONT_SANS, 9))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=(FONT_SANS, 9))
        style.configure("Muted.TLabel", background=PAPER, foreground=MUTED, font=(FONT_SANS, 9))
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=(FONT_SANS, 9))
        style.configure("Wordmark.TLabel", background=INK, foreground=BRAND_LIGHT, font=(FONT_MONO, 10))
        style.configure("HeaderTitle.TLabel", background=INK, foreground="#FFFFFF", font=(FONT_SERIF, 21))
        style.configure("HeaderSub.TLabel", background=INK, foreground="#B7C0CE", font=(FONT_SANS, 9))
        style.configure("HeaderMeta.TLabel", background=INK, foreground="#EDF0F4", font=(FONT_SANS, 9, "bold"))
        style.configure("SectionTitle.TLabel", background=PAPER, foreground=INK, font=(FONT_SERIF, 14))

        # notebook / tabs
        style.configure("TNotebook", background=PAPER, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 10), font=(FONT_SANS, 9, "bold"),
                         background=PAPER, foreground=MUTED, borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD)],
                  foreground=[("selected", BRAND_DARK)])

        # label frames (cards)
        style.configure("Card.TLabelframe", background=CARD, bordercolor=LINE, relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=CARD, foreground=MUTED, font=(FONT_SANS, 9, "bold"))

        # buttons
        style.configure("TButton", font=(FONT_SANS, 9), padding=(12, 7),
                         background=CARD, foreground=TEXT, bordercolor=LINE, relief="flat")
        style.map("TButton", background=[("active", PAPER)])
        style.configure("Accent.TButton", font=(FONT_SANS, 9, "bold"), padding=(16, 9),
                         background=BRAND, foreground="#FFFFFF", bordercolor=BRAND, relief="flat")
        style.map("Accent.TButton",
                  background=[("active", BRAND_DARK), ("disabled", "#A9C9CB")],
                  foreground=[("disabled", "#EFF4F4")])
        style.configure("Ghost.TButton", font=(FONT_SANS, 9), padding=(12, 7),
                         background=PAPER, foreground=MUTED, bordercolor=LINE, relief="flat")
        style.map("Ghost.TButton", background=[("active", LINE)], foreground=[("disabled", "#C3C9D1")])

        # entries / inputs
        style.configure("TEntry", fieldbackground="#FFFFFF", bordercolor=LINE, padding=6,
                         relief="flat", borderwidth=1)
        style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=(FONT_SANS, 9))
        style.configure("TRadiobutton", background=CARD, foreground=TEXT, font=(FONT_SANS, 9))
        style.map("TRadiobutton", background=[("active", CARD)])

        # progress bar
        style.configure("Teal.Horizontal.TProgressbar", troughcolor=LINE, background=BRAND,
                         bordercolor=LINE, lightcolor=BRAND, darkcolor=BRAND, thickness=8)

        # treeview
        style.configure("Treeview", rowheight=27, font=(FONT_SANS, 9), background=CARD,
                         fieldbackground=CARD, foreground=TEXT, bordercolor=LINE, borderwidth=0)
        style.configure("Treeview.Heading", font=(FONT_SANS, 8, "bold"), background=PAPER,
                         foreground=MUTED, relief="flat", padding=(6, 8))
        style.map("Treeview.Heading", background=[("active", PAPER)])
        style.map("Treeview", background=[("selected", "#E4F3F3")], foreground=[("selected", INK)])

    # ---------- layout ----------

    def _build_layout(self):
        self._build_header()

        footer = ttk.Frame(self, style="Footer.TFrame", padding=(18, 8))
        footer.pack(side="bottom", fill="x")
        left = f"{PRODUCT_NAME}  ·  Created by {CREATED_BY}"
        ttk.Label(footer, text=left, style="Muted.TLabel", font=(FONT_MONO, 8)).pack(side="left")
        ttk.Label(footer, text="Read-only checks only — no changes made to the target",
                  style="Muted.TLabel", font=(FONT_SANS, 8)).pack(side="right")

        notebook_wrap = ttk.Frame(self, padding=(18, 14, 18, 4))
        notebook_wrap.pack(fill="both", expand=True)

        notebook = ttk.Notebook(notebook_wrap)
        notebook.pack(fill="both", expand=True)
        self.notebook = notebook

        self.conn_tab = ttk.Frame(notebook, padding=18)
        self.checks_tab = ttk.Frame(notebook, padding=16)
        notebook.add(self.conn_tab, text="  1  Connection  ")
        notebook.add(self.checks_tab, text="  2  Run Checks & Results  ")

        self._build_connection_tab()
        self._build_checks_tab()

    def _build_header(self):
        header = ttk.Frame(self, style="Header.TFrame")
        header.pack(fill="x")
        inner = ttk.Frame(header, style="Header.TFrame", padding=(24, 16, 24, 16))
        inner.pack(fill="x")

        # wordmark row
        word_row = ttk.Frame(inner, style="Header.TFrame")
        word_row.pack(fill="x")
        if "header" in self._logo_images:
            tk.Label(word_row, image=self._logo_images["header"], bg=INK, bd=0).pack(side="left", padx=(0, 8))
        ttk.Label(word_row, text=PRODUCT_NAME, style="Wordmark.TLabel").pack(side="left")

        # status pill (dot + text) on the right
        status_frame = ttk.Frame(word_row, style="Header.TFrame")
        status_frame.pack(side="right")
        self._status_canvas = tk.Canvas(status_frame, width=10, height=10, bg=INK,
                                         highlightthickness=0, bd=0)
        self._status_canvas.pack(side="left", padx=(0, 6))
        self._status_dot = self._status_canvas.create_oval(1, 1, 9, 9, fill="#B42318", outline="")
        self.conn_status_var = tk.StringVar(value="Not connected")
        ttk.Label(status_frame, textvariable=self.conn_status_var, style="HeaderMeta.TLabel").pack(side="left")

        ttk.Label(inner, text=APP_TITLE, style="HeaderTitle.TLabel").pack(anchor="w", pady=(14, 4))
        ttk.Label(inner, text="Authenticated, read-only IBM i hardening review mapped to the CIS IBM i Benchmark.",
                  style="HeaderSub.TLabel").pack(anchor="w", pady=(0, 14))

        sep = tk.Frame(inner, bg="#2A3547", height=1)
        sep.pack(fill="x")

    def conn_status_var_color(self, color):
        self._status_canvas.itemconfig(self._status_dot, fill=color)

    def _make_scrollable(self, parent):
        """Wraps a tab's content in a scrollable canvas so nothing can ever be
        pushed fully out of reach, regardless of screen size or DPI scaling."""
        canvas = tk.Canvas(parent, bg=PAPER, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        inner = ttk.Frame(canvas)
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_configure)

        def _on_canvas_configure(event):
            canvas.itemconfig(inner_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            delta = int(-1 * (event.delta / 120)) if event.delta else (1 if event.num == 5 else -1)
            canvas.yview_scroll(delta, "units")
        canvas.bind("<Enter>", lambda e: (
            canvas.bind_all("<MouseWheel>", _on_mousewheel),
            canvas.bind_all("<Button-4>", _on_mousewheel),
            canvas.bind_all("<Button-5>", _on_mousewheel),
        ))
        canvas.bind("<Leave>", lambda e: (
            canvas.unbind_all("<MouseWheel>"),
            canvas.unbind_all("<Button-4>"),
            canvas.unbind_all("<Button-5>"),
        ))
        return inner

    # ---------- connection tab ----------

    def _build_connection_tab(self):
        frame = self._make_scrollable(self.conn_tab)

        ttk.Label(frame, text="Connection", style="SectionTitle.TLabel").pack(anchor="w", pady=(0, 12))

        mode_frame = ttk.LabelFrame(frame, text="  Connection Mode  ", style="Card.TLabelframe", padding=14)
        mode_frame.pack(fill="x", pady=(0, 14))
        self.mode_var = tk.StringVar(value="odbc")
        ttk.Radiobutton(mode_frame, text="ODBC  —  recommended, full structured checks via Db2 for i / QSYS2",
                        variable=self.mode_var, value="odbc", style="TRadiobutton",
                        command=self._on_mode_change).pack(anchor="w", pady=2)
        ttk.Radiobutton(mode_frame, text="SSH  —  generic command execution, supplementary checks",
                        variable=self.mode_var, value="ssh", style="TRadiobutton",
                        command=self._on_mode_change).pack(anchor="w", pady=2)

        # --- ODBC / SSH fields live in a stable container so re-packing one
        # doesn't reorder the buttons/note below it (pack_forget + pack moves
        # a widget to the end of its manager's stacking order otherwise) ---
        self.fields_container = ttk.Frame(frame)
        self.fields_container.pack(fill="x")

        self.odbc_frame = ttk.LabelFrame(self.fields_container, text="  ODBC Connection Details  ",
                                          style="Card.TLabelframe", padding=(16, 14, 16, 20))

        self.odbc_host = self._labeled_entry(self.odbc_frame, "Host / System name", 0)
        self.odbc_port = self._labeled_entry(self.odbc_frame, "Port", 1, default="8471")
        self.odbc_user = self._labeled_entry(self.odbc_frame, "User profile", 2)
        self.odbc_pass = self._labeled_entry(self.odbc_frame, "Password", 3, show="*")
        self.odbc_driver = self._labeled_entry(self.odbc_frame, "ODBC Driver name", 4,
                                                default="IBM i Access ODBC Driver")
        self.odbc_timeout = self._labeled_entry(self.odbc_frame, "Query timeout (seconds)", 5,
                                                  default="45")
        self.odbc_ssl = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.odbc_frame, text="Use SSL", variable=self.odbc_ssl, style="TCheckbutton").grid(
            row=6, column=1, sticky="w", pady=(8, 0))

        # --- SSH fields ---
        self.ssh_frame = ttk.LabelFrame(self.fields_container, text="  SSH Connection Details  ",
                                         style="Card.TLabelframe", padding=(16, 14, 16, 20))

        self.ssh_host = self._labeled_entry(self.ssh_frame, "Host", 0)
        self.ssh_port = self._labeled_entry(self.ssh_frame, "Port", 1, default="22")
        self.ssh_user = self._labeled_entry(self.ssh_frame, "User profile", 2)
        self.ssh_pass = self._labeled_entry(self.ssh_frame, "Password", 3, show="*")

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=(2, 0))
        self.connect_btn = ttk.Button(btn_frame, text="Connect", style="Accent.TButton", command=self._connect)
        self.connect_btn.pack(side="left")
        self.disconnect_btn = ttk.Button(btn_frame, text="Disconnect", style="Ghost.TButton",
                                          command=self._disconnect, state="disabled")
        self.disconnect_btn.pack(side="left", padx=8)

        note = ("Credentials are used only for this session to authenticate to the target IBM i "
                "and are never written to disk. Ensure you are explicitly authorized to test this system.")
        ttk.Label(frame, text=note, style="Muted.TLabel", wraplength=920, justify="left").pack(
            anchor="w", pady=(18, 0))

        self._on_mode_change()

    def _labeled_entry(self, parent, label, row, default="", show=None):
        ttk.Label(parent, text=label, width=20, style="CardMuted.TLabel").grid(
            row=row, column=0, sticky="w", pady=6)
        var = tk.StringVar(value=default)
        entry = ttk.Entry(parent, textvariable=var, width=42, show=show or "", style="TEntry")
        entry.grid(row=row, column=1, sticky="w", pady=6, padx=(6, 0))
        return var

    def _on_mode_change(self):
        if self.mode_var.get() == "odbc":
            self.ssh_frame.pack_forget()
            self.odbc_frame.pack(in_=self.fields_container, fill="x", pady=(0, 14))
        else:
            self.odbc_frame.pack_forget()
            self.ssh_frame.pack(in_=self.fields_container, fill="x", pady=(0, 14))

    def _connect(self):
        mode = self.mode_var.get()
        self.connect_btn.config(state="disabled")
        self.conn_status_var.set("Connecting…")
        self.conn_status_var_color("#A15C07")
        self.update_idletasks()

        try:
            if mode == "odbc":
                port = int(self.odbc_port.get() or 8471)
                timeout = int(self.odbc_timeout.get() or 45)
                connector = IBMiODBCConnector(
                    host=self.odbc_host.get().strip(),
                    user=self.odbc_user.get().strip(),
                    password=self.odbc_pass.get(),
                    port=port,
                    driver=self.odbc_driver.get().strip() or None,
                    ssl=self.odbc_ssl.get(),
                    query_timeout=timeout,
                )
                connector.connect()
                self.odbc_connector = connector
            else:
                port = int(self.ssh_port.get() or 22)
                connector = IBMiSSHConnector(
                    host=self.ssh_host.get().strip(),
                    user=self.ssh_user.get().strip(),
                    password=self.ssh_pass.get(),
                    port=port,
                )
                connector.connect()
                self.ssh_connector = connector

            self.connected_mode = mode
            self.conn_status_var.set(f"Connected ({mode.upper()})")
            self.conn_status_var_color("#3ED598")
            self.disconnect_btn.config(state="normal")
            self.run_btn.config(state="normal")
        except ConnectionError_ as e:
            messagebox.showerror("Connection failed", str(e))
            self.conn_status_var.set("Not connected")
            self.conn_status_var_color("#B42318")
        except Exception as e:
            messagebox.showerror("Connection failed", f"Unexpected error: {e}")
            self.conn_status_var.set("Not connected")
            self.conn_status_var_color("#B42318")
        finally:
            self.connect_btn.config(state="normal")

    def _disconnect(self):
        if self.odbc_connector:
            self.odbc_connector.close()
            self.odbc_connector = None
        if self.ssh_connector:
            self.ssh_connector.close()
            self.ssh_connector = None
        self.connected_mode = None
        self.conn_status_var.set("Not connected")
        self.conn_status_var_color("#B42318")
        self.disconnect_btn.config(state="disabled")
        self.run_btn.config(state="disabled")

    # ---------- checks tab ----------

    def _build_checks_tab(self):
        frame = self._make_scrollable(self.checks_tab)

        ttk.Label(frame, text="Run Checks & Results", style="SectionTitle.TLabel").pack(anchor="w", pady=(0, 12))

        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 10))

        self.checks_path_var = tk.StringVar(value=self.checks_path)
        ttk.Label(top, text="Checks file", style="Muted.TLabel").pack(side="left")
        ttk.Entry(top, textvariable=self.checks_path_var, width=56, state="readonly", style="TEntry").pack(
            side="left", padx=8)
        ttk.Button(top, text="Load different file…", style="Ghost.TButton",
                   command=self._browse_checks_file).pack(side="left")

        self.run_btn = ttk.Button(top, text="Run All Checks", style="Accent.TButton",
                                   command=self._run_checks_threaded, state="disabled")
        self.run_btn.pack(side="right")

        self.progress = ttk.Progressbar(frame, mode="determinate", style="Teal.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 6))
        self.progress_label = ttk.Label(frame, text="Idle.", style="Muted.TLabel")
        self.progress_label.pack(anchor="w", pady=(0, 12))

        # Summary counters — card with left accent bar, matching report design
        self.summary_frame = ttk.Frame(frame)
        self.summary_frame.pack(fill="x", pady=(0, 14))
        self.summary_vars = {}
        for status in ["PASS", "FAIL", "REVIEW", "ERROR"]:
            self._build_stat_card(self.summary_frame, status)

        # Results table + detail pane (paned window) — FIXED height, not
        # expand=True, so it can never consume all remaining space and
        # squeeze the export buttons below it out of existence.
        paned = ttk.PanedWindow(frame, orient="vertical", height=420)
        paned.pack(fill="x", expand=False, pady=(0, 14))
        paned.pack_propagate(False)

        table_frame = ttk.Frame(paned, style="Card.TFrame")
        detail_frame = ttk.LabelFrame(paned, text="  Detail  ", style="Card.TLabelframe", padding=10)
        paned.add(table_frame, weight=3)
        paned.add(detail_frame, weight=2)

        columns = ("id", "cis_ref", "name", "category", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse", height=8)
        headings = {"id": "ID", "cis_ref": "CIS Ref", "name": "Control", "category": "Category", "status": "Result"}
        widths = {"id": 64, "cis_ref": 70, "name": 320, "category": 220, "status": 90}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True, side="left")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        for status, color in STATUS_COLORS.items():
            self.tree.tag_configure(status, foreground=color)

        self.detail_text = tk.Text(detail_frame, wrap="word", height=8, font=(FONT_MONO, 9),
                                    bg=PAPER, fg=TEXT, relief="flat", bd=0, padx=10, pady=10,
                                    insertbackground=TEXT)
        self.detail_text.pack(fill="both", expand=True)
        self.detail_text.configure(state="disabled")

        export_bar = ttk.Frame(frame)
        export_bar.pack(fill="x", pady=(10, 4))
        ttk.Button(export_bar, text="Export HTML Report", style="Accent.TButton",
                   command=self._export_html).pack(side="left")
        ttk.Button(export_bar, text="Export CSV", style="Ghost.TButton",
                   command=self._export_csv).pack(side="left", padx=8)

        self.autosave_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.autosave_var, style="Muted.TLabel", wraplength=900,
                  justify="left").pack(anchor="w", pady=(0, 20))

    def _build_stat_card(self, parent, status):
        outer = tk.Frame(parent, bg=LINE)
        outer.pack(side="left", padx=(0, 10), fill="y")
        accent = tk.Frame(outer, bg=STATUS_COLORS[status], width=3)
        accent.pack(side="left", fill="y")
        card = tk.Frame(outer, bg=CARD, padx=16, pady=10)
        card.pack(side="left", fill="both")
        v = tk.StringVar(value="0")
        self.summary_vars[status] = v
        tk.Label(card, textvariable=v, font=(FONT_SERIF, 20), bg=CARD, fg=INK).pack(anchor="w")
        tk.Label(card, text=status.title(), font=(FONT_SANS, 8), bg=CARD, fg=MUTED).pack(anchor="w")

    def _browse_checks_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if path:
            self.checks_path = path
            self.checks_path_var.set(path)
            self._load_checks_quiet()

    def _load_checks_quiet(self):
        try:
            self.checks = load_checks(self.checks_path)
            self.progress_label.config(text=f"Loaded {len(self.checks)} checks from {os.path.basename(self.checks_path)}.")
        except Exception as e:
            self.checks = []
            messagebox.showwarning("Checks file", f"Could not load checks file:\n{e}")

    def _run_checks_threaded(self):
        if not self.checks:
            messagebox.showwarning("No checks", "No checks loaded.")
            return
        if not self.connected_mode:
            messagebox.showwarning("Not connected", "Connect to a target first.")
            return
        self.run_btn.config(state="disabled")
        self.progress["value"] = 0
        self.progress["maximum"] = len(self.checks)
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.results = []
        for status in self.summary_vars:
            self.summary_vars[status].set("0")

        thread = threading.Thread(target=self._run_checks_worker, daemon=True)
        thread.start()

    def _run_checks_worker(self):
        def progress_callback(i, total, name):
            self.after(0, lambda: self._update_progress(i, total, name))

        results = run_all_checks(
            self.checks,
            mode=self.connected_mode,
            odbc_connector=self.odbc_connector,
            ssh_connector=self.ssh_connector,
            progress_callback=progress_callback,
        )
        self.after(0, lambda: self._on_checks_complete(results))

    def _update_progress(self, i, total, name):
        self.progress["value"] = i
        self.progress_label.config(text=f"Running check {i}/{total}: {name}")

    def _on_checks_complete(self, results):
        self.results = results
        counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0, "ERROR": 0}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
            self.tree.insert("", "end", iid=r.check_id, values=(r.check_id, r.cis_ref, r.name, r.category, r.status),
                              tags=(r.status,))
        for status, v in self.summary_vars.items():
            v.set(str(counts.get(status, 0)))
        self.progress_label.config(text=f"Done. {len(results)} checks completed.")
        self.run_btn.config(state="normal")
        self._autosave_results()

    def _autosave_results(self):
        """Safety net: silently save a copy of every completed run to a local
        'reports' folder next to the tool, so results are never trapped in
        the GUI only - regardless of whether the Export buttons get clicked."""
        try:
            reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
            os.makedirs(reports_dir, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            html_path = os.path.join(reports_dir, f"autosave_{stamp}.html")
            csv_path = os.path.join(reports_dir, f"autosave_{stamp}.csv")
            meta = self._build_meta()
            generate_html(self.results, meta, html_path)
            generate_csv(self.results, csv_path)
            self.autosave_var.set(f"Auto-saved a local copy to: {reports_dir}")
        except Exception as e:
            self.autosave_var.set(f"Auto-save failed ({e}) - use Export buttons above to save manually.")

    def _on_row_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        check_id = sel[0]
        result = next((r for r in self.results if r.check_id == check_id), None)
        if not result:
            return
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        detail = (
            f"Control:      {result.name}\n"
            f"Category:     {result.category}\n"
            f"CIS Ref:      {result.cis_ref or '(not mapped - edit checks_config.json)'}\n"
            f"Result:       {result.status}\n"
            f"Timestamp:    {result.timestamp}\n"
            f"\nCommand / Query:\n{result.command_used}\n"
            f"\nEvidence / Output:\n{result.evidence}\n"
            f"\nRecommendation:\n{result.recommendation}\n"
        )
        self.detail_text.insert("1.0", detail)
        self.detail_text.configure(state="disabled")

    # ---------- export ----------

    def _export_html(self):
        if not self.results:
            messagebox.showwarning("No results", "Run checks before exporting.")
            return
        default_name = f"as400_audit_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        path = filedialog.asksaveasfilename(defaultextension=".html", initialfile=default_name,
                                             filetypes=[("HTML files", "*.html")])
        if not path:
            return
        meta = self._build_meta()
        generate_html(self.results, meta, path)
        messagebox.showinfo("Exported", f"HTML report saved to:\n{path}")

    def _export_csv(self):
        if not self.results:
            messagebox.showwarning("No results", "Run checks before exporting.")
            return
        default_name = f"as400_audit_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile=default_name,
                                             filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        generate_csv(self.results, path)
        messagebox.showinfo("Exported", f"CSV saved to:\n{path}")

    def _build_meta(self):
        target = (self.odbc_host.get() if self.connected_mode == "odbc" else self.ssh_host.get()) or ""
        return {
            "target": target,
            "mode": self.connected_mode or "",
            "tester": os.environ.get("USERNAME") or os.environ.get("USER") or "",
            "engagement": "",
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def main():
    # On Windows, make the process DPI-aware before any Tk window is created.
    # Without this, Windows can apply its own bitmap scaling on top of a
    # display-scaling setting (e.g. 125%/150%, common on laptops), causing
    # the app to request more physical pixels than actually fit on screen -
    # which is exactly the kind of thing that can push widgets like the
    # export buttons out of the visible window with no way to reveal them
    # by resizing. This does nothing (safely) on non-Windows platforms.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
