"""AULA F108Pro protocol, reconstructed from the vendor's Windows driver
("AULA F108Pro Driver 1.0.0.2", DeviceDriver.exe).

Wired  (0C45:800A): 64-byte HID *feature* reports (report ID 0) on the
                    vendor collection 0xFF13 (interface 3).
2.4G   (05AC:024F): 32-byte output/input reports on the vendor collection
                    0xFF60 (interface 3), last byte = 8-bit checksum.

Only commands observed in the vendor driver are implemented. The driver has
no firmware-update code (that is a separate tool), and neither does this one.
"""
from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass, field

from .hidio import HidrawDevice, HidrawInfo, enumerate_hidraw

WIRED_VID, WIRED_PID = 0x0C45, 0x800A
DONGLE_VID, DONGLE_PID = 0x05AC, 0x024F

SIG = b"\xAA\x55"

# ---------------------------------------------------------------- effects
# mode -> (name, flags). Flags (from the driver's UI table):
#   B brightness, S speed, C colour/colourful, D direction 0/1, V direction 2/3
EFFECTS: dict[int, tuple[str, str]] = {
    0: ("LED Off", ""),
    1: ("Static", "BC"),
    2: ("SingleOn", "BSC"),
    3: ("SingleOff", "BSC"),
    4: ("Glittering", "BSC"),
    5: ("Falling", "BSC"),
    6: ("Colourful", "BS"),
    7: ("Breath", "BSC"),
    8: ("Spectrum", "BS"),
    9: ("Outward", "BSC"),
    10: ("Scrolling", "BSCV"),
    11: ("Rolling", "BSCD"),
    12: ("Rotating", "BSCD"),
    13: ("Explode", "BSC"),
    14: ("Launch", "BSC"),
    15: ("Ripples", "BSC"),
    16: ("Flowing", "BSCD"),
    17: ("Pulsating", "BSC"),
    18: ("Tilt", "BSCD"),
    19: ("Shuttle", "BSC"),
}
MODE_USER = 0x80          # per-key ("user") lighting

# Music rhythm (2.4G command 0x0B) — combobox values from the vendor driver
MUSIC_SCHEMES = {1: "Green/Yellow/Red", 2: "Rainbow", 3: "Reverse Rainbow", 4: "Gradient",
                 5: "Spectrum Cycle", 6: "White", 7: "Red", 8: "Orange", 9: "Yellow",
                 10: "Blue", 11: "Green"}
MUSIC_BACKGROUNDS = {0: "Off", 1: "Green/Yellow/Red", 2: "Rainbow", 3: "Reverse Rainbow",
                     4: "Gradient", 5: "Spectrum Cycle", 6: "White", 7: "Red", 8: "Orange",
                     9: "Yellow", 10: "Blue", 11: "Green"}
BRIGHTNESS_MAX = 5
SPEED_MAX = 5


@dataclass
class Effect:
    mode: int = 11
    color: tuple[int, int, int] = (255, 0, 0)
    colorful: bool = True
    brightness: int = 5
    speed: int = 3
    direction: int = 0

    def data16(self) -> bytes:
        d = bytearray(16)
        d[0] = self.mode & 0xFF
        if self.mode != 0:
            d[1], d[2], d[3] = (int(c) & 0xFF for c in self.color)
            d[8] = 1 if self.colorful else 0
            d[9] = max(0, min(BRIGHTNESS_MAX, int(self.brightness)))
            d[10] = max(0, min(SPEED_MAX, int(self.speed)))
            d[11] = int(self.direction) & 0xFF
        d[14:16] = SIG
        return bytes(d)


# ---------------------------------------------------------------- key map
# Each key has a 4-byte entry at offset key_index*4 in a 0x240-byte table.
KEYMAP_SIZE = 0x240

MOD_BITS = {"lctrl": 0x01, "lshift": 0x02, "lalt": 0x04, "lgui": 0x08,
            "rctrl": 0x10, "rshift": 0x20, "ralt": 0x40, "rgui": 0x80}


def entry_default() -> bytes:
    return b"\x00\x00\x00\x00"


def entry_disabled() -> bytes:
    return b"\x05\x03\x00\x00"


def entry_key(usage: int, mods: int = 0) -> bytes:
    """Keyboard usage (HID page 7) with optional modifier mask."""
    if 0xE0 <= usage <= 0xE7 and mods == 0:
        return bytes([0x02, 1 << (usage - 0xE0), 0x00, 0x00])
    return bytes([0x02, mods & 0xFF, usage & 0xFF, 0x00])


def entry_consumer(usage: int) -> bytes:
    """Consumer-page usage (media keys, calculator, browser keys...)."""
    return bytes([0x03, usage & 0xFF, (usage >> 8) & 0xFF, 0x00])


MOUSE_ENTRIES = {
    "left": b"\x01\x01\x01\x00", "right": b"\x01\x01\x02\x00",
    "middle": b"\x01\x01\x04\x00", "back": b"\x01\x01\x08\x00",
    "forward": b"\x01\x01\x10\x00", "wheel_up": b"\x01\x03\x01\x00",
    "wheel_down": b"\x01\x03\xFF\x00",
}


def entry_macro(index: int, mode: int = 0, count: int = 1) -> bytes:
    """Run stored macro number `index` (its slot in the macro upload)."""
    return bytes([0x06, index & 0xFF, mode & 0xFF, count & 0xFF])


def build_keymap(entries: dict[int, bytes]) -> bytes:
    buf = bytearray(KEYMAP_SIZE)
    for key_index, e in entries.items():
        off = key_index * 4
        if 0 < key_index and off + 4 <= KEYMAP_SIZE - 2:
            buf[off:off + 4] = e
    buf[-2:] = SIG
    return bytes(buf)


# ---------------------------------------------------------------- lighting tables
LIGHT_SIZE = 0x240


def build_user_light(colors: dict[int, tuple[int, int, int]]) -> bytes:
    """Per-key static colours, entry [L, R, G, B] at offset 4*L."""
    buf = bytearray(LIGHT_SIZE)
    for li, (r, g, b) in colors.items():
        off = li * 4
        if 0 < li and off + 4 <= LIGHT_SIZE - 2:
            buf[off:off + 4] = bytes([li, r & 0xFF, g & 0xFF, b & 0xFF])
    buf[-2:] = SIG
    return bytes(buf)


def build_stream(colors: list[tuple[int, tuple[int, int, int]]]) -> bytes:
    """Real-time frame: sequential [L, R, G, B] tuples, 8 packets."""
    buf = bytearray(0x200)
    for i, (li, (r, g, b)) in enumerate(colors[:128]):
        buf[i * 4:i * 4 + 4] = bytes([li, r & 0xFF, g & 0xFF, b & 0xFF])
    return bytes(buf)


# ---------------------------------------------------------------- macros
# Event = 4 bytes: <lo> <hi> <code> <flags>
EV_KEY_DOWN, EV_KEY_UP = 0xB0, 0x30
EV_MOUSE_DOWN, EV_MOUSE_UP = 0x90, 0x10
EV_DELAY = 0x50
MOUSE_BTN = {"left": 0x01, "right": 0x02, "middle": 0x04}


@dataclass
class MacroEvent:
    kind: str          # "key" | "mouse" | "delay"
    code: int = 0      # HID usage / mouse button mask / delay ms
    down: bool = True

    def encode(self) -> bytes:
        if self.kind == "delay":
            ms = max(10, min(0xFFFF, int(self.code)))
            return bytes([ms & 0xFF, ms >> 8, 0x00, EV_DELAY])
        if self.kind == "mouse":
            return bytes([0, 0, self.code & 0xFF, EV_MOUSE_DOWN if self.down else EV_MOUSE_UP])
        return bytes([0, 0, self.code & 0xFF, EV_KEY_DOWN if self.down else EV_KEY_UP])


MACRO_SLOTS = 100
MACRO_TABLE = MACRO_SLOTS * 4   # 0x190
MACRO_MAX = 0xE00


def _macro_image(macros: list[list[MacroEvent]]) -> tuple[bytearray, int]:
    """Offset table (100 slots; unused = 0, empty macro = FF FF FF FF) followed
    by the macros. Returns (buffer, used length)."""
    buf = bytearray(MACRO_MAX + 64)
    off = MACRO_TABLE
    for i, events in enumerate(macros[:MACRO_SLOTS]):
        if not events:
            buf[i * 4:i * 4 + 4] = b"\xFF\xFF\xFF\xFF"
            continue
        blob = b"".join(e.encode() for e in events)
        need = 8 + len(blob)
        if off + need > MACRO_MAX - 64:
            raise ValueError("macros too large for keyboard memory")
        buf[i * 4:i * 4 + 4] = bytes([off & 0xFF, off >> 8, 0, 0])
        n = len(events)
        buf[off:off + 2] = bytes([n & 0xFF, n >> 8])
        buf[off + 8:off + need] = blob
        off += need
    return buf, off


def build_macros(macros: list[list[MacroEvent]]) -> bytes:
    """Wired image: whole 64-byte packets, at least one spare, AA 55 at the end."""
    buf, length = _macro_image(macros)
    packets = length // 64 + (1 if length % 64 == 0 else 2)
    out = bytearray(buf[:packets * 64])
    out[-2:] = SIG
    return bytes(out)


def build_macros_dongle(macros: list[list[MacroEvent]]) -> list[tuple[int, bytes]]:
    """Dongle image as (length byte, 28 data bytes) chunks, like the vendor app:
    L/28 + 1 + (L%28 != 0) chunks, AA 55 in the last two bytes, last length = L%28."""
    buf, length = _macro_image(macros)
    q = length // 28
    count = q + 1 + (1 if length % 28 else 0)
    img = bytearray(buf[:count * 28])
    img[-2:] = SIG
    return [(0x1C if i < count - 1 else length - q * 28, bytes(img[i * 28:(i + 1) * 28]))
            for i in range(count)]


# ---------------------------------------------------------------- settings
SLEEP_CHOICES = ["No sleep", "1 min", "5 min", "30 min"]


@dataclass
class Settings:
    win_lock: bool = False
    altf4_lock: bool = False
    alttab_lock: bool = False
    fn_switch: int = 0          # 0 momentary, 1 toggle
    sleep_time: int = 0         # raw value (see SLEEP_CHOICES)
    key_respond: int = 0        # raw debounce level value

    def data64(self) -> bytes:
        d = bytearray(64)
        d[0], d[1] = 0x00, 0x01
        d[2] = int(self.alttab_lock)
        d[3] = int(self.altf4_lock)
        d[4] = int(self.win_lock)
        d[5] = self.fn_switch & 0xFF
        d[6] = self.sleep_time & 0xFF
        d[8] = self.key_respond & 0xFF
        d[62:64] = SIG
        return bytes(d)


def clock_data(now: _dt.datetime | None = None, image: int = 0) -> bytes:
    now = now or _dt.datetime.now()
    d = bytearray(64)
    d[0] = 0
    d[1] = image + 1
    d[2] = 0x5A
    d[3] = now.year % 2000
    d[4], d[5] = now.month, now.day
    d[6], d[7], d[8] = now.hour, now.minute, now.second
    d[10] = (now.weekday() + 1) % 7      # 0 = Sunday
    d[62:64] = SIG
    return bytes(d)


# ================================================================= devices
class DeviceError(RuntimeError):
    pass


def _pad(b: bytes, n: int) -> bytes:
    return bytes(b[:n]).ljust(n, b"\x00")


class Wired:
    """Wired USB mode — 64-byte feature reports."""
    kind = "wired"

    def __init__(self, info: HidrawInfo, delay: float = 0.035):
        self.dev = HidrawDevice(info)
        self.delay = delay

    def close(self):
        self.dev.close()

    # -- transport ---------------------------------------------------
    def _send(self, payload: bytes, readback: bool = True) -> bytes | None:
        time.sleep(self.delay)
        self.dev.set_feature(_pad(payload, 64))
        if readback:
            time.sleep(self.delay)
            return self.dev.get_feature(64)
        return None

    def _send_block(self, data: bytes) -> None:
        time.sleep(self.delay)
        for i in range(0, len(data), 64):
            chunk = _pad(data[i:i + 64], 64)
            for attempt in range(11):
                try:
                    self.dev.set_feature(chunk)
                    break
                except OSError:
                    if attempt == 10:
                        raise
                    time.sleep(self.delay)
            time.sleep(self.delay)

    @staticmethod
    def _cmd(op: int, count: int = 0, b2: int = 0) -> bytes:
        p = bytearray(64)
        p[0], p[1], p[2], p[8] = 0x04, op, b2, count
        return bytes(p)

    def _transaction(self, op: int, data: bytes, refresh: bool, begin: int = 0x18,
                     b2: int = 0) -> None:
        self._send(self._cmd(begin))
        self._send(self._cmd(op, len(data) // 64, b2))
        if len(data) == 64:
            self._send(data, readback=False)
        else:
            self._send_block(data)
        self._send(self._cmd(0x02))
        if refresh:
            self._send(self._cmd(0xF0), readback=False)

    # -- commands ----------------------------------------------------
    def set_effect(self, eff: Effect) -> None:
        self._transaction(0x13, _pad(eff.data16(), 64), refresh=True)

    def set_user_light(self, colors: dict[int, tuple[int, int, int]], brightness: int = 5) -> None:
        sel = bytearray(64)
        sel[0] = MODE_USER
        sel[9] = max(0, min(BRIGHTNESS_MAX, brightness))
        sel[14:16] = SIG
        self._transaction(0x13, bytes(sel), refresh=True)
        self._transaction(0x23, build_user_light(colors), refresh=True)

    def _send_fast(self, payload: bytes) -> bytes:
        """Control packet with ack: ack[3] == 0x01 ok, 0xFF busy (resend once)."""
        ack = b""
        for _ in range(2):
            time.sleep(0.005)
            self.dev.set_feature(_pad(payload, 64))
            time.sleep(0.005)
            ack = self.dev.get_feature(64)
            if len(ack) < 4 or ack[3] != 0xFF:
                break
        return ack

    def stream(self, colors: list[tuple[int, tuple[int, int, int]]]) -> bool:
        """One real-time (non-persistent) per-key frame. The vendor app
        re-sends frames continuously while its custom-light page is open."""
        frame = build_stream(colors)
        ack = self._send_fast(self._cmd(0x20, 8))
        if len(ack) < 4 or ack[3] != 0x01:
            return False
        for i in range(0, len(frame), 64):
            self.dev.set_feature(frame[i:i + 64])
            time.sleep(0.002)
        self._send_fast(self._cmd(0x02))
        return True

    def read_colors(self) -> dict[int, tuple[int, int, int]]:
        ack = b""
        for _ in range(20):           # ack[3] == 0xFF means "busy, ask again"
            time.sleep(0.01)
            self.dev.set_feature(self._cmd(0xF5, 9))
            time.sleep(0.005)
            ack = self.dev.get_feature(64)
            if len(ack) >= 4 and ack[3] == 0x01:
                break
            time.sleep(0.05)
        else:
            raise DeviceError(f"unexpected ack {ack[:8].hex(' ')}")
        buf = b""
        for _ in range(9):
            time.sleep(0.003)
            buf += self.dev.get_feature(64)
        self._send(self._cmd(0x02))
        return {i: (buf[4 * i + 1], buf[4 * i + 2], buf[4 * i + 3])
                for i in range(1, len(buf) // 4) if buf[4 * i] == i}

    def set_keymap(self, entries: dict[int, bytes], fn_layer: bool = False) -> None:
        self._transaction(0x27 if fn_layer else 0x11, build_keymap(entries), refresh=True)

    def set_macros(self, macros: list[list[MacroEvent]]) -> None:
        data = build_macros(macros)
        self._send(self._cmd(0x19))
        self._send(self._cmd(0x15, len(data) // 64))
        time.sleep(0.03)
        self._send_block(data)
        time.sleep(0.03)
        self._send(self._cmd(0x02))

    def set_settings(self, s: Settings) -> None:
        self._transaction(0x17, s.data64(), refresh=False, b2=1)

    def set_clock(self, now: _dt.datetime | None = None, image: int = 0) -> None:
        self._transaction(0x28, clock_data(now, image), refresh=False)

    def battery(self) -> int | None:
        return None


class Dongle:
    """2.4 GHz dongle — 32-byte output reports with checksum."""
    kind = "dongle"

    def __init__(self, info: HidrawInfo):
        self.dev = HidrawDevice(info)

    def close(self):
        self.dev.close()

    def _xfer(self, cmd: int, length: int, idx: int, data: bytes = b"", retries: int = 3) -> bytes | None:
        p = bytearray(32)
        p[0], p[1], p[2] = cmd, length, idx
        p[3:3 + len(data)] = data[:28]
        p[31] = sum(p[:31]) & 0xFF
        for _attempt in range(retries):    # radio packets can get lost: resend on missing ack
            self.dev.drain()
            try:
                self.dev.write(bytes(p))
            except OSError:
                time.sleep(0.01)
                self.dev.write(bytes(p))
            time.sleep(0.005)
            for _ in range(20):
                r = self.dev.read(0.01, 64)
                if r and r[:3] == bytes(p[:3]):
                    return r
                time.sleep(0.01)
        return None

    def _chunks(self, cmd: int, data: bytes) -> None:
        n = (len(data) + 27) // 28
        for i in range(n):
            part = data[i * 28:(i + 1) * 28]
            self._xfer(cmd, len(part), i, part)
            time.sleep(0.002)

    def probe(self) -> bool:
        r = self._xfer(0x02, 0, 0)
        return bool(r) and r[0] == 0x02

    def set_effect(self, eff: Effect) -> None:
        self._xfer(0x05, 0x10, 0, eff.data16())

    def set_user_light(self, colors: dict[int, tuple[int, int, int]], brightness: int = 5) -> None:
        d = bytearray(16)
        d[0] = MODE_USER
        d[9] = max(0, min(BRIGHTNESS_MAX, brightness))
        d[14:16] = SIG
        self._xfer(0x05, 0x10, 0, bytes(d))
        self._chunks(0x14, build_user_light(colors))

    def stream(self, colors):
        raise DeviceError("real-time lighting is only available over USB")

    def music(self, heights: list[int], scheme: int = 2, background: int = 0,
              bg_brightness: int = 100) -> bool:
        """One music-rhythm frame; the keyboard renders it itself.
        heights: 21 column heights 0..6 (lit key rows from the bottom).
        scheme: MUSIC_SCHEMES value, background: MUSIC_BACKGROUNDS value."""
        hs = bytes(max(0, min(6, int(h))) for h in heights[:21]).ljust(21, b"\x00")
        data = bytes([scheme & 0xFF, background & 0xFF, max(0, min(100, int(bg_brightness)))]) + hs
        return self._xfer(0x0B, 0x1C, 0, data, retries=1) is not None

    def read_colors(self):
        raise DeviceError("reading colours is only available over USB")

    def set_keymap(self, entries: dict[int, bytes], fn_layer: bool = False) -> None:
        self._chunks(0x12 if fn_layer else 0x10, build_keymap(entries))

    def set_macros(self, macros: list[list[MacroEvent]]) -> None:
        for i, (length, data) in enumerate(build_macros_dongle(macros)):
            self._xfer(0x09, length, i, data)
            time.sleep(0.002)

    def set_settings(self, s: Settings) -> None:
        self._xfer(0x07, 0x10, 0, s.data64()[:16])

    def set_clock(self, now: _dt.datetime | None = None, image: int = 0) -> None:
        d = clock_data(now, image)
        # p[3]=img+1 p[4]=5A p[5..10]=Y M D h m s p[12]=dow p[17..18]=AA 55
        self._xfer(0x0C, 0x10, 0, d[1:11] + b"\x00" * 4 + SIG)

    def battery(self) -> int | None:
        r = self._xfer(0x20, 0x01, 0)
        return min(100, r[3]) if r else None


# ================================================================= discovery
@dataclass
class Found:
    wired: HidrawInfo | None = None
    dongle: HidrawInfo | None = None
    problems: list[str] = field(default_factory=list)


def find_devices() -> Found:
    f = Found()
    for d in enumerate_hidraw():
        if (d.vid, d.pid) == (WIRED_VID, WIRED_PID) and any(c.feature_len == 64 for c in d.collections):
            f.wired = d
        elif (d.vid, d.pid) == (DONGLE_VID, DONGLE_PID) and any(
                c.usage_page == 0xFF60 and c.output_len == 32 for c in d.collections):
            f.dongle = d
    import os
    for d in (f.wired, f.dongle):
        if d and not os.access(d.path, os.R_OK | os.W_OK):
            f.problems.append(f"{d.path}: ruxsat yo'q (udev qoidasini o'rnating: install.sh)")
    return f


def open_keyboard(prefer: str | None = None):
    """Open the wired channel if present (like the vendor app), else the dongle."""
    f = find_devices()
    order = [prefer] if prefer else ["wired", "dongle"]
    for kind in order:
        info = getattr(f, kind)
        if info is None:
            continue
        try:
            return Wired(info) if kind == "wired" else Dongle(info)
        except PermissionError as e:
            raise DeviceError(f"{info.path}: ruxsat yo'q — install.sh ni ishga tushiring") from e
    raise DeviceError("AULA F108Pro topilmadi (USB kabel yoki 2.4G dongle ulanganini tekshiring)")
