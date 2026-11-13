"""Local profile storage (~/.config/aula-f108/profile.json).

The keyboard cannot report its key map, macros or settings back, so — like the
vendor app — we keep the source of truth on the PC and always upload full
tables.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from .protocol import (Effect, MacroEvent, Settings, MOUSE_ENTRIES, entry_consumer,
                       entry_default, entry_disabled, entry_key, entry_macro)

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "aula-f108")
PROFILE = os.path.join(CONFIG_DIR, "profile.json")


def spec_to_entry(spec: dict) -> bytes:
    t = spec.get("type")
    if t == "disabled":
        return entry_disabled()
    if t == "key":
        return entry_key(int(spec.get("usage", 0)), int(spec.get("mods", 0)))
    if t == "consumer":
        return entry_consumer(int(spec["usage"]))
    if t == "mouse":
        return MOUSE_ENTRIES[spec["button"]]
    if t == "macro":
        mode = int(spec.get("mode", 0))
        count = max(1, min(255, int(spec.get("count", 1)))) if mode == 1 else 0
        return entry_macro(int(spec["index"]), mode, count)
    return entry_default()


class Profile:
    def __init__(self):
        self.effect = Effect()
        self.user_colors: dict[int, tuple[int, int, int]] = {}
        self.user_brightness = 5
        self.keymap: dict[str, dict[int, dict]] = {"main": {}, "fn": {}}
        self.macros: list[dict] = []          # {"name": str, "events": [MacroEvent-as-dict]}
        self.settings = Settings()

    # -- (de)serialisation -------------------------------------------------
    def to_json(self) -> dict:
        return {
            "effect": asdict(self.effect),
            "user_colors": {str(k): list(v) for k, v in self.user_colors.items()},
            "user_brightness": self.user_brightness,
            "keymap": {layer: {str(k): v for k, v in m.items()} for layer, m in self.keymap.items()},
            "macros": self.macros,
            "settings": asdict(self.settings),
        }

    @classmethod
    def from_json(cls, d: dict) -> "Profile":
        p = cls()
        if "effect" in d:
            e = d["effect"]
            e["color"] = tuple(e.get("color", (255, 0, 0)))
            p.effect = Effect(**e)
        p.user_colors = {int(k): tuple(v) for k, v in d.get("user_colors", {}).items()}
        p.user_brightness = int(d.get("user_brightness", 5))
        for layer in ("main", "fn"):
            p.keymap[layer] = {int(k): v for k, v in d.get("keymap", {}).get(layer, {}).items()}
        p.macros = d.get("macros", [])
        if "settings" in d:
            p.settings = Settings(**d["settings"])
        return p

    @classmethod
    def load(cls, path: str = PROFILE) -> "Profile":
        try:
            with open(path) as f:
                return cls.from_json(json.load(f))
        except FileNotFoundError:
            return cls()

    def save(self, path: str = PROFILE) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_json(), f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)

    # -- helpers -----------------------------------------------------------
    def keymap_entries(self, layer: str) -> dict[int, bytes]:
        return {k: spec_to_entry(v) for k, v in self.keymap[layer].items()}

    def macro_events(self) -> list[list[MacroEvent]]:
        return [[MacroEvent(**e) for e in m.get("events", [])] for m in self.macros]
