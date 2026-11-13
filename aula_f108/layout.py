"""Keyboard layout (assets/layout.json).

Key indices and positions describe the F108Pro's physical layout; the
rectangles use an 800x300 drawing space.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


@dataclass
class Key:
    label: str         # legend drawn on the key
    code: int          # HID keyboard usage of the default key
    key_index: int     # position in the key-map tables sent to the device
    light_index: int   # position in the per-key LED tables
    row: int
    col: int
    x: int
    y: int
    w: int
    h: int
    fn_disabled: bool

    @property
    def name(self) -> str:
        from .keycodes import key_name
        return "Fn" if self.code == 0xAF else key_name(self.code)


@dataclass
class Layout:
    model: str
    keys: list[Key]
    width: int
    height: int
    cmd_delay_ms: int
    light_defaults: dict[str, int]
    menu: dict[str, int]
    menu_wireless: dict[str, int]
    functions: dict[str, int]
    screen: dict[str, int]

    def by_key_index(self) -> dict[int, Key]:
        return {k.key_index: k for k in self.keys}


def load_layout(path: str | None = None) -> Layout:
    path = path or os.path.join(ASSETS, "layout.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return Layout(
        model=d.get("model", ""),
        keys=[Key(**k) for k in d["keys"]],
        width=d.get("width", 800), height=d.get("height", 300),
        cmd_delay_ms=d.get("cmd_delay_ms", 35),
        light_defaults=d.get("light", {}), menu=d.get("menu", {}),
        menu_wireless=d.get("menu_wireless", {}), functions=d.get("functions", {}),
        screen=d.get("screen", {}))
