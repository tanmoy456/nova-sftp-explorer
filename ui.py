import io
import json
import os
import stat
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageTk

from preview import (
    decode_bytes,
    should_preview_as_image,
    should_preview_as_text,
)
from sftp_client import RemoteEntry, SFTPClient

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

TEXT_PREVIEW_LIMIT = 256 * 1024
HEX_PREVIEW_LIMIT = 32 * 1024
IMAGE_PREVIEW_LIMIT = 8 * 1024 * 1024
SETTINGS_FILE = "nova_state.json"


class NovaSFTPExplorer(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Nova SFTP Explorer")
        self.geometry("1400x900")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.client = SFTPClient()
        self.cwd = "/"
        self.home_dir = "/"

        self.listing_rows: list[RemoteEntry] = []
        self.visible_rows: list[RemoteEntry] = []

        self.preview_token = 0
        self.preview_file_path = None
        self.preview_file_size = 0
        self.preview_offset = 0
        self.preview_page_size = TEXT_PREVIEW_LIMIT
        self.image_original = None
        self.image_tk = None
        self.image_zoom = 1.0
        self.image_fit_mode = True
        self.image_canvas_item = None
        self.nav_back_stack = []
        self.nav_forward_stack = []

        self.transfer_counter = 0
        self.transfer_rows = {}

        self.state_path = Path(__file__).with_name(SETTINGS_FILE)
        self.profiles = []
        self.bookmarks = []
        self.ui_prefs = {}
        self.profile_options = {}
        self._load_state()

        self._setup_layout()
        self._setup_toolbar()
        self._setup_body()
        self._setup_status_bar()
        self._refresh_profile_menu()
        self._apply_ui_prefs()

    def _setup_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

    def _setup_toolbar(self):
        self.toolbar = ctk.CTkFrame(self, corner_radius=0, fg_color="#0f1720")
        self.toolbar.grid(row=0, column=0, sticky="ew")
        self.toolbar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.toolbar,
            text="NOVA SFTP EXPLORER",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(10, 8), sticky="w")

        connect_row = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        connect_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        connect_row.grid_columnconfigure(10, weight=1)

        self.ent_host = ctk.CTkEntry(connect_row, width=210, placeholder_text="Host")
        self.ent_port = ctk.CTkEntry(connect_row, width=70, placeholder_text="22")
        self.ent_user = ctk.CTkEntry(connect_row, width=170, placeholder_text="Username")
        self.ent_pass = ctk.CTkEntry(connect_row, width=170, placeholder_text="Password", show="*")

        self.ent_host.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.ent_port.grid(row=0, column=1, padx=(0, 8), sticky="ew")
        self.ent_user.grid(row=0, column=2, padx=(0, 8), sticky="ew")
        self.ent_pass.grid(row=0, column=3, padx=(0, 8), sticky="ew")

        self.btn_connect = ctk.CTkButton(connect_row, text="Connect", width=110, command=self._connect_async, fg_color="#1c9f66", hover_color="#157a4e")
        self.btn_disconnect = ctk.CTkButton(connect_row, text="Disconnect", width=110, state="disabled", command=self.disconnect, fg_color="#b33939", hover_color="#8f2d2d")
        self.btn_connect.grid(row=0, column=4, padx=(0, 8))
        self.btn_disconnect.grid(row=0, column=5, padx=(0, 8))

        self.profile_var = ctk.StringVar(value="Profiles")
        self.profile_menu = ctk.CTkOptionMenu(connect_row, width=150, variable=self.profile_var, values=["Profiles"], command=self._on_profile_selected)
        self.btn_save_profile = ctk.CTkButton(connect_row, text="Save Profile", width=105, command=self.save_profile)
        self.profile_menu.grid(row=0, column=6, padx=(0, 8))
        self.btn_save_profile.grid(row=0, column=7, padx=(0, 8))

        path_row = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        path_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
        path_row.grid_columnconfigure(0, weight=1)

        self.path_entry = ctk.CTkEntry(path_row, placeholder_text="Remote path")
        self.path_entry.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.btn_back = ctk.CTkButton(path_row, text="<", width=44, state="disabled", command=self.go_back)
        self.btn_forward = ctk.CTkButton(path_row, text=">", width=44, state="disabled", command=self.go_forward)
        self.btn_up = ctk.CTkButton(path_row, text="Up", width=74, state="disabled", command=self.go_up)
        self.btn_refresh = ctk.CTkButton(path_row, text="Refresh", width=88, state="disabled", command=self.refresh_listing)
        self.btn_go = ctk.CTkButton(path_row, text="Go", width=70, state="disabled", command=self.go_to_path)

        self.btn_back.grid(row=0, column=1, padx=(0, 8))
        self.btn_forward.grid(row=0, column=2, padx=(0, 8))
        self.btn_up.grid(row=0, column=3, padx=(0, 8))
        self.btn_refresh.grid(row=0, column=4, padx=(0, 8))
        self.btn_go.grid(row=0, column=5)

        for w in (self.ent_host, self.ent_port, self.ent_user, self.ent_pass):
            w.bind("<Return>", self._on_connect_enter)
        self.path_entry.bind("<Return>", self._on_path_enter)

    def _setup_body(self):
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

        self.splitter = tk.PanedWindow(self.body, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=8, background="#0f1720", bd=0)
        self.splitter.grid(row=0, column=0, sticky="nsew")

        self.browser_panel = ctk.CTkFrame(self.splitter, corner_radius=14, fg_color="#131d27")
        self.preview_panel = ctk.CTkFrame(self.splitter, corner_radius=14, fg_color="#131d27")
        self.browser_panel.grid_rowconfigure(3, weight=1)
        self.browser_panel.grid_columnconfigure(0, weight=1)

        self.splitter.add(self.browser_panel, minsize=540, stretch="always")
        self.splitter.add(self.preview_panel, minsize=420, stretch="always")
        self.after(120, self._restore_splitter_position)

        header = ctk.CTkFrame(self.browser_panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header, text="Remote Browser", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w", padx=(2, 8))

        self.search_entry = ctk.CTkEntry(header, placeholder_text="Filter files...")
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", self._on_filter_change)

        self.show_hidden_var = ctk.BooleanVar(value=False)
        self.chk_show_hidden = ctk.CTkCheckBox(
            header,
            text="Show hidden",
            variable=self.show_hidden_var,
            command=self._on_filter_change,
        )
        self.chk_show_hidden.grid(row=0, column=2, padx=(0, 8))

        self.btn_upload = ctk.CTkButton(header, text="Upload", width=80, state="disabled", command=self.start_upload)
        self.btn_download = ctk.CTkButton(header, text="Download", width=92, state="disabled", command=self.start_download)
        self.btn_upload.grid(row=0, column=3, padx=(0, 6))
        self.btn_download.grid(row=0, column=4)

        self.breadcrumb_frame = ctk.CTkFrame(self.browser_panel, fg_color="transparent")
        self.breadcrumb_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 2))

        self._setup_file_table()
        self._setup_preview_tabs()

    def _setup_file_table(self):
        table_holder = ctk.CTkFrame(self.browser_panel, fg_color="transparent")
        table_holder.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
        table_holder.grid_rowconfigure(0, weight=1)
        table_holder.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("SFTP.Treeview", background="#17212b", foreground="#e6edf6", fieldbackground="#17212b", borderwidth=0, rowheight=30)
        style.map("SFTP.Treeview", background=[("selected", "#245f91")])
        style.configure("SFTP.Treeview.Heading", background="#0f1720", foreground="#e6edf6", relief="flat", borderwidth=0, font=("SF Pro Text", 12, "bold"))
        style.map(
            "SFTP.Treeview.Heading",
            background=[("active", "#0f1720"), ("pressed", "#0f1720")],
            foreground=[("active", "#e6edf6"), ("pressed", "#e6edf6")],
        )

        self.columns = ("name", "type", "size", "modified")
        self.file_table = ttk.Treeview(table_holder, columns=self.columns, show="headings", style="SFTP.Treeview")

        self.file_table.heading("name", text="Name")
        self.file_table.heading("type", text="Type")
        self.file_table.heading("size", text="Size")
        self.file_table.heading("modified", text="Modified")

        self.file_table.column("name", width=360, anchor="w")
        self.file_table.column("type", width=90, anchor="center")
        self.file_table.column("size", width=120, anchor="e")
        self.file_table.column("modified", width=180, anchor="center")

        y_scroll = ttk.Scrollbar(table_holder, orient="vertical", command=self.file_table.yview)
        x_scroll = ttk.Scrollbar(table_holder, orient="horizontal", command=self.file_table.xview)
        self.file_table.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.file_table.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        self.file_table.bind("<<TreeviewSelect>>", self._on_file_select)
        self.file_table.bind("<Double-1>", self._on_file_open)
        self.file_table.bind("<Return>", self._on_file_open)
        self.file_table.bind("<KP_Enter>", self._on_file_open)

    def _setup_preview_tabs(self):
        self.preview_panel.grid_rowconfigure(1, weight=1)
        self.preview_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.preview_panel, text="Instant Remote Preview", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 0))

        self.preview_tabs = ctk.CTkTabview(self.preview_panel)
        self.preview_tabs.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

        self.tab_text = self.preview_tabs.add("Text")
        self.tab_image = self.preview_tabs.add("Image")
        self.tab_hex = self.preview_tabs.add("Hex")
        self.tab_meta = self.preview_tabs.add("Metadata")
        self.tab_transfers = self.preview_tabs.add("Transfers")

        self.text_controls = ctk.CTkFrame(self.tab_text, fg_color="transparent")
        self.text_controls.pack(fill="x", padx=8, pady=(8, 0))
        self.btn_prev_page = ctk.CTkButton(self.text_controls, text="Prev", width=70, state="disabled", command=self.preview_prev_page)
        self.btn_next_page = ctk.CTkButton(self.text_controls, text="Next", width=70, state="disabled", command=self.preview_next_page)
        self.page_label = ctk.CTkLabel(self.text_controls, text="Page 1")
        self.btn_prev_page.pack(side="left")
        self.page_label.pack(side="left", padx=10)
        self.btn_next_page.pack(side="left")

        self.text_preview = ctk.CTkTextbox(self.tab_text, font=("JetBrains Mono", 13))
        self.text_preview.pack(fill="both", expand=True, padx=8, pady=8)

        self.image_controls = ctk.CTkFrame(self.tab_image, fg_color="transparent")
        self.image_controls.pack(fill="x", padx=8, pady=(8, 0))
        self.btn_image_fit = ctk.CTkButton(self.image_controls, text="Fit", width=68, command=self._image_fit_to_window)
        self.btn_image_zoom_out = ctk.CTkButton(self.image_controls, text="-", width=40, command=lambda: self._image_zoom_by(0.9))
        self.btn_image_zoom_in = ctk.CTkButton(self.image_controls, text="+", width=40, command=lambda: self._image_zoom_by(1.1))
        self.image_zoom_var = ctk.StringVar(value="100%")
        self.image_zoom_menu = ctk.CTkOptionMenu(
            self.image_controls,
            width=90,
            values=["10%", "20%", "50%", "80%", "100%"],
            variable=self.image_zoom_var,
            command=self._on_image_zoom_selected,
        )
        self.image_info_label = ctk.CTkLabel(self.image_controls, text="No image loaded")
        self.btn_image_fit.pack(side="left", padx=(0, 6))
        self.btn_image_zoom_out.pack(side="left", padx=(0, 6))
        self.btn_image_zoom_in.pack(side="left", padx=(0, 10))
        self.image_zoom_menu.pack(side="left", padx=(0, 10))
        self.image_info_label.pack(side="left")

        self.image_viewer = ctk.CTkFrame(self.tab_image, fg_color="transparent")
        self.image_viewer.pack(fill="both", expand=True, padx=8, pady=8)
        self.image_viewer.grid_rowconfigure(0, weight=1)
        self.image_viewer.grid_columnconfigure(0, weight=1)

        self.image_canvas = tk.Canvas(self.image_viewer, background="#171c23", highlightthickness=0, bd=0)
        self.image_x_scroll = ttk.Scrollbar(self.image_viewer, orient="horizontal", command=self.image_canvas.xview)
        self.image_y_scroll = ttk.Scrollbar(self.image_viewer, orient="vertical", command=self.image_canvas.yview)
        self.image_canvas.configure(xscrollcommand=self.image_x_scroll.set, yscrollcommand=self.image_y_scroll.set)

        self.image_canvas.grid(row=0, column=0, sticky="nsew")
        self.image_y_scroll.grid(row=0, column=1, sticky="ns")
        self.image_x_scroll.grid(row=1, column=0, sticky="ew")

        self.image_canvas.bind("<Configure>", self._on_image_canvas_resize)
        self.image_canvas.bind("<MouseWheel>", self._on_image_mousewheel)
        self.image_canvas.bind("<Button-4>", self._on_image_mousewheel)
        self.image_canvas.bind("<Button-5>", self._on_image_mousewheel)
        self.image_canvas.bind("<ButtonPress-1>", self._on_image_pan_start)
        self.image_canvas.bind("<B1-Motion>", self._on_image_pan_move)
        self.image_canvas.create_text(20, 20, anchor="nw", text="Select an image file to preview", fill="#c9d2df", tags=("placeholder",))

        self.hex_preview = ctk.CTkTextbox(self.tab_hex, font=("JetBrains Mono", 12))
        self.hex_preview.pack(fill="both", expand=True, padx=8, pady=8)

        self.meta_preview = ctk.CTkTextbox(self.tab_meta, font=("JetBrains Mono", 12))
        self.meta_preview.pack(fill="both", expand=True, padx=8, pady=8)

        self._setup_transfer_table()

    def _setup_transfer_table(self):
        holder = ctk.CTkFrame(self.tab_transfers, fg_color="transparent")
        holder.pack(fill="both", expand=True, padx=8, pady=8)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)

        cols = ("direction", "file", "progress", "status")
        self.transfer_table = ttk.Treeview(holder, columns=cols, show="headings")
        for col, text, width in (
            ("direction", "Direction", 110),
            ("file", "File", 330),
            ("progress", "Progress", 90),
            ("status", "Status", 110),
        ):
            self.transfer_table.heading(col, text=text)
            self.transfer_table.column(col, width=width, anchor="w")

        y_scroll = ttk.Scrollbar(holder, orient="vertical", command=self.transfer_table.yview)
        self.transfer_table.configure(yscrollcommand=y_scroll.set)
        self.transfer_table.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")

    def _setup_status_bar(self):
        self.status_var = ctk.StringVar(value="Disconnected")
        self.status = ctk.CTkLabel(self, textvariable=self.status_var, anchor="w")
        self.status.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))

    def _set_status(self, text: str):
        self.status_var.set(text)

    # State
    def _load_state(self):
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        self.profiles = data.get("profiles", [])
        self.bookmarks = data.get("bookmarks", [])
        self.ui_prefs = data.get("ui", {})

    def _save_state(self):
        payload = {"profiles": self.profiles, "bookmarks": self.bookmarks, "ui": self.ui_prefs}
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _apply_ui_prefs(self):
        for col, width in self.ui_prefs.get("columns", {}).items():
            if col in self.columns:
                self.file_table.column(col, width=int(width))
        last_profile = self.ui_prefs.get("last_profile")
        if last_profile and last_profile in self.profile_options:
            self.profile_var.set(last_profile)

    def _on_close(self):
        self._persist_ui_prefs()
        self.client.disconnect()
        self.destroy()

    def _persist_ui_prefs(self):
        splitter_x = None
        try:
            splitter_x = self.splitter.sash_coord(0)[0]
        except Exception:
            pass
        self.ui_prefs["splitter_x"] = splitter_x
        self.ui_prefs["columns"] = {col: self.file_table.column(col, "width") for col in self.columns}
        self.ui_prefs["last_profile"] = self.profile_var.get() if self.profile_var.get() in self.profile_options else ""
        self._save_state()

    # Menus
    def _refresh_profile_menu(self):
        self.profile_options = {p["name"]: p for p in self.profiles if p.get("name")}
        self.profile_menu.configure(values=["Profiles"] + sorted(self.profile_options))
        self.profile_var.set("Profiles")

    def _on_profile_selected(self, value):
        profile = self.profile_options.get(value)
        if not profile:
            return
        self.ent_host.delete(0, "end")
        self.ent_host.insert(0, profile.get("host", ""))
        self.ent_port.delete(0, "end")
        self.ent_port.insert(0, str(profile.get("port", "22")))
        self.ent_user.delete(0, "end")
        self.ent_user.insert(0, profile.get("username", ""))
        if profile.get("last_path"):
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, profile["last_path"])
        self.ui_prefs["last_profile"] = value

    def save_profile(self):
        host = self.ent_host.get().strip()
        user = self.ent_user.get().strip()
        if not host or not user:
            messagebox.showerror("Missing Fields", "Host and username are required for a profile.")
            return
        dialog = ctk.CTkInputDialog(text="Profile name", title="Save Profile")
        name = (dialog.get_input() or "").strip()
        if not name:
            return
        profile = {
            "name": name,
            "host": host,
            "port": self.ent_port.get().strip() or "22",
            "username": user,
            "last_path": self.path_entry.get().strip() or "/",
        }
        self.profiles = [p for p in self.profiles if p.get("name") != name]
        self.profiles.append(profile)
        self._refresh_profile_menu()
        self.profile_var.set(name)
        self.ui_prefs["last_profile"] = name
        self._save_state()

    # Connection
    def _on_connect_enter(self, _event):
        if self.btn_connect.cget("state") == "normal":
            self._connect_async()
        return "break"

    def _on_path_enter(self, _event):
        if self.btn_go.cget("state") == "normal":
            self.go_to_path()
        return "break"

    def _connect_async(self):
        self.btn_connect.configure(state="disabled", text="Connecting...")
        self._set_status("Connecting...")
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        host = self.ent_host.get().strip()
        user = self.ent_user.get().strip()
        password = self.ent_pass.get()
        port_raw = self.ent_port.get().strip() or "22"
        try:
            port = int(port_raw)
            cwd = self.client.connect(host, port, user, password)
            home = self.client.normalize("~")
        except Exception as exc:
            self.after(0, lambda: self._on_connect_failed(str(exc)))
            return

        self.cwd = cwd
        self.home_dir = home
        requested_path = self.path_entry.get().strip()
        self.after(0, lambda: self._on_connected(requested_path))

    def _on_connect_failed(self, error):
        messagebox.showerror("Connection Error", error)
        self.btn_connect.configure(state="normal", text="Connect")
        self._set_status("Disconnected")

    def _on_connected(self, requested_path: str):
        self.btn_connect.configure(state="disabled", text="Connected")
        for btn in (self.btn_disconnect, self.btn_up, self.btn_refresh, self.btn_go, self.btn_upload, self.btn_download):
            btn.configure(state="normal")
        self._update_nav_buttons()
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, self.cwd)
        if requested_path and requested_path != ".":
            self._navigate(requested_path, track_history=False)
        else:
            self.refresh_listing()

    def disconnect(self):
        self.client.disconnect()
        self.cwd = "/"
        self.home_dir = "/"
        self.listing_rows = []
        self.visible_rows = []
        self._clear_table()
        self._render_breadcrumbs("/")
        self._reset_preview()
        self.btn_connect.configure(state="normal", text="Connect")
        for btn in (self.btn_disconnect, self.btn_up, self.btn_refresh, self.btn_go, self.btn_upload, self.btn_download):
            btn.configure(state="disabled")
        self.nav_back_stack = []
        self.nav_forward_stack = []
        self._update_nav_buttons()
        self._set_status("Disconnected")

    # Navigation
    def go_up(self):
        if not self.client.connected or self.cwd == "/":
            return
        parent = os.path.dirname(self.cwd.rstrip("/")) or "/"
        self._navigate(parent)

    def go_back(self):
        if not self.client.connected or not self.nav_back_stack:
            return
        target = self.nav_back_stack.pop()
        if self.cwd and (not self.nav_forward_stack or self.nav_forward_stack[-1] != self.cwd):
            self.nav_forward_stack.append(self.cwd)
        self._update_nav_buttons()
        self._navigate(target, track_history=False)

    def go_forward(self):
        if not self.client.connected or not self.nav_forward_stack:
            return
        target = self.nav_forward_stack.pop()
        if self.cwd and (not self.nav_back_stack or self.nav_back_stack[-1] != self.cwd):
            self.nav_back_stack.append(self.cwd)
        self._update_nav_buttons()
        self._navigate(target, track_history=False)

    def go_to_path(self):
        if not self.client.connected:
            return
        target = self.path_entry.get().strip()
        if target:
            self._navigate(target)

    def _navigate(self, target: str, track_history: bool = True):
        if not self.client.connected:
            return
        resolved = SFTPClient.resolve_target_path(target, self.cwd, self.home_dir)
        self._set_status(f"Navigating to {resolved} ...")
        previous_path = self.cwd
        threading.Thread(target=self._navigate_worker, args=(resolved, previous_path, track_history), daemon=True).start()

    def _navigate_worker(self, target, previous_path, track_history):
        try:
            normalized = self.client.normalize(target)
            attrs = self.client.stat(normalized)
            if not stat.S_ISDIR(attrs.st_mode):
                raise ValueError(f"{normalized} is not a directory.")
            rows = self.client.listdir(normalized)
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("Navigation Error", str(exc)))
            return
        self.after(0, lambda: self._render_listing(normalized, rows, previous_path, track_history))

    def refresh_listing(self):
        if not self.client.connected:
            return
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            rows = self.client.listdir(self.cwd)
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("Browse Error", str(exc)))
            return
        self.after(0, lambda: self._render_listing(self.cwd, rows))

    def _render_listing(self, path, rows, previous_path=None, track_history=False):
        if track_history and previous_path and previous_path != path:
            if not self.nav_back_stack or self.nav_back_stack[-1] != previous_path:
                self.nav_back_stack.append(previous_path)
            self.nav_forward_stack.clear()
        self.cwd = path
        self.listing_rows = rows
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, path)
        self._render_breadcrumbs(path)
        self._apply_filter()
        self._update_nav_buttons()
        self._set_status(f"Loaded {len(rows)} items in {path}")

    def _update_nav_buttons(self):
        self.btn_back.configure(state="normal" if self.nav_back_stack else "disabled")
        self.btn_forward.configure(state="normal" if self.nav_forward_stack else "disabled")

    def _render_breadcrumbs(self, path):
        for child in self.breadcrumb_frame.winfo_children():
            child.destroy()
        parts = [p for p in (path or "/").split("/") if p]
        chain = ["/"]
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else f"/{part}"
            chain.append(current)
        for idx, crumb in enumerate(chain):
            label = "/" if crumb == "/" else os.path.basename(crumb)
            ctk.CTkButton(self.breadcrumb_frame, text=label, width=36, height=24, fg_color="#1b3a56", hover_color="#24557f", command=lambda p=crumb: self._navigate(p)).pack(side="left", padx=(0, 4))
            if idx < len(chain) - 1:
                ctk.CTkLabel(self.breadcrumb_frame, text=">", text_color="#95a4b8").pack(side="left", padx=(0, 4))

    # Filter
    def _on_filter_change(self, _event=None):
        self._apply_filter()

    def _apply_filter(self):
        query = self.search_entry.get().strip().lower()
        show_hidden = self.show_hidden_var.get()

        rows = self.listing_rows
        if not show_hidden:
            rows = [r for r in rows if not r.name.startswith(".")]

        if query:
            rows = [r for r in rows if query in r.name.lower()]

        self.visible_rows = rows
        self._clear_table()
        for idx, row in enumerate(self.visible_rows):
            self.file_table.insert("", "end", iid=str(idx), values=(row.name, row.file_type, row.size_human, row.modified))

    def _clear_table(self):
        for item in self.file_table.get_children():
            self.file_table.delete(item)

    def _selected_row(self):
        sel = self.file_table.selection()
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(self.visible_rows):
            return self.visible_rows[idx]
        return None

    def _selected_row_from_event(self, event):
        if event is not None and hasattr(event, "x") and hasattr(event, "y"):
            row_id = self.file_table.identify_row(event.y)
            if row_id:
                self.file_table.selection_set(row_id)
                self.file_table.focus(row_id)
        return self._selected_row()

    def _on_file_open(self, event=None):
        row = self._selected_row_from_event(event)
        if row and row.is_dir:
            self._navigate(row.full_path)

    # Preview
    def _on_file_select(self, _event):
        row = self._selected_row()
        if not row or row.is_dir:
            return
        self.preview_token += 1
        token = self.preview_token
        self.preview_file_path = row.full_path
        self.preview_file_size = row.st_size
        self.preview_offset = 0
        threading.Thread(target=self._preview_worker, args=(token, row, 0), daemon=True).start()

    def _preview_worker(self, token: int, row: RemoteEntry, offset: int):
        path = row.full_path
        ext = os.path.splitext(path.lower())[1]
        metadata = self._build_metadata(row)
        try:
            if should_preview_as_image(ext, row.st_size, IMAGE_PREVIEW_LIMIT):
                self._preview_image(token, path, metadata)
                return

            sample = self.client.read_head(path, 4096)
            if should_preview_as_text(ext, sample):
                self._preview_text(token, row, metadata, offset)
                return

            self._preview_hex(token, path, metadata)
        except Exception as exc:
            self.after(0, lambda: self._set_status(f"Preview failed: {exc}"))

    def _preview_text(self, token, row, metadata, offset):
        data = self.client.read_range(row.full_path, offset, self.preview_page_size)
        decoded = decode_bytes(data)
        end_offset = offset + len(data)
        has_more = end_offset < row.st_size
        text = decoded.text
        if has_more:
            text += "\n\n[Page truncated. Use Next for more.]"

        def update():
            if token != self.preview_token:
                return
            self.preview_file_path = row.full_path
            self.preview_file_size = row.st_size
            self.preview_offset = offset
            self.text_preview.delete("1.0", "end")
            self.text_preview.insert("1.0", text)
            self.meta_preview.delete("1.0", "end")
            self.meta_preview.insert("1.0", metadata + f"Encoding: {decoded.encoding}\n")
            self.preview_tabs.set("Text")
            self._update_text_paging_controls()
            self._set_status("Text preview ready")

        self.after(0, update)

    def _preview_image(self, token, path, metadata):
        raw = self.client.read_head(path, IMAGE_PREVIEW_LIMIT)
        image = Image.open(io.BytesIO(raw))
        image.load()

        def update():
            if token != self.preview_token:
                return
            self.preview_file_path = None
            self.preview_file_size = 0
            self.preview_offset = 0
            self.image_original = image
            self.image_fit_mode = True
            self.image_zoom = 1.0
            self._render_image_canvas()
            self.meta_preview.delete("1.0", "end")
            self.meta_preview.insert("1.0", metadata)
            self.preview_tabs.set("Image")
            self._update_text_paging_controls()

        self.after(0, update)

    def _preview_hex(self, token, path, metadata):
        data = self.client.read_head(path, HEX_PREVIEW_LIMIT)
        lines = []
        for offset in range(0, len(data), 16):
            chunk = data[offset : offset + 16]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
            lines.append(f"{offset:08x}  {hex_part:<47}  {ascii_part}")
        output = "\n".join(lines) + "\n\n[Binary preview limited to first 32 KB.]"

        def update():
            if token != self.preview_token:
                return
            self.preview_file_path = None
            self.preview_file_size = 0
            self.preview_offset = 0
            self.hex_preview.delete("1.0", "end")
            self.hex_preview.insert("1.0", output)
            self.meta_preview.delete("1.0", "end")
            self.meta_preview.insert("1.0", metadata)
            self.preview_tabs.set("Hex")
            self._update_text_paging_controls()

        self.after(0, update)

    def _build_metadata(self, row: RemoteEntry):
        return (
            f"Path: {row.full_path}\n"
            f"Type: {'Directory' if row.is_dir else 'File'}\n"
            f"Size: {row.st_size} bytes ({row.size_human})\n"
            f"Permissions: {stat.filemode(row.st_mode)}\n"
            f"Modified: {row.modified}\n"
        )

    def _row_by_path(self, path):
        for row in self.listing_rows:
            if row.full_path == path:
                return row
        return None

    def _on_image_canvas_resize(self, _event):
        if self.image_fit_mode:
            self._render_image_canvas()

    def _on_image_mousewheel(self, event):
        if self.image_original is None:
            return "break"
        delta = 0
        if hasattr(event, "delta") and event.delta:
            delta = event.delta
        elif getattr(event, "num", None) == 4:
            delta = 120
        elif getattr(event, "num", None) == 5:
            delta = -120
        if delta == 0:
            return "break"
        factor = 1.1 if delta > 0 else 0.9
        self._image_zoom_by(factor)
        return "break"

    def _on_image_pan_start(self, event):
        self.image_canvas.scan_mark(event.x, event.y)

    def _on_image_pan_move(self, event):
        self.image_canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_image_zoom_selected(self, value):
        if self.image_original is None:
            return
        try:
            pct = int(value.rstrip("%"))
        except ValueError:
            return
        self.image_fit_mode = False
        self.image_zoom = max(0.05, min(8.0, pct / 100.0))
        self._render_image_canvas()

    def _image_fit_to_window(self):
        if self.image_original is None:
            return
        self.image_fit_mode = True
        self._render_image_canvas()

    def _image_actual_size(self):
        if self.image_original is None:
            return
        self.image_fit_mode = False
        self.image_zoom = 1.0
        self.image_zoom_var.set("100%")
        self._render_image_canvas()

    def _image_zoom_by(self, factor):
        if self.image_original is None:
            return
        self.image_fit_mode = False
        self.image_zoom = max(0.05, min(8.0, self.image_zoom * factor))
        self._render_image_canvas()

    def _render_image_canvas(self):
        self.image_canvas.delete("placeholder")
        if self.image_original is None:
            self.image_canvas.delete("all")
            self.image_canvas_item = None
            self.image_canvas.create_text(20, 20, anchor="nw", text="Select an image file to preview", fill="#c9d2df", tags=("placeholder",))
            self.image_info_label.configure(text="No image loaded")
            self.image_canvas.configure(scrollregion=(0, 0, 1, 1))
            return

        original_w, original_h = self.image_original.size
        canvas_w = max(self.image_canvas.winfo_width(), 1)
        canvas_h = max(self.image_canvas.winfo_height(), 1)

        if self.image_fit_mode:
            fit_zoom = min(canvas_w / original_w, canvas_h / original_h, 1.0)
            self.image_zoom = max(fit_zoom, 0.01)

        draw_w = max(1, int(original_w * self.image_zoom))
        draw_h = max(1, int(original_h * self.image_zoom))
        rendered = self.image_original.resize((draw_w, draw_h), Image.Resampling.LANCZOS)
        self.image_tk = ImageTk.PhotoImage(rendered)

        x = max((canvas_w - draw_w) // 2, 0)
        y = max((canvas_h - draw_h) // 2, 0)
        if self.image_canvas_item is None:
            self.image_canvas_item = self.image_canvas.create_image(x, y, anchor="nw", image=self.image_tk)
        else:
            self.image_canvas.itemconfigure(self.image_canvas_item, image=self.image_tk)
            self.image_canvas.coords(self.image_canvas_item, x, y)

        self.image_canvas.configure(scrollregion=(0, 0, max(draw_w, canvas_w), max(draw_h, canvas_h)))
        zoom_pct = int(self.image_zoom * 100)
        mode = "Fit" if self.image_fit_mode else "Manual"
        self.image_info_label.configure(text=f"{original_w}x{original_h} | {zoom_pct}% | {mode}")

    def preview_prev_page(self):
        if not self.preview_file_path or self.preview_offset <= 0:
            return
        row = self._row_by_path(self.preview_file_path)
        if not row:
            return
        offset = max(0, self.preview_offset - self.preview_page_size)
        self.preview_token += 1
        threading.Thread(target=self._preview_worker, args=(self.preview_token, row, offset), daemon=True).start()

    def preview_next_page(self):
        if not self.preview_file_path:
            return
        row = self._row_by_path(self.preview_file_path)
        if not row:
            return
        next_offset = self.preview_offset + self.preview_page_size
        if next_offset >= self.preview_file_size:
            return
        self.preview_token += 1
        threading.Thread(target=self._preview_worker, args=(self.preview_token, row, next_offset), daemon=True).start()

    def _update_text_paging_controls(self):
        if not self.preview_file_path or self.preview_file_size <= 0:
            self.btn_prev_page.configure(state="disabled")
            self.btn_next_page.configure(state="disabled")
            self.page_label.configure(text="Page 1")
            return
        page = (self.preview_offset // self.preview_page_size) + 1
        total = ((self.preview_file_size - 1) // self.preview_page_size) + 1
        self.page_label.configure(text=f"Page {page}/{total}")
        self.btn_prev_page.configure(state="normal" if self.preview_offset > 0 else "disabled")
        self.btn_next_page.configure(state="normal" if (self.preview_offset + self.preview_page_size) < self.preview_file_size else "disabled")

    def _reset_preview(self):
        self.preview_token += 1
        self.preview_file_path = None
        self.preview_file_size = 0
        self.preview_offset = 0
        self.text_preview.delete("1.0", "end")
        self.hex_preview.delete("1.0", "end")
        self.meta_preview.delete("1.0", "end")
        self.image_original = None
        self.image_tk = None
        self.image_zoom = 1.0
        self.image_fit_mode = True
        self.image_canvas.delete("all")
        self.image_canvas_item = None
        self.image_zoom_var.set("100%")
        self.image_canvas.create_text(20, 20, anchor="nw", text="Select an image file to preview", fill="#c9d2df", tags=("placeholder",))
        self.image_info_label.configure(text="No image loaded")
        self._update_text_paging_controls()

    # Transfers
    def _new_transfer_row(self, direction: str, file_label: str):
        self.transfer_counter += 1
        transfer_id = f"t{self.transfer_counter}"
        self.transfer_rows[transfer_id] = {"direction": direction, "file": file_label, "progress": "0%", "status": "Queued"}
        self.transfer_table.insert("", "end", iid=transfer_id, values=(direction, file_label, "0%", "Queued"))
        self.preview_tabs.set("Transfers")
        return transfer_id

    def _update_transfer_row(self, transfer_id, progress=None, status=None):
        row = self.transfer_rows.get(transfer_id)
        if not row:
            return
        if progress is not None:
            row["progress"] = progress
        if status is not None:
            row["status"] = status
        self.transfer_table.item(transfer_id, values=(row["direction"], row["file"], row["progress"], row["status"]))

    def start_upload(self):
        if not self.client.connected:
            return
        local_path = filedialog.askopenfilename(title="Select file to upload")
        if not local_path:
            return
        remote_path = SFTPClient.join_remote(self.cwd, os.path.basename(local_path))
        transfer_id = self._new_transfer_row("Upload", os.path.basename(local_path))
        threading.Thread(target=self._upload_worker, args=(transfer_id, local_path, remote_path), daemon=True).start()

    def _upload_worker(self, transfer_id, local_path, remote_path):
        def cb(transferred, total):
            pct = f"{int((transferred / total) * 100) if total else 0}%"
            self.after(0, lambda p=pct: self._update_transfer_row(transfer_id, progress=p, status="Running"))

        try:
            self.after(0, lambda: self._update_transfer_row(transfer_id, status="Running"))
            self.client.put(local_path, remote_path, callback=cb)
            self.after(0, lambda: self._update_transfer_row(transfer_id, progress="100%", status="Done"))
            self.after(0, self.refresh_listing)
        except Exception as exc:
            self.after(0, lambda: self._update_transfer_row(transfer_id, status=f"Error: {exc}"))

    def start_download(self):
        if not self.client.connected:
            return
        row = self._selected_row()
        if not row or row.is_dir:
            messagebox.showwarning("Select file", "Select a remote file to download.")
            return
        local_path = filedialog.asksaveasfilename(initialfile=row.name, title="Save remote file as")
        if not local_path:
            return
        transfer_id = self._new_transfer_row("Download", row.name)
        threading.Thread(target=self._download_worker, args=(transfer_id, row.full_path, local_path), daemon=True).start()

    def _download_worker(self, transfer_id, remote_path, local_path):
        def cb(transferred, total):
            pct = f"{int((transferred / total) * 100) if total else 0}%"
            self.after(0, lambda p=pct: self._update_transfer_row(transfer_id, progress=p, status="Running"))

        try:
            self.after(0, lambda: self._update_transfer_row(transfer_id, status="Running"))
            self.client.get(remote_path, local_path, callback=cb)
            self.after(0, lambda: self._update_transfer_row(transfer_id, progress="100%", status="Done"))
        except Exception as exc:
            self.after(0, lambda: self._update_transfer_row(transfer_id, status=f"Error: {exc}"))

    def _restore_splitter_position(self):
        saved = self.ui_prefs.get("splitter_x")
        if isinstance(saved, int):
            self.splitter.sash_place(0, saved, 0)
        else:
            self.splitter.sash_place(0, 930, 0)
