# screenshot_util.py

import pyautogui
import time
import win32gui
import win32con
from PIL import ImageGrab

# Change this to match your Dolphin window name more loosely if needed
WINDOW_KEYWORDS = ["Dolphin", "Animal Crossing"]

def find_dolphin_window():
    """Find the Dolphin window handle based on title keywords."""
    target_hwnd = None

    def enum_handler(hwnd, _):
        nonlocal target_hwnd
        title = win32gui.GetWindowText(hwnd)
        if all(key.lower() in title.lower() for key in WINDOW_KEYWORDS):
            target_hwnd = hwnd

    win32gui.EnumWindows(enum_handler, None)
    return target_hwnd

def activate_window(hwnd):
    """Force a window to foreground."""
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.2)

def screenshot_dolphin_window():
    """Bring Dolphin to front and capture its window only."""
    hwnd = find_dolphin_window()
    if hwnd is None:
        print("⚠ Dolphin window not found for screenshot.")
        return None

    # Bring to front
    activate_window(hwnd)

    # Get window bounds
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)

    # Capture only this region
    img = ImageGrab.grab(bbox=(left, top, right, bottom))
    return img

if __name__ == "__main__":
    img = screenshot_dolphin_window()
    if img:
        img.show()



