import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, scrolledtext
import paramiko
import os
import json
import threading
from datetime import datetime
import stat
from PIL import Image, ImageTk
import io
import tempfile
from dotenv import load_dotenv

load_dotenv()

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "last_connection.json")


def load_last_connection():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_last_connection(host, username, key_path):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"host": host, "username": username, "key_path": key_path}, f)
    except Exception:
        pass


class EC2FileManager:
    def __init__(self, root):
        self.root = root
        self.root.title("EC2 File Manager - ROSCODE TECH")
        self.root.geometry("1000x700")
        self._set_window_icon()

        # Connection variables
        self.ssh_client = None
        self.sftp_client = None
        self.connected = False
        self.current_remote_path = "/"

        # Connection defaults: last used values take priority over .env
        last = load_last_connection()
        self.default_host = last.get("host") or os.environ.get("EC2_HOST", "")
        self.default_username = last.get("username") or os.environ.get("EC2_USERNAME", "ubuntu")
        self.default_key_path = last.get("key_path") or os.environ.get("EC2_KEY_PATH", "")

        self.setup_ui()

    def _set_window_icon(self):
        ico = os.path.join(ASSETS_DIR, "icon.ico")
        png = os.path.join(ASSETS_DIR, "icon_256.png")
        try:
            if os.path.exists(ico):
                self.root.iconbitmap(ico)
            elif os.path.exists(png):
                img = ImageTk.PhotoImage(Image.open(png))
                self.root.iconphoto(True, img)
        except Exception:
            pass

    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)

        # Connection frame
        conn_frame = ttk.LabelFrame(main_frame, text="Connection", padding="5")
        conn_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        conn_frame.columnconfigure(1, weight=1)

        # Connection fields
        ttk.Label(conn_frame, text="Host:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.host_var = tk.StringVar(value=self.default_host)
        ttk.Entry(conn_frame, textvariable=self.host_var, width=20).grid(row=0, column=1, sticky=(tk.W, tk.E),
                                                                         padx=(0, 10))

        ttk.Label(conn_frame, text="Username:").grid(row=0, column=2, sticky=tk.W, padx=(10, 5))
        self.username_var = tk.StringVar(value=self.default_username)
        ttk.Entry(conn_frame, textvariable=self.username_var, width=15).grid(row=0, column=3, sticky=(tk.W, tk.E),
                                                                             padx=(0, 10))

        ttk.Label(conn_frame, text="Key File:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
        self.key_path_var = tk.StringVar(value=self.default_key_path)
        ttk.Entry(conn_frame, textvariable=self.key_path_var).grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        ttk.Button(conn_frame, text="Browse", command=self.browse_key_file).grid(row=1, column=2, padx=(5, 10))

        # Connection buttons
        button_frame = ttk.Frame(conn_frame)
        button_frame.grid(row=1, column=3, sticky=tk.E)

        self.connect_btn = ttk.Button(button_frame, text="Connect", command=self.connect_to_server)
        self.connect_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.disconnect_btn = ttk.Button(button_frame, text="Disconnect", command=self.disconnect_from_server,
                                         state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT)

        # Status label
        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(conn_frame, textvariable=self.status_var, foreground="red")
        self.status_label.grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(5, 0))

        # Navigation frame
        nav_frame = ttk.Frame(main_frame)
        nav_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        nav_frame.columnconfigure(1, weight=1)

        ttk.Button(nav_frame, text="Home", command=self.go_home).grid(row=0, column=0, padx=(0, 5))
        ttk.Button(nav_frame, text="Up", command=self.go_up).grid(row=0, column=1, padx=(0, 5))

        self.path_var = tk.StringVar(value=self.current_remote_path)
        ttk.Label(nav_frame, text="Path:").grid(row=0, column=2, padx=(10, 5))
        self.path_entry = ttk.Entry(nav_frame, textvariable=self.path_var)
        self.path_entry.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=(0, 5))
        self.path_entry.bind('<Return>', self.navigate_to_path)

        ttk.Button(nav_frame, text="Refresh", command=self.refresh_file_list).grid(row=0, column=4, padx=(5, 0))

        # File management frame
        file_frame = ttk.LabelFrame(main_frame, text="Remote Files", padding="5")
        file_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        file_frame.columnconfigure(0, weight=1)
        file_frame.rowconfigure(0, weight=1)

        # File tree
        self.tree = ttk.Treeview(file_frame, columns=('Size', 'Modified', 'Permissions'), show='tree headings')
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure columns
        self.tree.heading('#0', text='Name')
        self.tree.heading('Size', text='Size')
        self.tree.heading('Modified', text='Modified')
        self.tree.heading('Permissions', text='Permissions')

        self.tree.column('#0', width=300)
        self.tree.column('Size', width=100)
        self.tree.column('Modified', width=150)
        self.tree.column('Permissions', width=100)

        # Scrollbars
        v_scrollbar = ttk.Scrollbar(file_frame, orient=tk.VERTICAL, command=self.tree.yview)
        v_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.tree.configure(yscrollcommand=v_scrollbar.set)

        h_scrollbar = ttk.Scrollbar(file_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        h_scrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.tree.configure(xscrollcommand=h_scrollbar.set)

        # Terminal frame
        terminal_frame = ttk.LabelFrame(main_frame, text="Terminal", padding="5")
        terminal_frame.grid(row=2, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(10, 0))
        terminal_frame.columnconfigure(0, weight=1)
        terminal_frame.rowconfigure(0, weight=1)

        # Terminal output
        self.terminal_output = scrolledtext.ScrolledText(
            terminal_frame,
            wrap=tk.WORD,
            font=('Consolas', 10),
            bg='black',
            fg='white',
            insertbackground='white',
            height=15
        )
        self.terminal_output.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Terminal input frame
        terminal_input_frame = ttk.Frame(terminal_frame)
        terminal_input_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        terminal_input_frame.columnconfigure(1, weight=1)

        # Terminal prompt and input
        self.prompt_var = tk.StringVar(value="$")
        ttk.Label(terminal_input_frame, textvariable=self.prompt_var, foreground="green").grid(row=0, column=0,
                                                                                               sticky=tk.W, padx=(0, 5))

        self.terminal_input = ttk.Entry(terminal_input_frame, font=('Consolas', 10))
        self.terminal_input.grid(row=0, column=1, sticky=(tk.W, tk.E))
        self.terminal_input.bind('<Return>', self.execute_command)
        self.terminal_input.bind('<Up>', self.command_history_up)
        self.terminal_input.bind('<Down>', self.command_history_down)

        # Terminal control buttons
        terminal_controls = ttk.Frame(terminal_frame)
        terminal_controls.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(5, 0))

        ttk.Button(terminal_controls, text="Clear", command=self.clear_terminal).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(terminal_controls, text="Kill Process", command=self.kill_current_process).pack(side=tk.LEFT,
                                                                                                   padx=(0, 5))

        # Terminal variables
        self.command_history = []
        self.history_index = -1
        self.current_channel = None
        self.current_working_dir = "~"

        # Context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="View/Edit", command=self.view_file)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Download", command=self.download_file)
        self.context_menu.add_command(label="Rename", command=self.rename_item)
        self.context_menu.add_command(label="Delete", command=self.delete_item)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Properties", command=self.show_properties)

        # Bind events
        self.tree.bind('<Double-1>', self.on_double_click)
        self.tree.bind('<Button-3>', self.show_context_menu)

        # Control buttons frame
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))

        # File operations buttons
        ttk.Button(control_frame, text="Upload File", command=self.upload_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(control_frame, text="Create Folder", command=self.create_folder).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(control_frame, text="View/Edit", command=self.view_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(control_frame, text="Download", command=self.download_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(control_frame, text="Rename", command=self.rename_item).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(control_frame, text="Delete", command=self.delete_item).pack(side=tk.LEFT, padx=(0, 5))

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))

        # Progress label
        self.progress_label_var = tk.StringVar()
        self.progress_label = ttk.Label(main_frame, textvariable=self.progress_label_var)
        self.progress_label.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))

    def browse_key_file(self):
        filename = filedialog.askopenfilename(
            title="Select SSH Key File",
            filetypes=[("PEM files", "*.pem"), ("All files", "*.*")]
        )
        if filename:
            self.key_path_var.set(filename)

    def connect_to_server(self):
        def connect():
            try:
                self.status_var.set("Connecting...")
                self.status_label.config(foreground="orange")

                # Create SSH client
                self.ssh_client = paramiko.SSHClient()
                self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                # Connect using key file
                key_path = self.key_path_var.get().strip()
                if not os.path.exists(key_path):
                    raise Exception("Key file not found")

                self.ssh_client.connect(
                    hostname=self.host_var.get().strip(),
                    username=self.username_var.get().strip(),
                    key_filename=key_path.strip(),
                    timeout=10
                )

                # Create SFTP client
                self.sftp_client = self.ssh_client.open_sftp()

                self.connected = True
                self.status_var.set("Connected")
                self.status_label.config(foreground="green")

                # Persist successful connection details for next launch
                save_last_connection(
                    self.host_var.get().strip(),
                    self.username_var.get().strip(),
                    key_path
                )

                # Update button states
                self.connect_btn.config(state=tk.DISABLED)
                self.disconnect_btn.config(state=tk.NORMAL)

                # Load initial directory
                self.refresh_file_list()

                # Initialize terminal
                self.initialize_terminal()

            except Exception as e:
                messagebox.showerror("Connection Error", f"Failed to connect: {str(e)}")
                self.status_var.set("Disconnected")
                self.status_label.config(foreground="red")

        threading.Thread(target=connect, daemon=True).start()

    def disconnect_from_server(self):
        try:
            if self.sftp_client:
                self.sftp_client.close()
            if self.ssh_client:
                self.ssh_client.close()
        except:
            pass

        self.connected = False
        self.ssh_client = None
        self.sftp_client = None

        self.status_var.set("Disconnected")
        self.status_label.config(foreground="red")

        # Update button states
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)

        # Clear file list
        self.tree.delete(*self.tree.get_children())

        # Clear terminal
        self.clear_terminal()
        self.current_channel = None

    def refresh_file_list(self):
        if not self.connected:
            return

        def load_files():
            try:
                self.progress_label_var.set("Loading files...")
                self.progress_var.set(0)

                # Clear existing items
                self.tree.delete(*self.tree.get_children())

                # Get file list
                files = self.sftp_client.listdir_attr(self.current_remote_path)

                total_files = len(files)
                for i, file_attr in enumerate(files):
                    # Calculate progress
                    progress = (i + 1) / total_files * 100
                    self.progress_var.set(progress)

                    # Determine file type and icon
                    if stat.S_ISDIR(file_attr.st_mode):
                        icon = "📁"
                        size = "<DIR>"
                    else:
                        icon = "📄"
                        size = self.format_size(file_attr.st_size)

                    # Format modified time
                    modified = datetime.fromtimestamp(file_attr.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

                    # Format permissions
                    permissions = stat.filemode(file_attr.st_mode)

                    # Insert into tree
                    self.tree.insert('', 'end',
                                     text=f"{icon} {file_attr.filename}",
                                     values=(size, modified, permissions))

                self.progress_var.set(0)
                self.progress_label_var.set("Ready")

            except Exception as e:
                messagebox.showerror("Error", f"Failed to load files: {str(e)}")
                self.progress_var.set(0)
                self.progress_label_var.set("Error")

        threading.Thread(target=load_files, daemon=True).start()

    def format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    def on_double_click(self, event):
        selection = self.tree.selection()
        if not selection:
            return

        item = self.tree.item(selection[0])
        filename = item['text'].split(' ', 1)[1]  # Remove icon

        if item['values'][0] == "<DIR>":
            self.navigate_to_folder(filename)
        else:
            self.view_file()

    def navigate_to_folder(self, folder_name):
        if folder_name == "..":
            self.go_up()
        else:
            new_path = os.path.join(self.current_remote_path, folder_name).replace('\\', '/')
            self.current_remote_path = new_path
            self.path_var.set(new_path)
            self.refresh_file_list()

    def go_home(self):
        self.current_remote_path = "/"
        self.path_var.set(self.current_remote_path)
        self.refresh_file_list()

    def go_up(self):
        if self.current_remote_path != "/":
            self.current_remote_path = os.path.dirname(self.current_remote_path)
            if not self.current_remote_path:
                self.current_remote_path = "/"
            self.path_var.set(self.current_remote_path)
            self.refresh_file_list()

    def navigate_to_path(self, event):
        new_path = self.path_var.get()
        if new_path != self.current_remote_path:
            self.current_remote_path = new_path
            self.refresh_file_list()

    def upload_file(self):
        if not self.connected:
            messagebox.showwarning("Warning", "Not connected to server")
            return

        local_file = filedialog.askopenfilename(title="Select file to upload")
        if not local_file:
            return

        def upload():
            try:
                filename = os.path.basename(local_file)
                remote_path = os.path.join(self.current_remote_path, filename).replace('\\', '/')

                self.progress_label_var.set(f"Uploading {filename}...")

                # Upload with progress callback
                file_size = os.path.getsize(local_file)
                uploaded = 0

                def progress_callback(transferred, total):
                    nonlocal uploaded
                    uploaded = transferred
                    progress = (transferred / total) * 100
                    self.progress_var.set(progress)
                    self.root.update_idletasks()

                self.sftp_client.put(local_file, remote_path, callback=progress_callback)

                self.progress_var.set(0)
                self.progress_label_var.set("Upload complete")
                self.refresh_file_list()

            except Exception as e:
                messagebox.showerror("Upload Error", f"Failed to upload file: {str(e)}")
                self.progress_var.set(0)
                self.progress_label_var.set("Upload failed")

        threading.Thread(target=upload, daemon=True).start()

    def download_file(self):
        if not self.connected:
            messagebox.showwarning("Warning", "Not connected to server")
            return

        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a file to download")
            return

        item = self.tree.item(selection[0])
        filename = item['text'].split(' ', 1)[1]  # Remove icon

        # Check if it's a directory
        if item['values'][0] == "<DIR>":
            messagebox.showwarning("Warning", "Cannot download directories")
            return

        # Choose local save location
        local_file = filedialog.asksaveasfilename(
            title="Save file as",
            initialvalue=filename
        )
        if not local_file:
            return

        def download():
            try:
                remote_path = os.path.join(self.current_remote_path, filename).replace('\\', '/')

                self.progress_label_var.set(f"Downloading {filename}...")

                # Download with progress callback
                def progress_callback(transferred, total):
                    progress = (transferred / total) * 100
                    self.progress_var.set(progress)
                    self.root.update_idletasks()

                self.sftp_client.get(remote_path, local_file, callback=progress_callback)

                self.progress_var.set(0)
                self.progress_label_var.set("Download complete")

            except Exception as e:
                messagebox.showerror("Download Error", f"Failed to download file: {str(e)}")
                self.progress_var.set(0)
                self.progress_label_var.set("Download failed")

        threading.Thread(target=download, daemon=True).start()

    def create_folder(self):
        if not self.connected:
            messagebox.showwarning("Warning", "Not connected to server")
            return

        folder_name = simpledialog.askstring("Create Folder", "Enter folder name:")
        if not folder_name:
            return

        try:
            remote_path = os.path.join(self.current_remote_path, folder_name).replace('\\', '/')
            self.sftp_client.mkdir(remote_path)
            self.refresh_file_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create folder: {str(e)}")

    def rename_item(self):
        if not self.connected:
            messagebox.showwarning("Warning", "Not connected to server")
            return

        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select an item to rename")
            return

        item = self.tree.item(selection[0])
        old_name = item['text'].split(' ', 1)[1]  # Remove icon

        new_name = simpledialog.askstring("Rename", f"Rename '{old_name}' to:", initialvalue=old_name)
        if not new_name or new_name == old_name:
            return

        try:
            old_path = os.path.join(self.current_remote_path, old_name).replace('\\', '/')
            new_path = os.path.join(self.current_remote_path, new_name).replace('\\', '/')

            self.sftp_client.rename(old_path, new_path)
            self.refresh_file_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to rename item: {str(e)}")

    def delete_item(self):
        if not self.connected:
            messagebox.showwarning("Warning", "Not connected to server")
            return

        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select an item to delete")
            return

        item = self.tree.item(selection[0])
        filename = item['text'].split(' ', 1)[1]  # Remove icon
        is_dir = item['values'][0] == "<DIR>"

        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete '{filename}'?"):
            return

        try:
            remote_path = os.path.join(self.current_remote_path, filename).replace('\\', '/')

            if is_dir:
                self.sftp_client.rmdir(remote_path)
            else:
                self.sftp_client.remove(remote_path)

            self.refresh_file_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete item: {str(e)}")

    def show_context_menu(self, event):
        try:
            self.tree.selection_set(self.tree.identify_row(event.y))
            self.context_menu.post(event.x_root, event.y_root)
        except:
            pass

    def show_properties(self):
        selection = self.tree.selection()
        if not selection:
            return

        item = self.tree.item(selection[0])
        filename = item['text'].split(' ', 1)[1]  # Remove icon

        try:
            remote_path = os.path.join(self.current_remote_path, filename).replace('\\', '/')
            file_attr = self.sftp_client.stat(remote_path)

            props = f"Name: {filename}\n"
            props += f"Path: {remote_path}\n"
            props += f"Size: {self.format_size(file_attr.st_size)}\n"
            props += f"Modified: {datetime.fromtimestamp(file_attr.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}\n"
            props += f"Permissions: {stat.filemode(file_attr.st_mode)}\n"
            props += f"UID: {file_attr.st_uid}\n"
            props += f"GID: {file_attr.st_gid}\n"

            messagebox.showinfo("Properties", props)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to get properties: {str(e)}")

    def view_file(self):
        if not self.connected:
            messagebox.showwarning("Warning", "Not connected to server")
            return

        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a file to view")
            return

        item = self.tree.item(selection[0])
        filename = item['text'].split(' ', 1)[1]  # Remove icon

        # Check if it's a directory
        if item['values'][0] == "<DIR>":
            messagebox.showwarning("Warning", "Cannot view directories")
            return

        # Get file size
        file_size = self.get_file_size_from_display(item['values'][0])

        # Check if file is too large (> 10MB)
        if file_size > 10 * 1024 * 1024:
            if not messagebox.askyesno("Large File",
                                       f"File is {self.format_size(file_size)}. "
                                       "This may take a while to load. Continue?"):
                return

        def load_and_view():
            try:
                remote_path = os.path.join(self.current_remote_path, filename).replace('\\', '/')

                self.progress_label_var.set(f"Loading {filename}...")
                self.progress_var.set(50)

                # Determine file type and viewing method
                file_ext = os.path.splitext(filename)[1].lower()

                if self.is_image_file(file_ext):
                    self.view_image_file(remote_path, filename)
                else:
                    # Open everything as text — user can always edit like a text file
                    self.view_text_file(remote_path, filename)

                self.progress_var.set(0)
                self.progress_label_var.set("Ready")

            except Exception as e:
                messagebox.showerror("View Error", f"Failed to view file: {str(e)}")
                self.progress_var.set(0)
                self.progress_label_var.set("Error")

        threading.Thread(target=load_and_view, daemon=True).start()

    def get_file_size_from_display(self, size_str):
        """Convert display size back to bytes"""
        if size_str == "<DIR>":
            return 0

        try:
            parts = size_str.split()
            if len(parts) == 2:
                value = float(parts[0])
                unit = parts[1]
                multipliers = {'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4}
                return int(value * multipliers.get(unit, 1))
        except:
            pass
        return 0

    def is_text_file(self, filename):
        text_extensions = {
            '.txt', '.py', '.js', '.html', '.htm', '.css', '.json', '.xml', '.md',
            '.yml', '.yaml', '.ini', '.cfg', '.conf', '.log', '.sql', '.sh', '.bash',
            '.c', '.cpp', '.h', '.hpp', '.java', '.php', '.rb', '.go', '.rs', '.kt',
            '.ts', '.jsx', '.tsx', '.vue', '.svelte', '.r', '.m', '.pl', '.ps1',
            '.dockerfile', '.gitignore', '.env', '.properties', '.toml', '.csv',
            '.example', '.sample', '.template', '.local', '.dist'
        }
        name = os.path.basename(filename).lower()

        # Check every dot-separated part as an extension (.env.example, .env.local, etc.)
        parts = name.split('.')
        for part in parts[1:]:
            if '.' + part in text_extensions:
                return True

        # Pure dot-files with no extension (.env, .gitignore, .bashrc, etc.)
        if name.startswith('.') and name.count('.') == 1:
            return True

        # Known extensionless text files
        if name in {'makefile', 'dockerfile', 'procfile', 'vagrantfile', 'gemfile',
                    'rakefile', 'cmakelists', 'requirements', 'pipfile'}:
            return True

        return False

    def is_image_file(self, ext):
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.ico'}
        return ext in image_extensions

    def view_text_file(self, remote_path, filename):
        try:
            # Read file content in binary mode to handle any encoding
            with self.sftp_client.open(remote_path, 'rb') as remote_file:
                raw = remote_file.read()

            # Try to decode: UTF-8 first, then latin-1 (which never fails)
            for encoding in ('utf-8-sig', 'utf-8', 'latin-1'):
                try:
                    content = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue

            # Create viewer window
            viewer = tk.Toplevel(self.root)
            viewer.title(f"Text Editor - {filename}")
            viewer.geometry("800x600")

            # Create menu
            menubar = tk.Menu(viewer)
            viewer.config(menu=menubar)

            file_menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label="File", menu=file_menu)
            file_menu.add_command(label="Save", command=lambda: self.save_text_content(content, filename))
            file_menu.add_command(label="Save Changes",
                                  command=lambda: self.save_text_changes(viewer, remote_path, text_widget))
            file_menu.add_separator()
            file_menu.add_command(label="Close", command=viewer.destroy)

            edit_menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label="Edit", menu=edit_menu)
            edit_menu.add_command(label="Find", command=lambda: self.show_find_dialog(text_widget))

            # Create text widget with scrollbar
            text_frame = ttk.Frame(viewer)
            text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            text_widget = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, font=('Consolas', 10))
            text_widget.pack(fill=tk.BOTH, expand=True)

            # Insert content
            text_widget.insert(tk.END, content)

            # Add syntax highlighting for common file types
            self.add_syntax_highlighting(text_widget, filename)

            # Status bar
            status_frame = ttk.Frame(viewer)
            status_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

            ttk.Label(status_frame, text=f"File: {filename}").pack(side=tk.LEFT)
            ttk.Label(status_frame, text=f"Size: {len(raw)} bytes").pack(side=tk.RIGHT)

        except Exception as e:
            messagebox.showerror("View Error", f"Failed to open file: {str(e)}")

    def view_image_file(self, remote_path, filename):
        try:
            # Download image to temporary file
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                self.sftp_client.get(remote_path, temp_file.name)
                temp_path = temp_file.name

            # Open and display image
            image = Image.open(temp_path)

            # Create viewer window
            viewer = tk.Toplevel(self.root)
            viewer.title(f"Image Viewer - {filename}")

            # Calculate window size (max 800x600)
            img_width, img_height = image.size
            max_width, max_height = 800, 600

            if img_width > max_width or img_height > max_height:
                ratio = min(max_width / img_width, max_height / img_height)
                new_width = int(img_width * ratio)
                new_height = int(img_height * ratio)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image)

            # Set window size
            viewer.geometry(f"{image.width + 20}x{image.height + 60}")

            # Create menu
            menubar = tk.Menu(viewer)
            viewer.config(menu=menubar)

            file_menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label="File", menu=file_menu)
            file_menu.add_command(label="Save As", command=lambda: self.save_image(temp_path, filename))
            file_menu.add_command(label="Close", command=viewer.destroy)

            # Display image
            image_frame = ttk.Frame(viewer)
            image_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            image_label = ttk.Label(image_frame, image=photo)
            image_label.pack()

            # Keep a reference to prevent garbage collection
            image_label.image = photo

            # Status bar
            status_frame = ttk.Frame(viewer)
            status_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

            ttk.Label(status_frame, text=f"File: {filename}").pack(side=tk.LEFT)
            ttk.Label(status_frame, text=f"Size: {img_width}x{img_height}").pack(side=tk.RIGHT)

            # Clean up temp file when window closes
            def cleanup():
                try:
                    os.unlink(temp_path)
                except:
                    pass
                viewer.destroy()

            viewer.protocol("WM_DELETE_WINDOW", cleanup)

        except Exception as e:
            messagebox.showerror("Image Error", f"Failed to display image: {str(e)}")

    def view_binary_file(self, remote_path, filename):
        try:
            # Read first 1KB of file for hex view
            with self.sftp_client.open(remote_path, 'rb') as remote_file:
                content = remote_file.read(1024)  # Read first 1KB

            # Create viewer window
            viewer = tk.Toplevel(self.root)
            viewer.title(f"Hex Viewer - {filename}")
            viewer.geometry("800x600")

            # Create menu
            menubar = tk.Menu(viewer)
            viewer.config(menu=menubar)

            file_menu = tk.Menu(menubar, tearoff=0)
            menubar.add_cascade(label="File", menu=file_menu)
            file_menu.add_command(label="Close", command=viewer.destroy)

            # Create text widget for hex display
            hex_frame = ttk.Frame(viewer)
            hex_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            hex_widget = scrolledtext.ScrolledText(hex_frame, wrap=tk.NONE, font=('Consolas', 10))
            hex_widget.pack(fill=tk.BOTH, expand=True)

            # Format as hex
            hex_content = self.format_hex_content(content)
            hex_widget.insert(tk.END, hex_content)
            hex_widget.config(state=tk.DISABLED)

            # Status bar
            status_frame = ttk.Frame(viewer)
            status_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

            ttk.Label(status_frame, text=f"File: {filename}").pack(side=tk.LEFT)
            ttk.Label(status_frame, text="Showing first 1KB (hex view)").pack(side=tk.RIGHT)

        except Exception as e:
            messagebox.showerror("View Error", f"Failed to view file: {str(e)}")

    def format_hex_content(self, content):
        hex_lines = []
        for i in range(0, len(content), 16):
            chunk = content[i:i + 16]
            hex_part = ' '.join(f'{b:02x}' for b in chunk)
            ascii_part = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
            hex_lines.append(f'{i:08x}  {hex_part:<48} |{ascii_part}|')
        return '\n'.join(hex_lines)

    def add_syntax_highlighting(self, text_widget, filename):
        # Basic syntax highlighting for Python files
        if filename.endswith('.py'):
            # Python keywords
            keywords = ['def', 'class', 'if', 'elif', 'else', 'for', 'while', 'try', 'except', 'import', 'from',
                        'return']

            for keyword in keywords:
                start = '1.0'
                while True:
                    pos = text_widget.search(f'\\b{keyword}\\b', start, stopindex=tk.END, regexp=True)
                    if not pos:
                        break
                    end = f'{pos}+{len(keyword)}c'
                    text_widget.tag_add('keyword', pos, end)
                    start = end

            text_widget.tag_config('keyword', foreground='blue', font=('Consolas', 10, 'bold'))

    def save_text_content(self, content, filename):
        local_file = filedialog.asksaveasfilename(
            title="Save file as",
            initialvalue=filename,
            defaultextension=".txt"
        )
        if local_file:
            try:
                with open(local_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                messagebox.showinfo("Success", "File saved successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save file: {str(e)}")

    def save_text_changes(self, viewer, remote_path, text_widget):
        try:
            # Get modified content
            content = text_widget.get('1.0', tk.END)[:-1]  # Remove last newline

            # Write back to server
            with self.sftp_client.open(remote_path, 'w') as remote_file:
                remote_file.write(content)

            messagebox.showinfo("Success", "Changes saved to server!")
            self.refresh_file_list()  # Refresh to show updated modification time

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save changes: {str(e)}")

    def save_image(self, temp_path, filename):
        local_file = filedialog.asksaveasfilename(
            title="Save image as",
            initialvalue=filename,
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.gif *.bmp *.tiff *.webp"), ("All files", "*.*")]
        )
        if local_file:
            try:
                import shutil
                shutil.copy2(temp_path, local_file)
                messagebox.showinfo("Success", "Image saved successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save image: {str(e)}")

    def show_find_dialog(self, text_widget):
        find_dialog = tk.Toplevel(self.root)
        find_dialog.title("Find")
        find_dialog.geometry("300x100")
        find_dialog.resizable(False, False)

        ttk.Label(find_dialog, text="Find:").pack(pady=5)

        find_var = tk.StringVar()
        find_entry = ttk.Entry(find_dialog, textvariable=find_var, width=30)
        find_entry.pack(pady=5)
        find_entry.focus()

        def find_text():
            search_term = find_var.get()
            if search_term:
                # Clear previous highlights
                text_widget.tag_remove('found', '1.0', tk.END)

                # Find and highlight all occurrences
                start = '1.0'
                while True:
                    pos = text_widget.search(search_term, start, stopindex=tk.END)
                    if not pos:
                        break
                    end = f'{pos}+{len(search_term)}c'
                    text_widget.tag_add('found', pos, end)
                    start = end

                text_widget.tag_config('found', background='yellow')

                # Scroll to first occurrence
                first_pos = text_widget.search(search_term, '1.0', stopindex=tk.END)
                if first_pos:
                    text_widget.see(first_pos)

        ttk.Button(find_dialog, text="Find All", command=find_text).pack(pady=5)
        find_entry.bind('<Return>', lambda e: find_text())

    def initialize_terminal(self):
        """Initialize the terminal session"""
        try:
            self.terminal_output.insert(tk.END, "Terminal initialized. Connected to EC2 instance.\n")
            self.terminal_output.insert(tk.END, "Type 'help' for available commands.\n\n")
            self.update_prompt()
            self.terminal_output.see(tk.END)
        except Exception as e:
            self.terminal_output.insert(tk.END, f"Terminal initialization error: {str(e)}\n")

    def update_prompt(self):
        """Update the terminal prompt with current directory"""
        try:
            # Get current working directory
            stdin, stdout, stderr = self.ssh_client.exec_command('pwd')
            self.current_working_dir = stdout.read().decode().strip()

            # Get username and hostname
            stdin, stdout, stderr = self.ssh_client.exec_command('whoami')
            username = stdout.read().decode().strip()

            stdin, stdout, stderr = self.ssh_client.exec_command('hostname')
            hostname = stdout.read().decode().strip()

            # Update prompt
            short_dir = self.current_working_dir.replace(f'/home/{username}', '~')
            self.prompt_var.set(f"{username}@{hostname}:{short_dir}$")

        except Exception as e:
            self.prompt_var.set("$")

    def execute_command(self, event):
        """Execute command in terminal"""
        command = self.terminal_input.get().strip()
        if not command:
            return

        # Add to history
        if command not in self.command_history:
            self.command_history.append(command)
        self.history_index = len(self.command_history)

        # Clear input
        self.terminal_input.delete(0, tk.END)

        # Display command in terminal
        self.terminal_output.insert(tk.END, f"{self.prompt_var.get()} {command}\n")
        self.terminal_output.see(tk.END)

        # Handle built-in commands
        if command == 'clear':
            self.clear_terminal()
            return
        elif command == 'help':
            self.show_terminal_help()
            return
        elif command.startswith('cd '):
            self.change_directory(command[3:].strip())
            return
        elif command == 'cd':
            self.change_directory('~')
            return

        # Execute command on server
        def run_command():
            try:
                # For interactive commands, use a shell channel
                if any(cmd in command for cmd in ['vi', 'vim', 'nano', 'less', 'more', 'top', 'htop']):
                    self.terminal_output.insert(tk.END, "Interactive commands not fully supported in this terminal.\n")
                    self.terminal_output.insert(tk.END, "Use basic commands or download files to edit locally.\n\n")
                    return

                # Change to current directory first, then execute command
                full_command = f"cd {self.current_working_dir} && {command}"

                stdin, stdout, stderr = self.ssh_client.exec_command(full_command, timeout=30)

                # Read output
                output = stdout.read().decode('utf-8', errors='replace')
                error = stderr.read().decode('utf-8', errors='replace')

                # Display output
                if output:
                    self.terminal_output.insert(tk.END, output)
                if error:
                    self.terminal_output.insert(tk.END, error)

                # Update prompt (in case directory changed)
                self.update_prompt()

                self.terminal_output.insert(tk.END, "\n")
                self.terminal_output.see(tk.END)

                # Refresh file list if command might have changed files
                if any(cmd in command for cmd in ['mkdir', 'rmdir', 'rm', 'mv', 'cp', 'touch', 'wget', 'curl']):
                    self.refresh_file_list()

            except Exception as e:
                self.terminal_output.insert(tk.END, f"Error executing command: {str(e)}\n\n")
                self.terminal_output.see(tk.END)

        threading.Thread(target=run_command, daemon=True).start()

    def change_directory(self, path):
        """Change current working directory"""
        try:
            # Handle relative paths and special cases
            if path == '~':
                stdin, stdout, stderr = self.ssh_client.exec_command('echo $HOME')
                path = stdout.read().decode().strip()
            elif not path.startswith('/'):
                # Relative path
                path = os.path.join(self.current_working_dir, path).replace('\\', '/')

            # Test if directory exists
            stdin, stdout, stderr = self.ssh_client.exec_command(f'test -d "{path}" && echo "exists"')
            if stdout.read().decode().strip() == "exists":
                self.current_working_dir = path
                self.update_prompt()
                self.terminal_output.insert(tk.END, f"Changed directory to: {path}\n\n")

                # Update file manager to show new directory
                self.current_remote_path = path
                self.path_var.set(path)
                self.refresh_file_list()
            else:
                self.terminal_output.insert(tk.END, f"Directory not found: {path}\n\n")

        except Exception as e:
            self.terminal_output.insert(tk.END, f"Error changing directory: {str(e)}\n\n")

        self.terminal_output.see(tk.END)

    def command_history_up(self, event):
        """Navigate up in command history"""
        if self.command_history and self.history_index > 0:
            self.history_index -= 1
            self.terminal_input.delete(0, tk.END)
            self.terminal_input.insert(0, self.command_history[self.history_index])

    def command_history_down(self, event):
        """Navigate down in command history"""
        if self.command_history:
            if self.history_index < len(self.command_history) - 1:
                self.history_index += 1
                self.terminal_input.delete(0, tk.END)
                self.terminal_input.insert(0, self.command_history[self.history_index])
            else:
                self.history_index = len(self.command_history)
                self.terminal_input.delete(0, tk.END)

    def clear_terminal(self):
        """Clear terminal output"""
        self.terminal_output.delete(1.0, tk.END)
        if self.connected:
            self.terminal_output.insert(tk.END, "Terminal cleared.\n\n")

    def show_terminal_help(self):
        """Show terminal help"""
        help_text = """
Available Commands:
  ls, ll          - List files and directories
  cd <path>       - Change directory
  pwd             - Show current directory
  mkdir <name>    - Create directory
  rmdir <name>    - Remove empty directory
  rm <file>       - Remove file
  cp <src> <dst>  - Copy file
  mv <src> <dst>  - Move/rename file
  cat <file>      - Display file content
  grep <pattern>  - Search in files
  find <path>     - Find files
  ps              - Show running processes
  df -h           - Show disk usage
  free -h         - Show memory usage
  uname -a        - Show system info
  whoami          - Show current user
  clear           - Clear terminal
  help            - Show this help

Navigation:
  Up/Down arrows  - Command history
  Tab             - Auto-completion (limited)

Note: Interactive editors (vi, nano) are not fully supported.
Use the file manager to edit files graphically.

"""
        self.terminal_output.insert(tk.END, help_text)
        self.terminal_output.see(tk.END)

    def kill_current_process(self):
        """Kill current running process (Ctrl+C equivalent)"""
        try:
            if self.current_channel:
                self.current_channel.close()
                self.current_channel = None
            self.terminal_output.insert(tk.END, "\n^C\nProcess interrupted.\n\n")
            self.terminal_output.see(tk.END)
        except:
            pass


def main():
    root = tk.Tk()
    app = EC2FileManager(root)
    root.mainloop()


if __name__ == "__main__":
    main()