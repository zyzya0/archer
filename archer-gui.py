#did it need readme, hah

import os
import re
import queue
import shlex
import signal
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext


PKG_RE = re.compile(r"^[A-Za-z0-9@._+\-]+$")

# (id, подпись, подсказка, нужен ли пакет)
ACTIONS = [
    ("install", "Установить пакет", "pacman -S <pkg> --noconfirm --needed", True),
    ("remove",  "Удалить пакет",    "pacman -Rns <pkg> --noconfirm",        True),
    ("clean",   "Очистить кеш",     "pacman -Scc --noconfirm",              False),
    ("update",  "Обновить систему", "pacman -Syyu --noconfirm",             False),
]


class ArcherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Archer — лучший инструмент для Arch-based дистрибутивов")
        self.root.geometry("880x640")
        self.root.minsize(720, 520)

        self.proc = None
        self.reader_thread = None
        self.out_queue = queue.Queue()
        self.running = False

        self._build_style()
        self._build_ui()
        self._update_widgets_state()
        self._poll_queue()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build_style(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Sub.TLabel", foreground="#666")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("Action.TRadiobutton", font=("Segoe UI", 10), padding=3)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Archer", style="Title.TLabel").pack(anchor="w")
        ttk.Label(main, text="Графическая оболочка для pacman",
                  style="Sub.TLabel").pack(anchor="w", pady=(0, 10))

        # --- выбор действия ---
        act_frame = ttk.LabelFrame(main, text="Действие", padding=8)
        act_frame.pack(fill="x")

        self.action_var = tk.StringVar(value="install")
        for value, label, hint, _ in ACTIONS:
            ttk.Radiobutton(
                act_frame,
                text=f"{label}   —   {hint}",
                value=value,
                variable=self.action_var,
                command=self._update_widgets_state,
                style="Action.TRadiobutton",
            ).pack(anchor="w")

        # --- имя пакета ---
        pkg_frame = ttk.Frame(main)
        pkg_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(pkg_frame, text="Имя пакета:", width=14).pack(side="left")
        self.pkg_var = tk.StringVar()
        self.pkg_entry = ttk.Entry(pkg_frame, textvariable=self.pkg_var)
        self.pkg_entry.pack(side="left", fill="x", expand=True)
        self.pkg_entry.bind("<Return>", lambda e: self._start())

        # --- пароль sudo ---
        pwd_frame = ttk.Frame(main)
        pwd_frame.pack(fill="x", pady=(8, 0))
        ttk.Label(pwd_frame, text="Пароль sudo:", width=14).pack(side="left")
        self.pwd_var = tk.StringVar()
        self.pwd_entry = ttk.Entry(pwd_frame, textvariable=self.pwd_var, show="•")
        self.pwd_entry.pack(side="left", fill="x", expand=True)
        self.pwd_entry.bind("<Return>", lambda e: self._start())
        self.show_pwd = tk.BooleanVar(value=False)
        ttk.Checkbutton(pwd_frame, text="показать", variable=self.show_pwd,
                        command=self._toggle_pwd).pack(side="left", padx=(6, 0))

        # --- кнопки ---
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=10)
        self.btn_run = ttk.Button(btn_frame, text="▶  Выполнить",
                                  style="Accent.TButton", command=self._start)
        self.btn_run.pack(side="left")
        self.btn_stop = ttk.Button(btn_frame, text="■  Остановить",
                                   command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_clear = ttk.Button(btn_frame, text="Очистить лог",
                                    command=self._clear_log)
        self.btn_clear.pack(side="left")

        # --- вывод ---
        out_frame = ttk.LabelFrame(main, text="Вывод", padding=4)
        out_frame.pack(fill="both", expand=True)

        self.text = scrolledtext.ScrolledText(
            out_frame, wrap="word", height=16,
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="#d4d4d4", relief="flat", borderwidth=0,
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("cmd",  foreground="#4ec9b0")
        self.text.tag_configure("ok",   foreground="#6a9955")
        self.text.tag_configure("warn", foreground="#dcdcaa")
        self.text.tag_configure("err",  foreground="#f48771")
        self.text.configure(state="disabled")

        # --- статус ---
        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(main, textvariable=self.status_var, relief="sunken",
                  anchor="w", padding=4).pack(fill="x", pady=(8, 0))

    # ------------------------------------------------------------- helpers
    def _toggle_pwd(self):
        self.pwd_entry.configure(show="" if self.show_pwd.get() else "•")

    def _update_widgets_state(self):
        action = self.action_var.get()
        needs_pkg = action in ("install", "remove")
        self.pkg_entry.configure(
            state="normal" if (needs_pkg and not self.running) else "disabled"
        )
        self.pwd_entry.configure(state="disabled" if self.running else "normal")

    def _append_line(self, text, tag=None):
        self.text.configure(state="normal")
        self.text.insert("end", text, tag)
        self.text.see("end")
        self.text.configure(state="disabled")

    def _handle_output(self, text):
        low = text.lower()
        tag = None
        if "error" in low or "ошибка" in low or "failed" in low:
            tag = "err"
        elif "warning" in low or "предупрежд" in low:
            tag = "warn"
        self._append_line(text, tag)

    def _clear_log(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def set_status(self, text):
        self.status_var.set(text)

    # ------------------------------------------------------------ команды
    def _build_argv(self, action, pkg):
        if action == "install":
            return ["pacman", "-S", pkg, "--noconfirm", "--needed"]
        if action == "remove":
            return ["pacman", "-Rns", pkg, "--noconfirm"]
        if action == "clean":
            return ["pacman", "-Scc", "--noconfirm"]
        if action == "update":
            return ["pacman", "-Syyu", "--noconfirm"]
        raise ValueError(f"Неизвестное действие: {action}")

    def _start(self):
        if self.running:
            return

        action = self.action_var.get()
        pkg = self.pkg_var.get().strip()

        if action in ("install", "remove"):
            if not pkg:
                messagebox.showwarning("Archer", "Укажите имя пакета.")
                return
            if not PKG_RE.match(pkg):
                messagebox.showerror("Archer", "Недопустимые символы в имени пакета.")
                return

        argv = self._build_argv(action, pkg)
        password = ""
        if os.geteuid() != 0:
            argv = ["sudo", "-S", "-p", "", *argv]
            password = self.pwd_var.get()

        self._append_line("$ " + " ".join(shlex.quote(a) for a in argv) + "\n", "cmd")
        self.set_status("Выполняется...")

        self.running = True
        self.btn_run.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._update_widgets_state()

        try:
            self.proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE if password else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except FileNotFoundError:
            self._finish_with_error("Команда не найдена. Установлены ли pacman и sudo?")
            return
        except Exception as exc:
            self._finish_with_error(f"Не удалось запустить команду: {exc}")
            return

        # отдаём sudo пароль и закрываем stdin
        if password and self.proc.stdin:
            try:
                self.proc.stdin.write(password + "\n")
                self.proc.stdin.flush()
                self.proc.stdin.close()
            except Exception:
                pass

        self.reader_thread = threading.Thread(
            target=self._reader, args=(self.proc,), daemon=True
        )
        self.reader_thread.start()

    def _reader(self, proc):
        try:
            for line in proc.stdout:
                self.out_queue.put(("out", line))
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            code = proc.wait()
            self.out_queue.put(("done", code))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.out_queue.get_nowait()
                if kind == "out":
                    self._handle_output(payload)
                elif kind == "done":
                    self._on_done(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _on_done(self, code):
        self.running = False
        self.proc = None
        self.btn_run.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._update_widgets_state()

        if code == 0:
            self._append_line("\n✔ Успешно завершено (код 0)\n", "ok")
            self.set_status("Готово")
        else:
            self._append_line(f"\n✘ Завершено с ошибкой (код {code})\n", "err")
            self.set_status(f"Ошибка, код {code}")

    def _finish_with_error(self, msg):
        self.running = False
        self.proc = None
        self.btn_run.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._update_widgets_state()
        self._append_line(msg + "\n", "err")
        self.set_status("Ошибка")
        messagebox.showerror("Archer", msg)

    def _stop(self):
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.set_status("Останавливаю...")

    def _on_close(self):
        if self.running and self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("Archer", "Команда ещё выполняется. Прервать и выйти?"):
                return
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    ArcherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
