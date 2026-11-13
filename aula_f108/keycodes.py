"""HID usage names and Linux evdev <-> HID keyboard usage mapping."""
from __future__ import annotations

# HID keyboard usage -> (name, evdev keycode)
_HID = {
    0x04: ("A", 30), 0x05: ("B", 48), 0x06: ("C", 46), 0x07: ("D", 32), 0x08: ("E", 18),
    0x09: ("F", 33), 0x0A: ("G", 34), 0x0B: ("H", 35), 0x0C: ("I", 23), 0x0D: ("J", 36),
    0x0E: ("K", 37), 0x0F: ("L", 38), 0x10: ("M", 50), 0x11: ("N", 49), 0x12: ("O", 24),
    0x13: ("P", 25), 0x14: ("Q", 16), 0x15: ("R", 19), 0x16: ("S", 31), 0x17: ("T", 20),
    0x18: ("U", 22), 0x19: ("V", 47), 0x1A: ("W", 17), 0x1B: ("X", 45), 0x1C: ("Y", 21),
    0x1D: ("Z", 44),
    0x1E: ("1", 2), 0x1F: ("2", 3), 0x20: ("3", 4), 0x21: ("4", 5), 0x22: ("5", 6),
    0x23: ("6", 7), 0x24: ("7", 8), 0x25: ("8", 9), 0x26: ("9", 10), 0x27: ("0", 11),
    0x28: ("Enter", 28), 0x29: ("Esc", 1), 0x2A: ("Backspace", 14), 0x2B: ("Tab", 15),
    0x2C: ("Space", 57), 0x2D: ("-", 12), 0x2E: ("=", 13), 0x2F: ("[", 26), 0x30: ("]", 27),
    0x31: ("\\", 43), 0x33: (";", 39), 0x34: ("'", 40), 0x35: ("`", 41), 0x36: (",", 51),
    0x37: (".", 52), 0x38: ("/", 53), 0x39: ("Caps Lock", 58),
    0x3A: ("F1", 59), 0x3B: ("F2", 60), 0x3C: ("F3", 61), 0x3D: ("F4", 62), 0x3E: ("F5", 63),
    0x3F: ("F6", 64), 0x40: ("F7", 65), 0x41: ("F8", 66), 0x42: ("F9", 67), 0x43: ("F10", 68),
    0x44: ("F11", 87), 0x45: ("F12", 88),
    0x46: ("Print Screen", 99), 0x47: ("Scroll Lock", 70), 0x48: ("Pause", 119),
    0x49: ("Insert", 110), 0x4A: ("Home", 102), 0x4B: ("Page Up", 104), 0x4C: ("Delete", 111),
    0x4D: ("End", 107), 0x4E: ("Page Down", 109), 0x4F: ("→", 106), 0x50: ("←", 105),
    0x51: ("↓", 108), 0x52: ("↑", 103),
    0x53: ("Num Lock", 69), 0x54: ("Num /", 98), 0x55: ("Num *", 55), 0x56: ("Num -", 74),
    0x57: ("Num +", 78), 0x58: ("Num Enter", 96), 0x59: ("Num 1", 79), 0x5A: ("Num 2", 80),
    0x5B: ("Num 3", 81), 0x5C: ("Num 4", 75), 0x5D: ("Num 5", 76), 0x5E: ("Num 6", 77),
    0x5F: ("Num 7", 71), 0x60: ("Num 8", 72), 0x61: ("Num 9", 73), 0x62: ("Num 0", 82),
    0x63: ("Num .", 83), 0x64: ("< >", 86), 0x65: ("Menu", 127),
    0x68: ("F13", 183), 0x69: ("F14", 184), 0x6A: ("F15", 185), 0x6B: ("F16", 186),
    0x6C: ("F17", 187), 0x6D: ("F18", 188), 0x6E: ("F19", 189), 0x6F: ("F20", 190),
    0x70: ("F21", 191), 0x71: ("F22", 192), 0x72: ("F23", 193), 0x73: ("F24", 194),
    0xE0: ("Left Ctrl", 29), 0xE1: ("Left Shift", 42), 0xE2: ("Left Alt", 56),
    0xE3: ("Left Super", 125), 0xE4: ("Right Ctrl", 97), 0xE5: ("Right Shift", 54),
    0xE6: ("Right Alt", 100), 0xE7: ("Right Super", 126),
}

KEY_NAMES: dict[int, str] = {u: n for u, (n, _e) in _HID.items()}
EVDEV_TO_HID: dict[int, int] = {e: u for u, (_n, e) in _HID.items()}

# Consumer-page usages offered by the vendor driver
CONSUMER: list[tuple[int, str]] = [
    (0x00CD, "Play / Pause"), (0x00B7, "Stop"), (0x00B6, "Oldingi trek"),
    (0x00B5, "Keyingi trek"), (0x00E9, "Ovoz +"), (0x00EA, "Ovoz −"), (0x00E2, "Ovozsiz"),
    (0x0183, "Media pleer"), (0x0192, "Kalkulyator"), (0x0194, "Mening kompyuterim"),
    (0x018A, "Pochta"), (0x0223, "Brauzer: bosh sahifa"), (0x0227, "Brauzer: yangilash"),
    (0x0226, "Brauzer: to'xtatish"), (0x0224, "Brauzer: orqaga"),
    (0x0225, "Brauzer: oldinga"), (0x022A, "Brauzer: sevimlilar"), (0x0221, "Qidiruv"),
]
CONSUMER_NAMES = dict(CONSUMER)

MOUSE: list[tuple[str, str]] = [
    ("left", "Chap tugma"), ("right", "O'ng tugma"), ("middle", "O'rta tugma"),
    ("back", "Orqaga (4)"), ("forward", "Oldinga (5)"),
    ("wheel_up", "G'ildirak yuqoriga"), ("wheel_down", "G'ildirak pastga"),
]
MOUSE_NAMES = dict(MOUSE)

MODIFIERS = [(0x01, "Ctrl"), (0x02, "Shift"), (0x04, "Alt"), (0x08, "Super"),
             (0x10, "R-Ctrl"), (0x20, "R-Shift"), (0x40, "R-Alt"), (0x80, "R-Super")]


def key_name(usage: int) -> str:
    return KEY_NAMES.get(usage, f"0x{usage:02X}")


def combo_name(usage: int, mods: int) -> str:
    parts = [n for bit, n in MODIFIERS if mods & bit]
    if usage:
        parts.append(key_name(usage))
    return "+".join(parts) or "—"


def selectable_keys() -> list[tuple[int, str]]:
    return sorted(KEY_NAMES.items(), key=lambda kv: kv[0])
