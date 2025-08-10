# clipboard_buddy_pro.py
import os, json, csv, time, threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from tkinter.scrolledtext import ScrolledText
import pyperclip, keyboard

APP_NAME = "ClipboardBuddyPro"
DEFAULT_HOTKEY_POPUP = "ctrl+shift+space"   # abre el menú rápido
DEFAULT_HOTKEY_MANAGER = "ctrl+shift+e"     # abre el gestor de grupos/mensajes
VIRTUAL_ALL = "Todos Los mensajes"

# ---------- Persistencia ----------
def appdata_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, APP_NAME)
    os.makedirs(folder, exist_ok=True)
    return folder

SNIPPETS_FILE = os.path.join(appdata_path(), "snippets.json")

DEFAULT_DATA = {
    "General": [
        "¡Gracias por tu compra!",
        "¿Cómo puedo ayudarte?",
        "Te paso el link en un momento."
    ],
    "Ventas": [
        "Promo: membresía $5/mes con cursos, comunidad y calculadoras.",
        "Envío en 24-48 h hábiles.",
        "Stock disponible, ¡aprovechá!"
    ]
}

def load_data():
    # Crea archivo si no existe
    if not os.path.exists(SNIPPETS_FILE):
        with open(SNIPPETS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DATA, f, ensure_ascii=False, indent=2)
    # Lee
    with open(SNIPPETS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Asegura estructura válida
    if not isinstance(data, dict):
        data = DEFAULT_DATA.copy()
    # Nunca persistimos el grupo virtual
    data.pop(VIRTUAL_ALL, None)
    # Normaliza listas de texto
    for g, msgs in list(data.items()):
        if not isinstance(msgs, list):
            data[g] = []
        else:
            data[g] = [str(m) for m in msgs if isinstance(m, (str, int, float))]
    return data

def save_data(data):
    safe = dict(data)
    safe.pop(VIRTUAL_ALL, None)
    with open(SNIPPETS_FILE, "w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=2)

def all_group_names(data):
    names = sorted([g for g in data.keys() if g != VIRTUAL_ALL], key=lambda s: s.lower())
    return [VIRTUAL_ALL] + names

def all_messages_pairs(data):
    """ Devuelve lista de tuplas (grupo, mensaje) para el grupo virtual. """
    pairs = []
    for g, msgs in data.items():
        if g == VIRTUAL_ALL:
            continue
        for m in msgs:
            pairs.append((g, m))
    return pairs

def export_to_csv(data, filepath):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["group", "message"])
        for g, msgs in data.items():
            if g == VIRTUAL_ALL:
                continue
            for m in msgs:
                writer.writerow([g, m])

def import_from_csv(filepath, data, replace=False):
    if replace:
        new_data = {}
    else:
        new_data = dict(data)

    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "group" not in reader.fieldnames or "message" not in reader.fieldnames:
            raise ValueError("El CSV debe tener encabezados: group,message")

        for row in reader:
            g = str(row["group"]).strip()
            m = str(row["message"])
            if not g:
                continue
            lst = new_data.setdefault(g, [])
            if m not in lst:
                lst.append(m)

    new_data.pop(VIRTUAL_ALL, None)
    return new_data

# ---------- Diálogo multilinea para agregar/editar mensajes ----------
class MultilineInputDialog(tk.Toplevel):
    """
    Diálogo modal con caja de texto multilinea (wrap por palabras).
    - Ctrl+Enter: Guardar
    - Esc: Cancelar
    """
    def __init__(self, parent, title="Mensaje", initial_text=""):
        super().__init__(parent)
        self.title(title)
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.result = None

        # Ventana modal centrada relativa al parent
        self.transient(parent)
        self.grab_set()

        # Layout
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        hint = ttk.Label(self, text="Escribe el mensaje tal como lo pegarías. Enter = salto de línea. Ctrl+Enter = Guardar.")
        hint.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))

        self.text = ScrolledText(self, wrap="word", width=80, height=18)
        self.text.grid(row=1, column=0, sticky="nsew", padx=10)
        if initial_text:
            self.text.insert("1.0", initial_text)

        btns = ttk.Frame(self)
        btns.grid(row=2, column=0, sticky="e", padx=10, pady=10)

        save_btn = ttk.Button(btns, text="Guardar (Ctrl+Enter)", command=self.on_save)
        cancel_btn = ttk.Button(btns, text="Cancelar (Esc)", command=self.on_cancel)
        save_btn.pack(side="left", padx=(0,8))
        cancel_btn.pack(side="left")

        # Bindings
        self.bind("<Escape>", lambda e: self.on_cancel())
        self.bind("<Control-Return>", lambda e: self.on_save())

        # Intento de posición cerca del mouse
        try:
            x, y = self.winfo_pointerx(), self.winfo_pointery()
            self.geometry(f"+{max(0, x-420)}+{max(0, y-300)}")
        except:
            pass

        self.text.focus_set()
        self.wait_window(self)

    def on_save(self):
        # end-1c evita el salto de línea final automático de Text
        content = self.text.get("1.0", "end-1c")
        if not content.strip():
            if not messagebox.askyesno("Mensaje vacío", "El contenido está vacío. ¿Guardar igualmente?"):
                return
        self.result = content
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()

def ask_multiline(parent, title, initial=""):
    dlg = MultilineInputDialog(parent, title=title, initial_text=initial)
    return dlg.result

# ---------- UI: Popup de pegado rápido ----------
class Popup(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Clipboard Buddy")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(padx=10, pady=10)

        # Posición cerca del puntero
        try:
            x, y = self.winfo_pointerx(), self.winfo_pointery()
            self.geometry(f"+{max(0, x-320)}+{max(0, y-240)}")
        except:
            pass

        # Grupo
        tk.Label(self, text="Grupo").grid(row=0, column=0, sticky="w")
        self.group_var = tk.StringVar()
        self.group_combo = ttk.Combobox(self, textvariable=self.group_var, state="readonly",
                                        values=all_group_names(self.app.data), width=40)
        self.group_combo.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0,6))
        self.group_combo.bind("<<ComboboxSelected>>", self.refresh_list)

        # Búsqueda
        tk.Label(self, text="Buscar").grid(row=2, column=0, sticky="w")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(self, textvariable=self.search_var, width=45)
        self.search_entry.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0,6))
        self.search_entry.bind("<KeyRelease>", self.refresh_list)

        # Lista mensajes
        self.listbox = tk.Listbox(self, width=60, height=12, activestyle="dotbox")
        self.listbox.grid(row=4, column=0, columnspan=3, sticky="nsew")
        self.listbox.bind("<Return>", lambda e: self.paste_selected())
        self.listbox.bind("<Escape>", lambda e: self.close())

        # Botones
        paste_btn   = ttk.Button(self, text="Pegar (Enter)", command=self.paste_selected)
        manage_btn  = ttk.Button(self, text="Gestionar… (Ctrl+Shift+E)", command=self.open_manager)
        cancel_btn  = ttk.Button(self, text="Cancelar (Esc)", command=self.close)
        paste_btn.grid(row=5, column=0, pady=8, sticky="ew")
        manage_btn.grid(row=5, column=1, pady=8, sticky="ew")
        cancel_btn.grid(row=5, column=2, pady=8, sticky="ew")

        # Accesos
        self.bind("<Escape>", lambda e: self.close())

        # Datos de lista actual [(display, text)]
        self.current_items = []
        # Inicializa
        self.group_combo.current(0)
        self.refresh_list()
        self.search_entry.focus_set()

        # Registra popup en la app para poder refrescar desde el gestor
        self.app.register_popup(self)

    def destroy(self):
        self.app.unregister_popup(self)
        super().destroy()

    def current_items_for_group(self):
        g = self.group_var.get()
        q = self.search_var.get().strip().lower()

        items = []
        if g == VIRTUAL_ALL:
            for grp, msg in all_messages_pairs(self.app.data):
                # En la lista mostramos una sola línea (para no romper el listbox);
                # los saltos de línea se reemplazan por ⏎ para indicarlo visualmente.
                disp = f"[{grp}] " + (msg.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ⏎ "))
                if not q or (q in msg.lower() or q in grp.lower()):
                    items.append((disp, msg))
        else:
            msgs = self.app.data.get(g, [])
            for msg in msgs:
                disp = msg.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ⏎ ")
                if not q or q in msg.lower():
                    items.append((disp, msg))
        return items

    def refresh_list(self, *args):
        # Actualiza valores de grupos
        self.group_combo["values"] = all_group_names(self.app.data)
        if self.group_var.get() not in self.group_combo["values"]:
            self.group_var.set(VIRTUAL_ALL)

        # Rellena listbox
        self.current_items = self.current_items_for_group()
        self.listbox.delete(0, tk.END)
        for disp, _ in self.current_items:
            self.listbox.insert(tk.END, disp)
        if self.listbox.size() > 0:
            self.listbox.select_set(0)

    def paste_selected(self):
        if self.listbox.size() == 0:
            messagebox.showinfo("Clipboard Buddy", "No hay mensajes en este filtro.")
            return
        idxs = self.listbox.curselection()
        if not idxs:
            idxs = (0,)
        _, text = self.current_items[idxs[0]]

        # Ocultar para devolver foco a la app anterior
        self.withdraw()
        self.update_idletasks()
        pyperclip.copy(text)
        time.sleep(0.05)
        try:
            keyboard.send("ctrl+v")
        except Exception as e:
            messagebox.showwarning("Clipboard Buddy", f"No pude simular Ctrl+V.\nQuedó copiado al portapapeles.\n{e}")
        self.close()

    def open_manager(self):
        self.app.open_manager()

    def close(self):
        self.destroy()

# ---------- UI: Gestor de grupos y mensajes ----------
class ManagerWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Gestor de grupos y mensajes")
        self.attributes("-topmost", True)
        self.geometry("820x460")
        self.configure(padx=10, pady=10)
        self.resizable(True, True)

        # Info virtual
        info = ttk.Label(self, text=f"Nota: '{VIRTUAL_ALL}' es un grupo virtual con todos los mensajes (se ve en el menú rápido).")
        info.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0,8))

        # Paneles
        # Grupos (izquierda)
        grp_frame = ttk.LabelFrame(self, text="Grupos")
        grp_frame.grid(row=1, column=0, sticky="nsew", padx=(0,10))
        self.rowconfigure(1, weight=1)
        self.columnconfigure(2, weight=1)

        self.groups_list = tk.Listbox(grp_frame, width=28, height=16, activestyle="dotbox", exportselection=False)
        self.groups_list.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=(4,6), padx=6)
        grp_frame.rowconfigure(0, weight=1)
        grp_frame.columnconfigure(0, weight=1)

        add_g_btn    = ttk.Button(grp_frame, text="Agregar grupo", command=self.add_group)
        ren_g_btn    = ttk.Button(grp_frame, text="Renombrar", command=self.rename_group)
        del_g_btn    = ttk.Button(grp_frame, text="Eliminar", command=self.delete_group)
        add_g_btn.grid(row=1, column=0, sticky="ew", padx=6, pady=2)
        ren_g_btn.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        del_g_btn.grid(row=1, column=2, sticky="ew", padx=6, pady=2)

        # Mensajes (derecha)
        msg_frame = ttk.LabelFrame(self, text="Mensajes")
        msg_frame.grid(row=1, column=2, sticky="nsew")
        msg_frame.rowconfigure(1, weight=1)
        msg_frame.columnconfigure(0, weight=1)

        # Filtro mensajes
        tk.Label(msg_frame, text="Buscar").grid(row=0, column=0, sticky="w", padx=6)
        self.msg_search_var = tk.StringVar()
        msg_search = ttk.Entry(msg_frame, textvariable=self.msg_search_var)
        msg_search.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        msg_frame.columnconfigure(1, weight=1)
        msg_search.bind("<KeyRelease>", lambda e: self.refresh_messages())

        self.messages_list = tk.Listbox(msg_frame, width=50, height=16, activestyle="dotbox")
        self.messages_list.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=6)

        add_m_btn = ttk.Button(msg_frame, text="Agregar mensaje", command=self.add_message)
        edit_m_btn = ttk.Button(msg_frame, text="Editar mensaje", command=self.edit_message)
        del_m_btn = ttk.Button(msg_frame, text="Eliminar mensaje", command=self.delete_message)
        add_m_btn.grid(row=2, column=0, sticky="ew", padx=6, pady=2)
        edit_m_btn.grid(row=2, column=1, sticky="ew", padx=6, pady=2)
        del_m_btn.grid(row=3, column=0, columnspan=2, sticky="ew", padx=6, pady=2)

        # Botones Import/Export
        io_frame = ttk.Frame(self)
        io_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8,0))
        export_btn = ttk.Button(io_frame, text="Exportar CSV…", command=self.export_csv)
        import_btn = ttk.Button(io_frame, text="Importar CSV…", command=self.import_csv)
        export_btn.pack(side="left", padx=(0,8))
        import_btn.pack(side="left")

        # Eventos
        self.groups_list.bind("<<ListboxSelect>>", lambda e: self.refresh_messages())

        # Carga inicial
        self.refresh_groups()
        if self.groups_list.size() > 0:
            self.groups_list.select_set(0)
            self.refresh_messages()

    # ---- helpers ----
    def get_selected_group(self):
        idxs = self.groups_list.curselection()
        if not idxs:
            return None
        names = sorted([g for g in self.app.data.keys() if g != VIRTUAL_ALL], key=lambda s: s.lower())
        if 0 <= idxs[0] < len(names):
            return names[idxs[0]]
        return None

    def refresh_groups(self):
        self.groups_list.delete(0, tk.END)
        for g in sorted([g for g in self.app.data.keys() if g != VIRTUAL_ALL], key=lambda s: s.lower()):
            self.groups_list.insert(tk.END, g)
        self.app.refresh_all_popups()

    def refresh_messages(self):
        self.messages_list.delete(0, tk.END)
        g = self.get_selected_group()
        if not g:
            return
        msgs = self.app.data.get(g, [])
        q = self.msg_search_var.get().strip().lower()
        for m in msgs:
            if not q or q in m.lower():
                # Mostrar indicadores de salto de línea en la lista
                disp = m.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ⏎ ")
                self.messages_list.insert(tk.END, disp)
        self.app.refresh_all_popups()

    def add_group(self):
        name = simpledialog.askstring("Nuevo grupo", "Nombre del grupo:", parent=self)
        if not name:
            return
        name = name.strip()
        if not name or name == VIRTUAL_ALL:
            messagebox.showerror("Error", f"Nombre inválido.")
            return
        if name in self.app.data:
            messagebox.showerror("Error", "Ya existe un grupo con ese nombre.")
            return
        self.app.data[name] = []
        save_data(self.app.data)
        self.refresh_groups()

    def rename_group(self):
        g = self.get_selected_group()
        if not g:
            messagebox.showinfo("Atención", "Seleccioná un grupo.")
            return
        new = simpledialog.askstring("Renombrar grupo", f"Nuevo nombre para '{g}':", initialvalue=g, parent=self)
        if not new:
            return
        new = new.strip()
        if not new or new == VIRTUAL_ALL:
            messagebox.showerror("Error", "Nombre inválido.")
            return
        if new in self.app.data and new != g:
            messagebox.showerror("Error", "Ya existe un grupo con ese nombre.")
            return
        if new == g:
            return
        self.app.data[new] = self.app.data.pop(g)
        save_data(self.app.data)
        self.refresh_groups()
        # Seleccionar el nuevo
        names = sorted([x for x in self.app.data.keys() if x != VIRTUAL_ALL], key=lambda s: s.lower())
        try:
            idx = names.index(new)
            self.groups_list.select_clear(0, tk.END)
            self.groups_list.select_set(idx)
            self.refresh_messages()
        except:
            pass

    def delete_group(self):
        g = self.get_selected_group()
        if not g:
            messagebox.showinfo("Atención", "Seleccioná un grupo.")
            return
        if not messagebox.askyesno("Confirmar", f"¿Eliminar el grupo '{g}' y todos sus mensajes?"):
            return
        self.app.data.pop(g, None)
        save_data(self.app.data)
        self.refresh_groups()
        self.refresh_messages()

    def _selected_message_raw(self):
        """ Devuelve el mensaje original (no la versión con '⏎ ') según selección. """
        g = self.get_selected_group()
        if not g:
            return None, None, None
        idxs = self.messages_list.curselection()
        if not idxs:
            return g, None, None
        # Reconstruimos el mensaje comparando contra la lista original del grupo,
        # porque en el listbox mostramos ' ⏎ ' en vez de '\n'.
        displayed = self.messages_list.get(idxs[0])
        candidates = self.app.data.get(g, [])
        for i, original in enumerate(candidates):
            if displayed == original.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ⏎ "):
                return g, i, original
        # Si no encontramos coincidencia (poco probable), usamos el índice directo como fallback.
        try:
            return g, idxs[0], candidates[idxs[0]]
        except:
            return g, None, None

    def add_message(self):
        g = self.get_selected_group()
        if not g:
            messagebox.showinfo("Atención", "Seleccioná un grupo.")
            return
        text = ask_multiline(self, title="Agregar mensaje", initial="")
        if text is None:
            return
        if text in self.app.data[g]:
            if not messagebox.askyesno("Duplicado", "Ese mensaje ya existe en el grupo. ¿Agregar de todos modos?"):
                return
        self.app.data[g].append(text)
        save_data(self.app.data)
        self.refresh_messages()

    def edit_message(self):
        g, pos, old = self._selected_message_raw()
        if not g:
            messagebox.showinfo("Atención", "Seleccioná un grupo.")
            return
        if pos is None:
            messagebox.showinfo("Atención", "Seleccioná un mensaje.")
            return
        new = ask_multiline(self, title="Editar mensaje", initial=old)
        if new is None:
            return
        self.app.data[g][pos] = new
        save_data(self.app.data)
        self.refresh_messages()

    def delete_message(self):
        g, pos, old = self._selected_message_raw()
        if not g:
            messagebox.showinfo("Atención", "Seleccioná un grupo.")
            return
        if pos is None:
            messagebox.showinfo("Atención", "Seleccioná un mensaje.")
            return
        if not messagebox.askyesno("Confirmar", "¿Eliminar el mensaje seleccionado?"):
            return
        try:
            del self.app.data[g][pos]
            save_data(self.app.data)
            self.refresh_messages()
        except Exception:
            pass

    def export_csv(self):
        file = filedialog.asksaveasfilename(
            title="Exportar a CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="snippets.csv"
        )
        if not file:
            return
        try:
            export_to_csv(self.app.data, file)
            messagebox.showinfo("Exportación", "Exportado correctamente.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar.\n{e}")

    def import_csv(self):
        file = filedialog.askopenfilename(
            title="Importar CSV",
            filetypes=[("CSV", "*.csv")]
        )
        if not file:
            return
        replace = messagebox.askyesno(
            "Importar CSV",
            "¿Reemplazar completamente los datos actuales?\n(Sí = reemplazar, No = fusionar)"
        )
        try:
            new_data = import_from_csv(file, self.app.data, replace=replace)
            self.app.data.clear()
            self.app.data.update(new_data)
            save_data(self.app.data)
            self.refresh_groups()
            self.refresh_messages()
            messagebox.showinfo("Importación", "Importado correctamente.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo importar.\n{e}")

# ---------- App principal ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()  # correr en "segundo plano"
        self.data = load_data()

        self._popups = set()
        self._manager = None

        # Hotkeys globales
        self.hotkey_thread = threading.Thread(target=self.register_hotkeys, daemon=True)
        self.hotkey_thread.start()

        self.protocol("WM_DELETE_WINDOW", self.quit_app)

    # ---- hotkeys ----
    def register_hotkeys(self):
        # Nota: en Windows puede requerir ejecutar como Administrador
        keyboard.add_hotkey(DEFAULT_HOTKEY_POPUP, lambda: self.after(0, self.open_popup))
        keyboard.add_hotkey(DEFAULT_HOTKEY_MANAGER, lambda: self.after(0, self.open_manager))
        keyboard.wait()

    # ---- ventanas ----
    def open_popup(self):
        # Evita duplicados múltiples
        for w in self.winfo_children():
            if isinstance(w, Popup):
                try:
                    w.lift()
                    w.focus_force()
                except:
                    pass
                return
        Popup(self)

    def open_manager(self):
        if self._manager and tk.Toplevel.winfo_exists(self._manager):
            try:
                self._manager.lift()
                self._manager.focus_force()
            except:
                pass
            return
        self._manager = ManagerWindow(self)

    # ---- coordinación de refrescos ----
    def register_popup(self, popup):
        self._popups.add(popup)

    def unregister_popup(self, popup):
        self._popups.discard(popup)

    def refresh_all_popups(self):
        # Si cambio datos en gestor, refresco popups abiertos
        for p in list(self._popups):
            try:
                p.refresh_list()
            except:
                pass

    def quit_app(self):
        self.destroy()

if __name__ == "__main__":
    App().mainloop()
