"""Music rhythm mode: system audio -> spectrum -> per-key colours.

Audio comes from the default PipeWire sink monitor (pw-record); colours are
rendered on the PC and pushed with the USB real-time stream (04 20), the same
way the vendor driver does it in wired mode. Pure Python, no numpy.

    python3 -m aula_f108.music [--style spectrum|heat|pulse] [--seconds N]
"""
from __future__ import annotations

import argparse
import array
import colorsys
import fcntl
import math
import os
import select
import subprocess
import sys
import time

from .layout import Key, load_layout
from .protocol import DeviceError, Effect, open_keyboard

# Only one music stream may talk to the keyboard at a time (GUI or terminal):
# two simultaneous streams made the keyboard stop answering for 5 s.
LOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "aula-f108-music.lock")


class AlreadyRunning(DeviceError):
    pass


def _acquire_lock() -> int:
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # released automatically when the process exits
    except BlockingIOError:
        os.close(fd)
        raise AlreadyRunning("Musiqa rejimi allaqachon ishlayapti (GUI yoki terminalda). Avval uni to'xtating.")
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd

RATE = 22050
N = 1024
BANDS = 21
ROWS = 6


# ------------------------------------------------------------------ audio
class AudioSource:
    """Default sink monitor via pw-record, mono s16 @ 22.05 kHz."""

    def __init__(self):
        self.proc = subprocess.Popen(
            ["pw-record", "-a", "--rate", str(RATE), "--channels", "1", "--format", "s16",
             "--latency", "20ms", "-P", "{ stream.capture.sink=true }", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        os.set_blocking(self.proc.stdout.fileno(), False)
        self.buf = array.array("h", bytes(N * 2))
        self._rest = b""

    def latest(self) -> array.array:
        """Return the newest N samples (reads whatever is available)."""
        fd = self.proc.stdout.fileno()
        data = self._rest
        while select.select([fd], [], [], 0)[0]:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
        n = len(data) // 2 * 2
        self._rest = data[n:]
        if n:
            new = array.array("h")
            new.frombytes(data[:n])
            self.buf = (self.buf + new)[-N:]
        return self.buf

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(1)
        except subprocess.TimeoutExpired:
            self.proc.kill()


# ------------------------------------------------------------------ FFT
class Spectrum:
    def __init__(self):
        bits = N.bit_length() - 1
        self.rev = [int(f"{i:0{bits}b}"[::-1], 2) for i in range(N)]
        self.win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (N - 1)) for i in range(N)]
        self.tw = [complex(math.cos(-2 * math.pi * k / N), math.sin(-2 * math.pi * k / N)) for k in range(N // 2)]
        # log-spaced band edges (in FFT bins) from 40 Hz to 10 kHz, at least one bin each
        lo, hi = 40.0, 10000.0
        edges, last = [], 0
        for b in range(BANDS + 1):
            f = lo * (hi / lo) ** (b / BANDS)
            k = max(last + 1, int(round(f * N / RATE)))
            edges.append(k)
            last = k
        self.edges = edges
        self.peak = 1e-3
        self.levels = [0.0] * BANDS

    def fft(self, samples) -> list[complex]:
        a = [complex(samples[self.rev[i]] * self.win[self.rev[i]], 0) for i in range(N)]
        size = 2
        while size <= N:
            half, step = size // 2, N // size
            for start in range(0, N, size):
                for j in range(half):
                    t = self.tw[j * step] * a[start + j + half]
                    u = a[start + j]
                    a[start + j] = u + t
                    a[start + j + half] = u - t
            size *= 2
        return a

    def bands(self, samples) -> list[float]:
        X = self.fft(samples)
        raw = []
        for b in range(BANDS):
            k0, k1 = self.edges[b], self.edges[b + 1]
            e = sum(abs(X[k]) ** 2 for k in range(k0, k1)) / (k1 - k0)
            raw.append(math.sqrt(e) * (1 + b * 0.12))      # gentle treble tilt
        top = max(raw)
        self.peak = max(top, self.peak * 0.995, 3e4)        # slow auto-gain
        out = []
        for b, v in enumerate(raw):
            db = 20 * math.log10(v / self.peak + 1e-9)      # 0 dB = loudest recent
            lvl = max(0.0, min(1.0, (db + 36) / 36))
            prev = self.levels[b]
            lvl = lvl if lvl > prev else prev * 0.82        # fast attack, slow release
            out.append(lvl)
        self.levels = out
        return out


# ------------------------------------------------------------------ renderers
def _rgb(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, max(0.0, min(1.0, v)))
    return int(r * 255), int(g * 255), int(b * 255)


def render(style: str, keys: list[Key], levels: list[float], t: float):
    frame = []
    bass = max(levels[:4]) if levels else 0.0
    for k in keys:
        col = min(BANDS - 1, k.col)
        height = levels[col] * ROWS                    # bars grow from the bottom row
        from_bottom = (ROWS - 1) - k.row
        v = max(0.0, min(1.0, height - from_bottom))
        if style == "pulse":
            c = _rgb(t * 0.05 + col / BANDS * 0.3, 1.0, 0.15 + 0.85 * bass)
        elif style == "heat":
            c = _rgb(0.33 - 0.33 * (from_bottom / (ROWS - 1)), 1.0, v)   # green -> red
        else:  # spectrum: rainbow columns
            c = _rgb(col / BANDS + t * 0.02, 1.0, v)
        frame.append((k.light_index, c))
    return frame


# ------------------------------------------------------------------ main loop
DEFAULT_OPTS = {"style": "spectrum", "scheme": 2, "background": 0, "bg_brightness": 100, "gain": 1.0}


def run(opts: dict | None = None, seconds: float = 0, fps: float = 20, stop=None,
        on_frame=None, stats: dict | None = None) -> None:
    """USB: colours rendered here (opts['style']) and streamed.
    2.4G: column heights sent with command 0x0B; the keyboard renders them
    using opts['scheme'] / ['background'] / ['bg_brightness'].
    `opts` is read every frame, so it can be changed while running.
    on_frame(levels, kind, fps) is called after every frame (from this thread).
    Raises AlreadyRunning if another music stream is active."""
    lock = _acquire_lock()
    try:
        _run(opts, seconds, fps, stop, on_frame, stats)
    finally:
        os.close(lock)


def _run(opts, seconds, fps, stop, on_frame, stats) -> None:
    opts = opts if opts is not None else dict(DEFAULT_OPTS)
    layout = load_layout()
    kb = open_keyboard()
    audio, spec = AudioSource(), Spectrum()
    t0 = time.monotonic()
    frames = errors = lost = 0
    was_lit = True
    stats = stats if stats is not None else {}
    try:
        while not (stop and stop()):
            t = time.monotonic() - t0
            if seconds and t > seconds:
                break
            o = {**DEFAULT_OPTS, **opts}
            levels = [min(1.0, v * float(o["gain"])) for v in spec.bands(audio.latest())]
            try:
                if kb.kind == "wired":
                    kb.stream(render(o["style"], layout.keys, levels, t))
                else:
                    heights = [round(v * ROWS) for v in levels]
                    lit = any(heights)
                    if lit or was_lit:           # like the vendor app: idle while silent
                        if not kb.music(heights, o["scheme"], o["background"], o["bg_brightness"]):
                            lost += 1
                    was_lit = lit
                errors = 0
            except OSError as e:         # a stalled/lost USB transfer: back off, reopen, go on
                errors += 1
                print(f"USB xato ({e}); qayta urinish {errors}")
                if errors > 10:
                    raise
                time.sleep(0.2)
                kb.close()
                kb = open_keyboard()
                continue
            frames += 1
            if on_frame:
                on_frame(levels, kb.kind, frames / max(time.monotonic() - t0, 1e-6))
            sleep = 1 / fps - (time.monotonic() - t0 - t)
            if sleep > 0:
                time.sleep(sleep)
    finally:
        audio.close()
        dt = time.monotonic() - t0
        stats.update(frames=frames, fps=frames / max(dt, 1e-6), lost=lost, kind=kb.kind)
        print(f"{kb.kind}: {frames} kadr, {stats['fps']:.1f} fps" + (f", javobsiz: {lost}" if lost else ""))
        kb.close()


def main():
    ap = argparse.ArgumentParser(description="AULA F108Pro — musiqa ritmi")
    ap.add_argument("--style", choices=["spectrum", "heat", "pulse"], default="spectrum",
                    help="USB rejimida rang uslubi")
    ap.add_argument("--scheme", type=int, default=2, help="2.4G: ustun ranglari (1-11)")
    ap.add_argument("--background", type=int, default=0, help="2.4G: fon (0=o'chiq, 1-11)")
    ap.add_argument("--bg-brightness", type=int, default=100, help="2.4G: fon yorqinligi 0-100")
    ap.add_argument("--gain", type=float, default=1.0, help="sezgirlik (1.0 = standart)")
    ap.add_argument("--seconds", type=float, default=0, help="0 = Ctrl+C gacha")
    ap.add_argument("--restore", action="store_true", help="tugagach standart effektni qaytarish")
    a = ap.parse_args()
    try:
        run({"style": a.style, "scheme": a.scheme, "background": a.background,
             "bg_brightness": a.bg_brightness, "gain": a.gain}, a.seconds)
    except AlreadyRunning as e:
        print(e, file=sys.stderr)
        sys.exit(1)             # never touch the lighting of the instance that is running
    except KeyboardInterrupt:
        pass
    if a.restore:
        kb = open_keyboard()
        kb.set_effect(Effect())
        kb.close()


if __name__ == "__main__":
    main()
