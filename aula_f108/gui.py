"""GTK4 / libadwaita control panel for the AULA F108Pro."""
from __future__ import annotations

import queue
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, GLib, Graphene, Gsk, Gtk, Pango  # noqa: E402

from . import keycodes as kc  # noqa: E402
from .config import Profile  # noqa: E402
from .layout import Key, load_layout  # noqa: E402
from .protocol import (BRIGHTNESS_MAX, EFFECTS, SPEED_MAX, DeviceError, Effect,  # noqa: E402
                       find_devices, open_keyboard)
from .settings_values import (FN_SWITCH, KEY_RESPOND, MACRO_MODES, SLEEP_TIME)  # noqa: E402

APP_ID = "uz.local.AulaF108"


# ======================================================================= worker
class Worker:
    """Runs device jobs one at a time off the GTK main thread."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, job, done=None, error=None):
        self.q.put((job, done, error))

    def _run(self):
        while True:
            job, done, error = self.q.get()
            self.busy = True
            try:
                kb = open_keyboard()
                try:
                    res = job(kb)
                finally:
                    kb.close()
                if done:
                    GLib.idle_add(done, res)
            except Exception as e:  # noqa: BLE001
                if error:
                    GLib.idle_add(error, e)
            finally:
                self.busy = False


def rgba_to_tuple(c: Gdk.RGBA) -> tuple[int, int, int]:
    return (round(c.red * 255), round(c.green * 255), round(c.blue * 255))


def tuple_to_rgba(t) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = t[0] / 255, t[1] / 255, t[2] / 255, 1.0
    return c


def string_combo(title: str, items: list[str], subtitle: str = "") -> Adw.ComboRow:
    row = Adw.ComboRow(title=title, subtitle=subtitle)
    row.set_model(Gtk.StringList.new(items))
    return row


def scale_row(title: str, lo: int, hi: int) -> tuple[Adw.ActionRow, Gtk.Scale]:
    row = Adw.ActionRow(title=title)
    sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
    sc.set_digits(0)
    sc.set_draw_value(True)
    sc.set_hexpand(True)
    sc.set_size_request(260, -1)
    for v in range(lo, hi + 1):
        sc.add_mark(v, Gtk.PositionType.BOTTOM, None)
    row.add_suffix(sc)
    return row, sc


# ================================================================ keyboard view
def _rgba(t) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = t
    return c


def _rect(x, y, w, h) -> Graphene.Rect:
    return Graphene.Rect().init(x, y, w, h)


class KeyboardView(Gtk.Widget):
    """Draws the keyboard from layout.json with per-key decorations; click/drag picks keys."""
    __gtype_name__ = "AulaKeyboardView"

    def __init__(self, layout, decorate, on_key, drag_paint: bool = False):
        super().__init__()
        self.layout = layout
        self.decorate = decorate          # key -> (fill rgba tuple|None, outline rgba|None, label|None)
        self.on_key = on_key
        pad = 12
        self.bx = min(k.x for k in layout.keys) - pad
        self.by = min(k.y for k in layout.keys) - pad
        self.iw = max(k.x + k.w for k in layout.keys) + pad - self.bx
        self.ih = max(k.y + k.h for k in layout.keys) + pad - self.by
        self.set_hexpand(True)
        self._font = Pango.FontDescription.from_string("Sans Bold 6.5")
        self._legend_font = Pango.FontDescription.from_string("Sans 6")
        self._geom = (1.0, 0.0, 0.0)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda g, n, x, y: self._hit(x, y))
        self.add_controller(click)
        if drag_paint:
            drag = Gtk.GestureDrag()
            drag.connect("drag-update", self._drag)
            self.add_controller(drag)

    def _drag(self, g, dx, dy):
        ok, x, y = g.get_start_point()
        if ok:
            self._hit(x + dx, y + dy)

    def _hit(self, x, y):
        s, ox, oy = self._geom
        px, py = (x - ox) / s + self.bx, (y - oy) / s + self.by
        for k in self.layout.keys:
            if k.x <= px <= k.x + k.w and k.y <= py <= k.y + k.h:
                self.on_key(k)
                return

    @staticmethod
    def _rounded(snap, rect, radius, color):
        rr = Gsk.RoundedRect()          # keep a reference: init_from_rect returns a borrowed view
        rr.init_from_rect(rect, radius)
        snap.push_rounded_clip(rr)
        snap.append_color(_rgba(color), rect)
        snap.pop()

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 480, self.iw, -1, -1
        return 180, self.ih, -1, -1

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        s = min(w / self.iw, h / self.ih)
        ox, oy = (w - self.iw * s) / 2, (h - self.ih * s) / 2
        self._geom = (s, ox, oy)
        snap.save()
        snap.translate(Graphene.Point().init(ox, oy))
        snap.scale(s, s)
        snap.translate(Graphene.Point().init(-self.bx, -self.by))
        self._rounded(snap, _rect(self.bx, self.by, self.iw, self.ih), 14, (0.13, 0.13, 0.15, 1))
        for k in self.layout.keys:
            fill, outline, label = self.decorate(k)
            r = _rect(k.x, k.y, k.w, k.h)
            self._rounded(snap, r, 4, (0.30, 0.30, 0.33, 1))
            if fill:
                self._rounded(snap, r, 4, fill)
            if k.label:
                lay = self.create_pango_layout(k.label)
                lay.set_font_description(self._legend_font)
                lay.set_width(int(k.w * Pango.SCALE))
                lay.set_alignment(Pango.Alignment.CENTER)
                snap.save()
                snap.translate(Graphene.Point().init(k.x, k.y + 3))
                snap.append_layout(lay, _rgba((0.93, 0.93, 0.95, 1)))
                snap.restore()
            if outline:
                c, t = _rgba(outline), 2.5
                x0, y0, x1, y1 = k.x - 3, k.y - 3, k.x + k.w + 3, k.y + k.h + 3
                for r in (_rect(x0, y0, x1 - x0, t), _rect(x0, y1 - t, x1 - x0, t),
                          _rect(x0, y0, t, y1 - y0), _rect(x1 - t, y0, t, y1 - y0)):
                    snap.append_color(c, r)
            if label:
                lay = self.create_pango_layout(label)
                lay.set_font_description(self._font)
                lay.set_width(int((k.w + 6) * Pango.SCALE))
                lay.set_ellipsize(Pango.EllipsizeMode.END)
                lay.set_alignment(Pango.Alignment.CENTER)
                _lw, lh = lay.get_pixel_size()
                snap.append_color(_rgba((0, 0, 0, 0.78)), _rect(k.x - 3, k.y + k.h - lh, k.w + 6, lh))
                snap.save()
                snap.translate(Graphene.Point().init(k.x - 3, k.y + k.h - lh))
                snap.append_layout(lay, _rgba((1, 0.85, 0.3, 1)))
                snap.restore()
        snap.restore()


# ===================================================================== pages
class LightingPage(Adw.PreferencesPage):
    def __init__(self, app_win):
        super().__init__(title="Yorug'lik", icon_name="weather-clear-symbolic")
        self.w = app_win
        eff = app_win.profile.effect
        self.modes = sorted(EFFECTS)

        g = Adw.PreferencesGroup(title="Yorug'lik effekti",
                                 description="Klaviaturaning o'rnatilgan effektlari (xotirasida saqlanadi).")
        self.add(g)
        self.mode = string_combo("Effekt", [EFFECTS[m][0] for m in self.modes])
        self.mode.set_selected(self.modes.index(eff.mode) if eff.mode in self.modes else 11)
        self.mode.connect("notify::selected", lambda *a: self._sync())
        g.add(self.mode)

        self.colorful = Adw.SwitchRow(title="Rang-barang (kamalak)", active=eff.colorful)
        self.colorful.connect("notify::active", lambda *a: self._sync())
        g.add(self.colorful)

        self.color_row = Adw.ActionRow(title="Rang")
        self.color_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
        self.color_btn.set_rgba(tuple_to_rgba(eff.color))
        self.color_btn.set_valign(Gtk.Align.CENTER)
        self.color_row.add_suffix(self.color_btn)
        g.add(self.color_row)

        self.bright_row, self.bright = scale_row("Yorqinlik", 0, BRIGHTNESS_MAX)
        self.bright.set_value(eff.brightness)
        g.add(self.bright_row)
        self.speed_row, self.speed = scale_row("Tezlik", 0, SPEED_MAX)
        self.speed.set_value(eff.speed)
        g.add(self.speed_row)
        self.dir = string_combo("Yo'nalish", ["1-yo'nalish", "2-yo'nalish"])
        g.add(self.dir)
        self._dir_values = (1, 0)
        self._initial_dir = eff.direction

        g2 = Adw.PreferencesGroup()
        self.add(g2)
        btn = Gtk.Button(label="Klaviaturaga yozish", css_classes=["suggested-action", "pill"],
                         halign=Gtk.Align.CENTER)
        btn.connect("clicked", self._apply)
        g2.add(btn)
        self._sync(first=True)

    def _sync(self, first=False):
        mode = self.modes[self.mode.get_selected()]
        flags = EFFECTS[mode][1]
        self.colorful.set_sensitive("C" in flags)
        self.color_row.set_sensitive("C" in flags and not self.colorful.get_active())
        self.bright_row.set_sensitive("B" in flags)
        self.speed_row.set_sensitive("S" in flags)
        has_dir = "D" in flags or "V" in flags
        self.dir.set_sensitive(has_dir)
        self._dir_values = (2, 3) if "V" in flags else (1, 0)
        if first and self._initial_dir in self._dir_values:
            self.dir.set_selected(self._dir_values.index(self._initial_dir))

    def current(self) -> Effect:
        mode = self.modes[self.mode.get_selected()]
        flags = EFFECTS[mode][1]
        return Effect(
            mode=mode,
            color=rgba_to_tuple(self.color_btn.get_rgba()),
            colorful=self.colorful.get_active() if "C" in flags else True,
            brightness=int(self.bright.get_value()),
            speed=int(self.speed.get_value()),
            direction=self._dir_values[self.dir.get_selected()] if ("D" in flags or "V" in flags) else 0)

    def _apply(self, *_):
        eff = self.current()
        self.w.profile.effect = eff
        self.w.profile.save()
        self.w.run(lambda kb: kb.set_effect(eff), f"Effekt: {EFFECTS[eff.mode][0]}")


class PerKeyPage(Gtk.Box):
    def __init__(self, app_win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                         margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.w = app_win
        self.colors: dict[int, tuple[int, int, int]] = dict(app_win.profile.user_colors)

        info = Gtk.Label(wrap=True, xalign=0, css_classes=["dim-label"],
                         label="Rangni tanlang, so'ng tugmalar ustida bosing yoki sudrab bo'yang. "
                               "Tayyor bo'lgach «Klaviaturaga yozish» tugmasini bosing.")
        self.append(info)

        bar = Gtk.Box(spacing=8)
        self.append(bar)
        bar.append(Gtk.Label(label="Mo'yqalam:"))
        self.brush = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
        self.brush.set_rgba(tuple_to_rgba((0, 160, 255)))
        bar.append(self.brush)
        eraser = Gtk.ToggleButton(icon_name="edit-clear-symbolic", tooltip_text="O'chirg'ich (rangsiz)")
        self.eraser = eraser
        bar.append(eraser)
        for label, cb in (("Hammasini bo'yash", self._fill_all), ("Tozalash", self._clear),
                          ("Klaviaturadan o'qish", self._read)):
            b = Gtk.Button(label=label)
            b.connect("clicked", cb)
            bar.append(b)
        spacer = Gtk.Box(hexpand=True)
        bar.append(spacer)
        bar.append(Gtk.Label(label="Yorqinlik"))
        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, BRIGHTNESS_MAX, 1)
        self.bright.set_digits(0)
        self.bright.set_size_request(140, -1)
        self.bright.set_value(app_win.profile.user_brightness)
        bar.append(self.bright)

        self.view = KeyboardView(app_win.layout, self._decorate, self._paint, drag_paint=True)
        self.view.set_vexpand(True)
        self.append(self.view)

        apply = Gtk.Button(label="Klaviaturaga yozish", css_classes=["suggested-action", "pill"],
                           halign=Gtk.Align.CENTER)
        apply.connect("clicked", self._apply)
        self.append(apply)

    def _decorate(self, k: Key):
        c = self.colors.get(k.light_index)
        if not c:
            return None, None, None
        return (c[0] / 255, c[1] / 255, c[2] / 255, 0.8), None, None

    def _paint(self, k: Key):
        if self.eraser.get_active():
            self.colors.pop(k.light_index, None)
        else:
            self.colors[k.light_index] = rgba_to_tuple(self.brush.get_rgba())
        self.view.queue_draw()

    def _fill_all(self, *_):
        c = rgba_to_tuple(self.brush.get_rgba())
        self.colors = {k.light_index: c for k in self.w.layout.keys}
        self.view.queue_draw()

    def _clear(self, *_):
        self.colors = {}
        self.view.queue_draw()

    def _read(self, *_):
        def done(cols):
            self.colors = {li: c for li, c in cols.items() if any(c)}
            self.view.queue_draw()
            self.w.toast("Joriy ranglar klaviaturadan o'qildi")
        self.w.run(lambda kb: kb.read_colors(), None, done=done)

    def _apply(self, *_):
        cols = dict(self.colors)
        br = int(self.bright.get_value())
        self.w.profile.user_colors = cols
        self.w.profile.user_brightness = br
        self.w.profile.save()
        self.w.run(lambda kb: kb.set_user_light(cols, br), "Tugma ranglari yozildi")


KEY_TYPES = [("default", "Standart (zavod)"), ("disabled", "O'chirilgan"),
             ("key", "Boshqa tugma / kombinatsiya"), ("consumer", "Multimedia"),
             ("mouse", "Sichqoncha"), ("macro", "Makros")]


def spec_label(spec: dict, profile: Profile) -> str:
    t = spec.get("type")
    if t == "disabled":
        return "✕"
    if t == "key":
        return kc.combo_name(spec.get("usage", 0), spec.get("mods", 0))
    if t == "consumer":
        return kc.CONSUMER_NAMES.get(spec["usage"], "Media")
    if t == "mouse":
        return kc.MOUSE_NAMES.get(spec["button"], "Mouse")
    if t == "macro":
        i = spec["index"]
        return profile.macros[i]["name"] if i < len(profile.macros) else f"Makros {i + 1}"
    return ""


class KeysPage(Gtk.Box):
    def __init__(self, app_win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                         margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.w = app_win
        self.layer = "main"
        self.sel: Key | None = None
        self._keys = kc.selectable_keys()

        top = Gtk.Box(spacing=0, css_classes=["linked"], halign=Gtk.Align.CENTER)
        self.b_main = Gtk.ToggleButton(label="Asosiy qatlam", active=True)
        self.b_fn = Gtk.ToggleButton(label="Fn qatlami", group=self.b_main)
        self.b_main.connect("toggled", self._layer_changed)
        top.append(self.b_main)
        top.append(self.b_fn)
        self.append(top)

        self.view = KeyboardView(app_win.layout, self._decorate, self._select)
        self.view.set_vexpand(True)
        self.append(self.view)

        page = Adw.PreferencesGroup(title="Tanlangan tugma", description="Tugmani rasmda bosib tanlang.")
        self.group = page
        self.append(page)
        self.type = string_combo("Vazifa", [n for _t, n in KEY_TYPES])
        self.type.connect("notify::selected", lambda *a: self._type_changed())
        page.add(self.type)
        self.value = Adw.ComboRow(title="Qiymat", enable_search=True)
        self.value.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        page.add(self.value)
        self.mods_row = Adw.ActionRow(title="Modifikatorlar")
        self.mod_btns = []
        mb = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        for bit, name in kc.MODIFIERS[:4]:
            b = Gtk.ToggleButton(label=name)
            b.bit = bit
            mb.append(b)
            self.mod_btns.append(b)
        self.mods_row.add_suffix(mb)
        page.add(self.mods_row)
        self.macro_mode = string_combo("Ijro rejimi", [n for _v, n in MACRO_MODES])
        page.add(self.macro_mode)
        self.count_row = Adw.SpinRow.new_with_range(1, 255, 1)
        self.count_row.set_title("Takrorlar soni")
        page.add(self.count_row)

        btns = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=6)
        for label, cb, css in (("Belgilash", self._assign, []),
                               ("Bu tugmani tiklash", self._reset_one, []),
                               ("Klaviaturaga yozish", self._apply, ["suggested-action"])):
            b = Gtk.Button(label=label, css_classes=["pill"] + css)
            b.connect("clicked", cb)
            btns.append(b)
        self.append(btns)
        self._type_changed()
        self.group.set_sensitive(False)

    # -- helpers
    def _layer_changed(self, *_):
        self.layer = "main" if self.b_main.get_active() else "fn"
        self._load_selection()
        self.view.queue_draw()

    def _decorate(self, k: Key):
        spec = self.w.profile.keymap[self.layer].get(k.key_index)
        fill = (1, 0.6, 0, 0.35) if spec else None
        outline = (0.2, 0.7, 1, 1) if self.sel is k else None
        return fill, outline, spec_label(spec, self.w.profile) if spec else None

    def _select(self, k: Key):
        if self.layer == "fn" and k.fn_disabled:
            self.w.toast("Bu tugmani Fn qatlamida o'zgartirib bo'lmaydi")
            return
        self.sel = k
        self.group.set_title(f"Tanlangan tugma: {k.name}")
        self.group.set_sensitive(True)
        self._load_selection()
        self.view.queue_draw()

    def _type_changed(self):
        t = KEY_TYPES[self.type.get_selected()][0]
        if t == "key":
            items = [n for _u, n in self._keys]
        elif t == "consumer":
            items = [n for _u, n in kc.CONSUMER]
        elif t == "mouse":
            items = [n for _b, n in kc.MOUSE]
        elif t == "macro":
            items = [m["name"] for m in self.w.profile.macros] or ["(avval makros yarating)"]
        else:
            items = []
        self.value.set_model(Gtk.StringList.new(items))
        self.value.set_visible(bool(items))
        self.mods_row.set_visible(t == "key")
        self.macro_mode.set_visible(t == "macro")
        self.count_row.set_visible(t == "macro")

    def _load_selection(self):
        if not self.sel:
            return
        spec = self.w.profile.keymap[self.layer].get(self.sel.key_index, {"type": "default"})
        types = [t for t, _n in KEY_TYPES]
        self.type.set_selected(types.index(spec.get("type", "default")))
        self._type_changed()
        t = spec.get("type")
        for b in self.mod_btns:
            b.set_active(bool(spec.get("mods", 0) & b.bit) if t == "key" else False)
        if t == "key":
            usages = [u for u, _n in self._keys]
            if spec.get("usage") in usages:
                self.value.set_selected(usages.index(spec["usage"]))
        elif t == "consumer":
            us = [u for u, _n in kc.CONSUMER]
            if spec["usage"] in us:
                self.value.set_selected(us.index(spec["usage"]))
        elif t == "mouse":
            bs = [b for b, _n in kc.MOUSE]
            self.value.set_selected(bs.index(spec["button"]))
        elif t == "macro":
            self.value.set_selected(min(spec["index"], max(0, len(self.w.profile.macros) - 1)))
            vals = [v for v, _n in MACRO_MODES]
            if spec.get("mode") in vals:
                self.macro_mode.set_selected(vals.index(spec["mode"]))
            self.count_row.set_value(spec.get("count", 1))

    def _assign(self, *_):
        if not self.sel:
            return
        t = KEY_TYPES[self.type.get_selected()][0]
        i = self.value.get_selected()
        if t == "default":
            self.w.profile.keymap[self.layer].pop(self.sel.key_index, None)
        else:
            if t == "disabled":
                spec = {"type": "disabled"}
            elif t == "key":
                mods = sum(b.bit for b in self.mod_btns if b.get_active())
                spec = {"type": "key", "usage": self._keys[i][0], "mods": mods}
            elif t == "consumer":
                spec = {"type": "consumer", "usage": kc.CONSUMER[i][0]}
            elif t == "mouse":
                spec = {"type": "mouse", "button": kc.MOUSE[i][0]}
            else:
                if not self.w.profile.macros:
                    self.w.toast("Avval «Makroslar» bo'limida makros yarating")
                    return
                spec = {"type": "macro", "index": i,
                        "mode": MACRO_MODES[self.macro_mode.get_selected()][0],
                        "count": int(self.count_row.get_value())}
            self.w.profile.keymap[self.layer][self.sel.key_index] = spec
        self.w.profile.save()
        self.view.queue_draw()

    def _reset_one(self, *_):
        if self.sel:
            self.w.profile.keymap[self.layer].pop(self.sel.key_index, None)
            self.w.profile.save()
            self._load_selection()
            self.view.queue_draw()

    def _apply(self, *_):
        p = self.w.profile
        main, fn = p.keymap_entries("main"), p.keymap_entries("fn")

        def job(kb):
            kb.set_keymap(main, fn_layer=False)
            kb.set_keymap(fn, fn_layer=True)
        self.w.run(job, "Tugmalar xaritasi yozildi")


class MacrosPage(Gtk.Box):
    def __init__(self, app_win):
        super().__init__(spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.w = app_win
        self.cur = -1
        self.recording = False
        self._last_t = 0.0

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=220)
        self.append(left)
        left.append(Gtk.Label(label="Makroslar", xalign=0, css_classes=["heading"]))
        sw = Gtk.ScrolledWindow(vexpand=True)
        self.mlist = Gtk.ListBox(css_classes=["boxed-list"])
        self.mlist.connect("row-selected", self._macro_selected)
        sw.set_child(self.mlist)
        left.append(sw)
        lb = Gtk.Box(css_classes=["linked"])
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Yangi makros")
        add.connect("clicked", self._add_macro)
        rm = Gtk.Button(icon_name="list-remove-symbolic", tooltip_text="Makrosni o'chirish")
        rm.connect("clicked", self._remove_macro)
        lb.append(add)
        lb.append(rm)
        left.append(lb)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        self.append(right)
        self.name = Gtk.Entry(placeholder_text="Makros nomi")
        self.name.connect("changed", self._rename)
        right.append(self.name)
        bar = Gtk.Box(spacing=6)
        self.rec = Gtk.ToggleButton(label="● Yozib olish")
        self.rec.connect("toggled", self._toggle_rec)
        bar.append(self.rec)
        self.rec_delays = Gtk.CheckButton(label="Haqiqiy kechikishlar", active=True)
        bar.append(self.rec_delays)
        self.delay_spin = Gtk.SpinButton.new_with_range(10, 65535, 10)
        self.delay_spin.set_value(50)
        add_d = Gtk.Button(label="+ Kechikish (ms)")
        add_d.connect("clicked", lambda *a: self._append({"kind": "delay", "code": int(self.delay_spin.get_value()), "down": True}))
        bar.append(add_d)
        bar.append(self.delay_spin)
        del_ev = Gtk.Button(icon_name="edit-delete-symbolic", tooltip_text="Tanlangan hodisani o'chirish")
        del_ev.connect("clicked", self._del_event)
        bar.append(del_ev)
        clr = Gtk.Button(label="Tozalash")
        clr.connect("clicked", self._clear_events)
        bar.append(clr)
        right.append(bar)
        self.hint = Gtk.Label(xalign=0, css_classes=["dim-label"], wrap=True,
                              label="«Yozib olish»ni yoqing va tugmalarni bosing. Super va Alt+Tab kabi "
                                    "tizim tugmalarini GNOME ushlab qolishi mumkin.")
        right.append(self.hint)
        sw2 = Gtk.ScrolledWindow(vexpand=True)
        self.elist = Gtk.ListBox(css_classes=["boxed-list"])
        sw2.set_child(self.elist)
        right.append(sw2)
        up = Gtk.Button(label="Barcha makroslarni klaviaturaga yozish",
                        css_classes=["suggested-action", "pill"], halign=Gtk.Align.CENTER)
        up.connect("clicked", self._apply)
        right.append(up)

        keyc = Gtk.EventControllerKey()
        keyc.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keyc.connect("key-pressed", lambda c, kv, code, st: self._key(code, True))
        keyc.connect("key-released", lambda c, kv, code, st: self._key(code, False))
        app_win.add_controller(keyc)
        self._reload_list()

    # -- macro list
    def _reload_list(self):
        while (r := self.mlist.get_row_at_index(0)) is not None:
            self.mlist.remove(r)
        for m in self.w.profile.macros:
            self.mlist.append(Gtk.Label(label=m["name"], xalign=0, margin_top=8, margin_bottom=8, margin_start=8))
        if self.w.profile.macros:
            self.mlist.select_row(self.mlist.get_row_at_index(max(0, min(self.cur, len(self.w.profile.macros) - 1))))
        else:
            self.cur = -1
            self._reload_events()

    def _macro_selected(self, lb, row):
        self.cur = row.get_index() if row else -1
        self.name.set_text(self.w.profile.macros[self.cur]["name"] if self.cur >= 0 else "")
        self._reload_events()

    def _add_macro(self, *_):
        if len(self.w.profile.macros) >= 100:
            return
        self.w.profile.macros.append({"name": f"Makros {len(self.w.profile.macros) + 1}", "events": []})
        self.cur = len(self.w.profile.macros) - 1
        self.w.profile.save()
        self._reload_list()

    def _remove_macro(self, *_):
        if self.cur < 0:
            return
        del self.w.profile.macros[self.cur]
        # keep key assignments pointing at the right slots
        for layer in self.w.profile.keymap.values():
            for k, spec in list(layer.items()):
                if spec.get("type") == "macro":
                    if spec["index"] == self.cur:
                        del layer[k]
                    elif spec["index"] > self.cur:
                        spec["index"] -= 1
        self.cur -= 1
        self.w.profile.save()
        self._reload_list()

    def _rename(self, entry):
        if self.cur >= 0:
            self.w.profile.macros[self.cur]["name"] = entry.get_text() or f"Makros {self.cur + 1}"
            row = self.mlist.get_row_at_index(self.cur)
            if row:
                row.get_child().set_label(self.w.profile.macros[self.cur]["name"])
            self.w.profile.save()

    # -- events
    def _events(self):
        return self.w.profile.macros[self.cur]["events"] if self.cur >= 0 else None

    @staticmethod
    def _ev_text(e):
        if e["kind"] == "delay":
            return f"⏱  {e['code']} ms"
        arrow = "↓" if e["down"] else "↑"
        if e["kind"] == "mouse":
            return f"{arrow}  Sichqoncha {e['code']}"
        return f"{arrow}  {kc.key_name(e['code'])}"

    def _reload_events(self):
        while (r := self.elist.get_row_at_index(0)) is not None:
            self.elist.remove(r)
        for e in self._events() or []:
            self.elist.append(Gtk.Label(label=self._ev_text(e), xalign=0, margin_top=4, margin_bottom=4, margin_start=8))

    def _append(self, e):
        evs = self._events()
        if evs is None:
            self.w.toast("Avval makros yarating")
            return
        evs.append(e)
        self.elist.append(Gtk.Label(label=self._ev_text(e), xalign=0, margin_top=4, margin_bottom=4, margin_start=8))
        self.w.profile.save()

    def _del_event(self, *_):
        row = self.elist.get_selected_row()
        if row and self._events() is not None:
            del self._events()[row.get_index()]
            self.w.profile.save()
            self._reload_events()

    def _clear_events(self, *_):
        if self._events() is not None:
            self._events().clear()
            self.w.profile.save()
            self._reload_events()

    def _toggle_rec(self, b):
        self.recording = b.get_active()
        b.set_label("■ To'xtatish" if self.recording else "● Yozib olish")
        self._last_t = 0.0
        if self.recording:
            self.w.toast("Yozib olinmoqda — tugmalarni bosing")

    def _key(self, code, down):
        if not self.recording or not self.get_mapped():
            return False
        usage = kc.EVDEV_TO_HID.get(code - 8)
        if usage is None:
            return True
        now = time.monotonic()
        if self._last_t:
            ms = int((now - self._last_t) * 1000) if self.rec_delays.get_active() else int(self.delay_spin.get_value())
            self._append({"kind": "delay", "code": max(10, min(65535, ms)), "down": True})
        self._last_t = now
        self._append({"kind": "key", "code": usage, "down": down})
        return True

    def _apply(self, *_):
        macros = self.w.profile.macro_events()
        self.w.run(lambda kb: kb.set_macros(macros), f"{len(macros)} ta makros yozildi")


class SettingsPage(Adw.PreferencesPage):
    def __init__(self, app_win):
        super().__init__(title="Sozlamalar", icon_name="emblem-system-symbolic")
        self.w = app_win
        s = app_win.profile.settings

        g = Adw.PreferencesGroup(title="Bloklash (o'yin rejimi)")
        self.add(g)
        self.win = Adw.SwitchRow(title="Windows (Super) tugmasini o'chirish", active=s.win_lock)
        self.altf4 = Adw.SwitchRow(title="Alt + F4 ni o'chirish", active=s.altf4_lock)
        self.alttab = Adw.SwitchRow(title="Alt + Tab ni o'chirish", active=s.alttab_lock)
        for r in (self.win, self.altf4, self.alttab):
            g.add(r)

        g2 = Adw.PreferencesGroup(title="Funksiyalar")
        self.add(g2)
        self.fn = self._combo(g2, "Fn tugmasi rejimi", FN_SWITCH, s.fn_switch)
        self.sleep = self._combo(g2, "Uyqu vaqti", SLEEP_TIME, s.sleep_time)
        self.resp = self._combo(g2, "Tugma javob vaqti (debounce)", KEY_RESPOND, s.key_respond)
        btn = Gtk.Button(label="Sozlamalarni yozish", css_classes=["suggested-action", "pill"],
                         halign=Gtk.Align.CENTER, margin_top=12)
        btn.connect("clicked", self._apply)
        g2.add(btn)

        g3 = Adw.PreferencesGroup(title="Ekran", description="Klaviatura ekranidagi soatni kompyuter vaqtiga moslash.")
        self.add(g3)
        row = Adw.ActionRow(title="Soatni sinxronlash")
        b = Gtk.Button(label="Sinxronlash", valign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *a: self.w.run(lambda kb: kb.set_clock(), "Soat sinxronlandi"))
        row.add_suffix(b)
        g3.add(row)

        g4 = Adw.PreferencesGroup(title="Tiklash")
        self.add(g4)
        r1 = Adw.ActionRow(title="Tugmalar xaritasini tiklash",
                           subtitle="Ikkala qatlamdagi barcha o'zgartirishlar o'chadi.")
        b1 = Gtk.Button(label="Tiklash", valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
        b1.connect("clicked", lambda *a: self._confirm("Tugmalar xaritasi tiklansinmi?", self._reset_keys))
        r1.add_suffix(b1)
        g4.add(r1)
        r2 = Adw.ActionRow(title="Zavod sozlamalari",
                           subtitle="Tugmalar, makroslar, yorug'lik va sozlamalar standart holatga qaytadi.")
        b2 = Gtk.Button(label="Tiklash", valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
        b2.connect("clicked", lambda *a: self._confirm("Barcha sozlamalar zavod holatiga qaytarilsinmi?", self._factory))
        r2.add_suffix(b2)
        g4.add(r2)

    @staticmethod
    def _combo(group, title, options, value):
        row = string_combo(title, [n for _v, n in options])
        vals = [v for v, _n in options]
        row.set_selected(vals.index(value) if value in vals else 0)
        row.values = vals
        group.add(row)
        return row

    def current(self):
        s = self.w.profile.settings
        s.win_lock = self.win.get_active()
        s.altf4_lock = self.altf4.get_active()
        s.alttab_lock = self.alttab.get_active()
        s.fn_switch = self.fn.values[self.fn.get_selected()]
        s.sleep_time = self.sleep.values[self.sleep.get_selected()]
        s.key_respond = self.resp.values[self.resp.get_selected()]
        return s

    def _apply(self, *_):
        s = self.current()
        self.w.profile.save()
        self.w.run(lambda kb: kb.set_settings(s), "Sozlamalar yozildi")

    def _confirm(self, text, action):
        d = Adw.AlertDialog(heading=text)
        d.add_response("cancel", "Bekor qilish")
        d.add_response("ok", "Tiklash")
        d.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda dlg, r: action() if r == "ok" else None)
        d.present(self.w)

    def _reset_keys(self):
        self.w.profile.keymap = {"main": {}, "fn": {}}
        self.w.profile.save()

        def job(kb):
            kb.set_keymap({}, fn_layer=False)
            kb.set_keymap({}, fn_layer=True)
        self.w.run(job, "Tugmalar xaritasi tiklandi")
        self.w.keys_page.view.queue_draw()

    def _factory(self):
        from .protocol import Settings
        p = Profile()
        self.w.profile.keymap, self.w.profile.macros = p.keymap, p.macros
        self.w.profile.effect, self.w.profile.settings = p.effect, Settings()
        self.w.profile.user_colors = {}
        self.w.profile.save()

        def job(kb):
            kb.set_macros([])
            kb.set_keymap({}, fn_layer=False)
            kb.set_keymap({}, fn_layer=True)
            kb.set_settings(Settings())
            kb.set_effect(Effect())
        self.w.run(job, "Zavod sozlamalari tiklandi — dasturni qayta oching")


# ===================================================================== window
class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AULA F108Pro", default_width=1040, default_height=760)
        self.layout = load_layout()
        self.profile = Profile.load()
        self.worker = Worker()

        self.toasts = Adw.ToastOverlay()
        tv = Adw.ToolbarView()
        self.toasts.set_child(tv)
        self.set_content(self.toasts)

        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title="AULA F108Pro", subtitle="…")
        stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        self.status_lbl = Gtk.Label(css_classes=["dim-label"])
        header.pack_start(self.status_lbl)
        self.spinner = Adw.Spinner(visible=False)
        header.pack_end(self.spinner)
        tv.add_top_bar(header)
        tv.set_content(stack)

        self.light_page = LightingPage(self)
        self.perkey_page = PerKeyPage(self)
        self.keys_page = KeysPage(self)
        self.macros_page = MacrosPage(self)
        self.settings_page = SettingsPage(self)
        stack.add_titled_with_icon(self.light_page, "light", "Yorug'lik", "weather-clear-symbolic")
        stack.add_titled_with_icon(self.perkey_page, "perkey", "Ranglar", "applications-graphics-symbolic")
        stack.add_titled_with_icon(self.keys_page, "keys", "Tugmalar", "input-keyboard-symbolic")
        stack.add_titled_with_icon(self.macros_page, "macros", "Makroslar", "media-record-symbolic")
        stack.add_titled_with_icon(self.settings_page, "settings", "Sozlamalar", "emblem-system-symbolic")
        stack.connect("notify::visible-child", lambda *a: self.keys_page._type_changed())

        self._battery = None
        self._refresh_status()
        GLib.timeout_add_seconds(2, self._refresh_status)
        GLib.timeout_add_seconds(30, self._poll_battery)
        self._poll_battery()

    # -- status
    def _refresh_status(self):
        f = find_devices()
        if f.wired:
            txt = "● USB (simli)"
            bad = f.wired.path
        elif f.dongle:
            txt = "● 2.4G dongle" + (f"  🔋{self._battery}%" if self._battery is not None else "")
            bad = f.dongle.path
        else:
            txt, bad = "○ Klaviatura topilmadi", None
        if bad and any(p.startswith(bad + ":") for p in f.problems):
            txt = "⚠ Ruxsat yo'q — install.sh ni ishga tushiring"
        self.status_lbl.set_label(txt)
        return True

    def _poll_battery(self):
        f = find_devices()
        if f.dongle and not f.wired and not f.problems and not self.worker.busy:
            def done(v):
                self._battery = v
                self._refresh_status()
            self.worker.submit(lambda kb: kb.battery(), done, lambda e: None)
        return True

    # -- helpers
    def toast(self, text: str):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def run(self, job, ok_text: str | None, done=None):
        self.spinner.set_visible(True)

        def _done(res):
            self.spinner.set_visible(False)
            if ok_text:
                self.toast(ok_text)
            if done:
                done(res)

        def _err(e):
            self.spinner.set_visible(False)
            msg = str(e) if isinstance(e, DeviceError) else f"Xato: {e}"
            self.toast(msg)
            print(f"[aula-f108] {e!r}", file=sys.stderr)

        self.worker.submit(job, _done, _err)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.props.active_window or MainWindow(self)
        win.present()


def main():
    return App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
