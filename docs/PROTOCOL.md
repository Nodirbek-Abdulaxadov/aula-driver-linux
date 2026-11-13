# AULA F108Pro (SONiX 0C45:800A / dongle 05AC:024F) — protocol spec from DeviceDriver.exe

Source: DeviceDriver.exe (x86 PE, MFC), sha256 446b362b2820844a2c670342208bb1e09500a38b4d69435ea2be8b3bff6179b6.
Static analysis only (Ghidra via REA). Tags: **[OBS]** = directly observed in code; **[INF]** = inferred.

## 1. Transport (low level)

### 1.0 Device discovery / collection selection  [OBS]
`FUN_00450af0` enumerates every HID interface (SetupDi, class "HIDClass"), opens it, reads HidD_GetAttributes (VID/PID/version), HidD_GetPreparsedData+HidP_GetCaps (UsagePage/Usage), HidD_GetProductString, and parses "&mi_xx" from the path (stored, but **not used for selection**).
`FUN_0044f960` then, for each interface whose VID/PID(+product string) matches a `<mode>` entry of config.xml (`FUN_0044ff20`/`FUN_00450080`, which also yields the mode value 0=USB / 2=2.4G), opens it (`FUN_00450f70`) and classifies **by HidP_GetCaps report lengths**:

| test (caps) | role | stored at | F108Pro interface |
|---|---|---|---|
| FeatureReportByteLength == 0x41 | **wired command channel** (SetFeature/GetFeature 65 B) | device list entry, type 0 | wired MI_03 (usage page 0xFF13) |
| OutputReportByteLength == 0x21 && InputReportByteLength == 0x21 | **2.4G command channel** (WriteFile/ReadFile 33 B) | device list entry, type 2; online flag = `FUN_0044f680` probe | dongle MI_03 (usage page 0xFF60) |
| UsagePage == 0xFFFF && Usage == 0x01 | async notify input (poll ReadFile every 200 ms, `FUN_00435160`) | devmgr+0x28 | [INF] wired MI_01 vendor collection carrying report ID 5 — verify descriptor |
| OutputReportByteLength == 0x1001 | TFT image channel (WriteFile 4097 B) | devmgr+0x2c | wired MI_02 (usage page 0xFF68) |
| anything else | closed | – | – |

```
if (*(short *)(_Memory + 4) == 0x41) { ...type = FUN_00450080(...) ... }                 // feature len 65
else if ((*(short *)(_Memory + 2) == 0x21) && (_Memory[3] == 0x21)) { ...[0x420]=2; [0x424]=FUN_0044f680(_Memory); }
else if ((usagePage == -1) && (usage == 1)) devmgr[0x28] = _Memory;
else if (*(short *)(_Memory + 2) == 0x1001) devmgr[0x2c] = _Memory;
```
`FUN_0044fe20` picks the command device: first entry with matching model and type 0 (wired), else type 1, else type 2 (dongle) ⇒ wired is preferred when both are present.
The `hid_interface="...&MI_00"` attribute in config.xml is parsed and stored but is not consulted by this selection code (it would be wrong anyway: MI_00 is the boot keyboard).

**Linux mapping:** wired: open the hidraw node of 0C45:800A whose report descriptor has a 64-byte *feature* report (MI_03, input 3). Dongle: hidraw of 05AC:024F with 32-byte in/out (MI_03).

### 1.0b Notify input report (`FUN_00435160`)  [OBS]
Polled every ≥200 ms with 10 ms timeout on devmgr+0x28; report ID byte is kept (not 0). Layout `r[0]=0x05` (report ID), `r[1]`, `r[2]`, `r[3]`:
- `05 A6 FF 01` → main+0x775 = 1 then refresh UI (`FUN_0041f980`); `05 A6 FE 02` → main+0x775 = 0 [INF: some connection/state toggle].
- any other `05 xx yy ..` → `FUN_00419300(main, yy)`: software-executed key action number yy (open program / website / text etc., see §2.3). Debug string: "mouse notify data: %02X %02X %02X %02X".

### 1.1 Send = HID SetFeature, 65 bytes  [OBS]
`FUN_00451330(devobj, buf)`:
```
cVar2 = (*DAT_005950a0 /*HidD_SetFeature*/)(*param_1 /*HANDLE*/, param_2 /*buf*/, 0x41);
return ok ? 0x41 : -1;   // (asm: MOV EAX,0x41 / OR EAX,-1)
```
- Buffer = 0x41 bytes: byte[0] = report ID = 0x00 (memset 0, never written), bytes[1..64] = 64-byte command payload.
- On Linux hidraw: `ioctl(fd, HIDIOCSFEATURE(65), buf)` with buf[0]=0x00.

### 1.2 Receive = IOCTL_HID_GET_FEATURE via DeviceIoControl  [OBS]
`FUN_004513d0(devobj, buf, len)`:
```
DeviceIoControl(handle, 0xb0192 /*IOCTL_HID_GET_FEATURE*/, buf, len, buf, len, &n, &ovl);
GetOverlappedResult(handle,&ovl,&n,TRUE);  return n (bytes) or -1
```
- Called with len = 0x41 (buf[0]=0x00 report id). HidD_GetFeature pointer (DAT_0059509c) is unused; the app issues the IOCTL itself.
- Linux: `ioctl(fd, HIDIOCGFEATURE(65), buf)` with buf[0]=0.

### 1.3 Send wrappers (all on the device-manager singleton `DAT_00595144`, returned by `FUN_00413440`)  [OBS]
| fn | signature | behaviour |
|---|---|---|
| `FUN_0044edc0` | `send(buf64*, len, bool readback)` | len<0x42: `Sleep(this+0x30)`; SetFeature(0x00+64B); if ok && readback: `Sleep(this+0x30)`; GetFeature(65) (result ignored). len>=0x42: loop len/64 chunks, each = SetFeature(0x00 + next 64B) then `Sleep(this+0x30)`, up to 10 retries per chunk on failure; no readback. |
| `FUN_0044efb0` | `send_fast(buf64*, len)` | len<0x42: Sleep(5); SetFeature; Sleep(5); GetFeature; if response payload[3] == 0xFF (busy?) re-send SetFeature + GetFeature once. len>=0x42: chunks with Sleep(2), no readback, abort if the whole frame takes > 100 ms. Used for the 04 20 real-time stream (custom light page, wired music mode). |
| `FUN_0044f290` | `query(buf64* inout, maxlen)` | Sleep(3); SetFeature(cmd); Sleep(5); GetFeature(len = caller value 3/9 → always fails on Windows); retry GetFeature(65) up to 10× (Sleep 5). If resp payload[3]==0x01 then reads up to 9 more 64B feature reports (Sleep 3 each, stop if a read returns !=0x40 bytes or takes >360ms) and copies them into the caller buffer. |
| `FUN_0044f1c0` | `send_big(buf4096*)` | 4096-byte path (see 1.5) |

`this+0x30` = inter-command delay [INF: = `cmd_delaytime` (35 ms) from rgb-keyboard.xml].

Packet payload convention (payload = the 64 bytes after report-ID 0):
- **Command packet**: `payload[0]=0x04`, `payload[1]=opcode`, rest command-specific; in the "header" form payload[8] (sometimes [8..9] LE) = number of 64-byte data packets that follow.
- **Data packets**: raw 64-byte blocks; the final 2 bytes of a data block are the signature `AA 55` (payload[0x3e]=0xAA, [0x3f]=0x55; for multi-packet blocks at the end of the whole block, e.g. offset 0x23e/0x23f in a 0x240 block).
- Every write transaction is framed: `04 18` (BEGIN) ... `04 02` (END/APPLY). No checksum observed.

### 1.4 Device model values parsed from rgb-keyboard.xml (`FUN_0041cd80`)  [OBS]
- `<cmd_delaytime value=35>` → main+0x7bc and **devmgr+0x30** (the Sleep() before/after every `FUN_0044edc0` packet = 35 ms).
- `<light rgb_keyboard=1>` → main+0x7ac (=1 ⇒ per-light data is 4 bytes/light, 9 packets / 0x240 bytes; =0 ⇒ 1 byte/light, 3 packets / 0xC0 bytes). **F108Pro: rgb_keyboard=1.**
- `default_mode=11` → +0x810, `default_brightness=5` → +0x814, `default_speed=3` → +0x818, `brightness_max=5`, `speed_max=5` (slider max values; minimum 0 [INF from slider]).
- `<function fn_layer=1 sleep_time=1 key_respondtime=1>` → feature-enable flags +0x7b0/+0x7b4/+0x7b8.
- Each `<key code=.. key_index=.. light_index=..>`: map main+0x81c: code → key_index (used for key-remap table offset), map main+0x824: code → light_index (used for per-key RGB offset). Only stored if both indices > 0.
- On F108Pro key_index == light_index for every key, range 1..123 (104 keys). Full table in Appendix A.

### 1.5 Other transports  [OBS]
- `FUN_00451110(dev, buf, len)`: overlapped **WriteFile** (output report); buffer padded with zeros up to the collection's OutputReportByteLength (dev+8 ushort).
- `FUN_004511f0(dev, out, len, timeout_ms)`: overlapped **ReadFile** (input report) with WaitForSingleObject(timeout); if received byte[0]==0x00 (report ID) it is stripped before copy.
- `FUN_0044f1c0(devmgr, buf4096)` — **wired TFT-screen image path**: uses a *second* device object at devmgr+0x2c; WriteFile 0x1001 bytes (0x00 + 4096 B) then ReadFile(timeout 300 ms) (ack, content not checked). ⇒ This is the MI_02 collection (usage page 0xFF68, 4096-byte output report). Only caller: GIF upload `FUN_00422b50`.
- `FUN_0044f4e0(devmgr, buf33, sumlen)` — **2.4 GHz dongle command path** (output report 0x21 = 0x00 + 32 B ⇒ dongle MI_03, usage page 0xFF60, 32-byte reports). See section 3.
- `FUN_0044f680(dev)` — dongle probe/handshake (section 3).

### 1.6 Wired vs 2.4G selection inside the app  [OBS]
Worker-thread dispatcher `FUN_00434230` pops a task id and calls the wired or dongle builder depending on `main+0x784` (`0`=USB wired, `2`=2.4G dongle; matches `<mode value=..>` in config.xml):

| task | wired fn (feature reports) | 2.4G fn (32-B output reports) | meaning |
|---|---|---|---|
| 6/7 | `FUN_004185e0(layer)` via `FUN_00434840`/`FUN_004348a0` | `FUN_00418e80` / `FUN_004191c0` | key remap (layer 0 = main, 1 = Fn) |
| 8 | `FUN_0042d630` | `FUN_0042dbb0` | macro upload |
| 9 | `FUN_0042b040` | `FUN_0042b1e0` | lighting effect |
| 10 | `FUN_00433fd0` (via `FUN_00434900`) | inline in `FUN_00434900` | side-light mode (04 13 [0]=0x1F+n; unused on F108Pro) |
| 11 | inline copy of `FUN_0044b910` (`FUN_00434980`) | inline in `FUN_00434980` | user (per-key) light upload |
| 12 | `FUN_00414230` | `FUN_004144a0` | system settings |
| 13 | (none) | inline: dongle cmd `0x1F` | see §3 |
| 16 | `FUN_00422b50` | `FUN_004233f0` | TFT GIF upload |
| 19 | `FUN_00423b10` | `FUN_00423c40` | TFT clock/time sync |
| idle, page 3 | `FUN_0042ae20` (wired only) | – | read live per-key colours (04 F5) |
| idle, page 6 | `FUN_00427fe0` | – | custom/real-time light stream (04 20) |
| idle, page 7 | `FUN_00433320` | – | music rhythm stream |

## 2. Wired command set (feature report 0x00 + 64 B on MI_03, usage page 0xFF13)

Notation: `CMD xx` = 64-byte payload `04 xx 00 00 00 00 00 00 nn 00 ... 00` where nn = payload[8] (count of following 64-byte data packets, when used). "rb" = sent with readback flag (a GetFeature follows, result ignored). All offsets below are payload offsets (add 1 for the hidraw buffer that starts with report ID 0x00).

| opcode | name (inferred) | evidence |
|---|---|---|
| 04 18 | BEGIN / open write session | first packet of every persistent write (light, keymap, user light, settings, clock, GIF); not used by the 04 20 stream or 04 F5 read |
| 04 19 | BEGIN (macro variant) | `FUN_0042d630` sends `04 19` instead of `04 18` before macro upload |
| 04 02 | END / apply-save | last packet of every sequence (also after the 04 20 stream and after the 04 F5 read) |
| 04 F0 | post-END "refresh/reload" [INF] | sent after 04 02 in light-effect, key-remap, user-light (`FUN_0042b040`,`FUN_004185e0`,`FUN_0044b800`,`FUN_0044b910`,`FUN_00433fd0`); readback flag 0 in most |
| 04 11 | write key-map, main layer | `FUN_004185e0(param=0)`, nn=9 |
| 04 27 | write key-map, Fn layer | `FUN_004185e0(param=1)`, nn=9 |
| 04 13 | write lighting effect | nn=1 |
| 04 15 | write macro data | nn=N (variable) |
| 04 17 | write system settings | nn=1 |
| 04 20 | stream custom/real-time per-key RGB | nn=8 (RGB) / 3 (mono); sent with `send_fast` |
| 04 23 | write user (static per-key) lighting | nn=9 (RGB) / 3 (mono) |
| 04 28 | write TFT clock | nn=1 |
| 04 72 | TFT GIF upload header | payload[2]=slot, payload[8..9]=chunk count (LE16) |
| 04 F5 | READ live per-key colours | nn=9 (RGB) / 3; the only wired read command |

### 2.1 Lighting effect — `FUN_0042b040` (task 9)  [OBS]
Values come from SQLite `t_light_data` (`SELECT * ... WHERE profile=? AND mode=?`), columns: light_id, profile, name, mode, brightness, speed, direction, colorful, colorindex, color_value(COLORREF 0x00BBGGRR), config_func, reserved, status.
Sequence:
```
04 18                                   (rb)
04 13 00 00 00 00 00 00 01              (rb)
DATA (rb=0):
  [0]  mode            (main+0x804; 0 = off)
  [1]  R  = color_value & 0xFF          ┐ only filled when mode != 0
  [2]  G  = (color_value>>8)  & 0xFF    │
  [3]  B  = (color_value>>16) & 0xFF    │
  [8]  colorful (1 = rainbow/multicolour, 0 = use RGB)
  [9]  brightness  (0..brightness_max=5)
  [10] speed       (0..speed_max=5)
  [11] direction
  [14] 0xAA  [15] 0x55                  (signature; rest 0)
04 02                                   (rb)
04 F0                                   (rb=0)
```
Decompiler excerpt:
```
local_58 = 0x1304; local_50 = 1;                          // 04 13 .. [8]=1
local_56 = color>>8; local_50 = colorful; local_4f = brightness;
local_58._1_1_ = (char)color; local_4e = speed; local_55 = color>>16; local_4d = direction;
local_58 = CONCAT11(local_58._1_1_, mode); local_4a = 0x55aa;
```
"Mode only" variant `FUN_00433fd0` (task 10): identical framing, DATA = `[0]=main+0x808, [14..15]=AA 55`, everything else 0. **Correction:** main+0x808 = side-light combobox data + 0x1F (asm 0x433f79 `add eax,0x1f`), and the builder only runs when the menu `sidelight` bit (0x100) is set → this is the **side-light mode** command (values 0x1F+n). F108Pro has `sidelight="0"`, so it is never used on this keyboard.

### 2.2 Effect mode table  [OBS: defaults inserted by `FUN_0042b2f0`; names = 1033.lan id 520+mode]
Default row values: brightness = default_brightness (5), speed = default_speed (3), direction 0, colorful 1, colorindex 0, color_value 0x0000FF (red).
`config_func` bitmask decides which controls the UI shows (`FUN_0042aa80`): 0x01 brightness, 0x02 speed, 0x04 direction pair {1,0}, 0x08 direction pair {2,3}, 0x10 palette RGB sliders, 0x20 colour button + "Colorful" checkbox.

| mode | name (1033.lan) | config_func | direction values |
|---|---|---|---|
| 0 | LED Off | 0x00 | – |
| 1 | Static | 0x31 | – (no speed) |
| 2 | SingleOn | 0x33 | – |
| 3 | SingleOff | 0x33 | – |
| 4 | Glittering | 0x33 | – |
| 5 | Falling | 0x33 | – |
| 6 | Colourful | 0x03 | – (no colour) |
| 7 | Breath | 0x33 | – |
| 8 | Spectrum | 0x03 | – (no colour) |
| 9 | Outward | 0x33 | – |
| 10 | Scrolling | 0x3b | 2 or 3 |
| 11 | Rolling (default) | 0x37 | 1 or 0 |
| 12 | Rotating | 0x37 | 1 or 0 |
| 13 | Explode | 0x33 | – |
| 14 | Launch | 0x33 | – |
| 15 | Ripples | 0x33 | – |
| 16 | Flowing | 0x37 | 1 or 0 |
| 17 | Pulsating | 0x33 | – |
| 18 | Tilt | 0x37 | 1 or 0 |
| 19 | Shuttle | 0x33 | – |
| 0x80 | User (per-key static) lighting | – | see 2.4 |

Direction radio handler (`FUN_0042c570`, asm 0x42c5ca..): control id 0x5b→1, 0x5c→0, 0x5d→2, 0x5e→3 [which physical direction each value is: not determinable statically; INF 0/1 = left/right, 2/3 = up/down].
Brightness/speed = raw slider positions 0..5 (`MSlider+0x144`). Colour: "Colorful" checkbox → colorful=1 (UI also forces colour 0xFF for preview).

### 2.3 Key remapping — `FUN_004185e0(this, fnLayer)` (tasks 6/7)  [OBS]
```
04 18                                        (rb)
04 11 00 00 00 00 00 00 09   (main layer)    (rb)      | 04 27 ... 09 for the Fn layer
DATA 0x240 bytes = 9 × 64-byte packets (chunked, Sleep(35) between, up to 10 retries each)
04 02                                        (rb)
04 F0                                        (rb)
```
`local_58._0_2_ = CONCAT11(fnLayer ? 0x27 : 0x11, 4); local_50 = 9;` ... `FUN_0044edc0(&DAT_00595144,&local_364,0x240,'\x01');`

DATA layout: 144 entries × 4 bytes; **entry offset = key_index × 4** (key_index from rgb-keyboard.xml via map main+0x81c, keyed by HID key code). Entry 0 unused. Bytes 0x23e/0x23f = `AA 55` (overwrite the tail of entry 143). Keys with no DB row ⇒ `00 00 00 00` = **firmware default** for that key. Only rows that exist in `t_key_macro_data(profile, fn_layer, key_code, …, macro_type, macro_value(+0x1c), macro_value2(+0x20), macro_value3(+0x24))` are written. For the Fn layer, keys found in set main+0x82c (keys flagged `fnlayer_disable`) are skipped.

Entry encoding by app `macro_type` (UI string from 1033.lan via `FUN_00417a00`-area switch):

| macro_type | UI | entry bytes [0..3] |
|---|---|---|
| (none) / 4 | Default key | `00 00 00 00` |
| 1 | Disable Key (202) | `05 03 00 00` |
| 2 | Key Function (205) – single key / combo | `02 <modmask> <usage> 00`; modmask = macro_value2 (bit0 LCtrl,1 LShift,2 LAlt,3 LGui,4 RCtrl,5 RShift,6 RAlt,7 RGui), usage = HID keyboard usage (macro_value). If the target key itself is a modifier (usage E0–E7) and modmask==0: `02 <bit(usage)> 00 00` (`FUN_00451b90` maps E0→01 … E7→80) |
| 3 | Macro (206) | `06 <macro#> <mode> <count>`; macro# = position of the macro in the macro list = slot index in the macro upload (§2.5); mode 0 once, 1 N times (count 1–255), 2 toggle, 3 while held, 4 click-to-play (§10) |
| 5 | Mouse (207) | `01 01 01 00` left, `01 01 04 00` middle, `01 01 02 00` right, `01 01 03 00` "double click" (app value 4), `01 03 01 00` wheel up, `01 03 FF 00` wheel down, `01 01 08 00` button 4, `01 01 10 00` button 5 → byte1 = 01 buttons / 03 wheel, byte2 = button mask / wheel delta |
| 6 | Multimedia (208) | `03 <usage_lo> 00 00`: 1 CD play/pause, 2 B7 stop, 3 B6 prev, 4 B5 next, 5 E9 vol+, 6 EA vol−, 7 E2 mute |
| 7 | Windows shortcut (209) | `02 <mod> <usage> 00`: 1 `08 07` Win+D, 2 `08 08` Win+E, 3 `08 0F` Win+L, 4 `01 1A` Ctrl+W, 5 `04 2B` Alt+Tab, 6 `01 06` Ctrl+C, 7 `01 19` Ctrl+V, 8 `01 1B` Ctrl+X, 10 → `02 02 00 00`, 11 → `02 01 00 00` (raw; meaning unclear) |
| 8/9/10/11 | Open program / website / send text / open file (210/211/212/218) | `05 02 <id> 00` (id = macro_value). Executed **by the PC app**: keyboard emits notify input `05 xx <id>` (§1.0b) → `FUN_00419300` [INF] |
| 12 | "Key function" consumer/launch (`FUN_004194e0`) | `03 <lo> <hi> 00` = 16-bit Consumer usage: 500→0x0194 My Computer, 501→0x0192 Calculator, 502→0x018A Mail, 503→0x0183 Media, 504→0x00CD, 505→0x00B7, 506→0x00B6, 507→0x00B5, 508→0x00E9, 509→0x00EA, 510→0x00E2, 511→0x0223 WWW Home, 512→0x0227 Refresh, 513→0x0226 Stop, 514→0x0224 Back, 515→0x0225 Forward, 516→0x022A Favorites, 517→0x0221 Search |
| 13 | Multi-Key (213) | `07 <v1> <v2> <v3>` (macro_value, value2, value3) [INF: modifier + up to 2 usages] |

General entry grammar [INF from the above]: byte0 = class (00 default, 01 mouse, 02 keyboard, 03 consumer, 05 special/software, 06 macro, 07 multi-key).

### 2.4 System settings — `FUN_00414230` (task 12)  [OBS]
```
04 18                                   (rb)
04 17 01 00 00 00 00 00 01              (rb)   (local_58=0x1704; local_56=1 → payload[2]=1; local_50=1 → [8]=1)
DATA (rb=0):
  [0]=0x00 [1]=0x01
  [2] disable Alt+Tab   (main+0x678, 0/1)   — see §8
  [3] disable Alt+F4    (main+0x67c, 0/1)
  [4] disable Win key   (main+0x680, 0/1)
  [5] fn_switch        (0 = Momentary, 1 = Toggle; §8)
  [6] sleep_time       (0 none, 1 = 1 min, 2 = 5 min, 3 = 30 min; §8)
  [7] 0
  [8] key_respondtime  (1..5 = debounce Level 1..5; 0 when never set; §8)
  [62]=0xAA [63]=0x55
04 02                                   (rb)
```
Note: unlike the other builders, no 04 F0 here. Values are the raw strings from t_config_data passed through `_wtoi` (empty → DAT_0056d43c default string) — exact numeric encodings of sleep/debounce levels: [INF] index order of the UI lists.

### 2.5 Macros — `FUN_0042d630` (task 8)  [OBS]
Guard: (macro count + listbox count) × 8 ≤ 0xA8C.
Build buffer (max 0xE00 bytes, zero-filled):
- **Offset table** at 0x000–0x18F: 100 slots × 4 bytes. Slot i (= macro# used in key entries) = `<off_lo> <off_hi> 00 00` (offset of macro i in this buffer), or `FF FF FF FF` if the macro has no records. First macro starts at 0x190 (400).
- **Macro block** at off: `[off+0..1]` = N = number of 4-byte events (LE16), `[off+2..7]` = 0, then N events at off+8. Next macro at off + 8 + 4N.
- **Event** (4 bytes) `d_lo d_hi code flags`; each recorded action produces an action event followed by a delay event:
  - key down: `00 00 <HID usage> B0`;  key up: `00 00 <usage> 30`  (usage via VK→HID table `FUN_00451460`)
  - mouse down: `00 00 <btn> 90`; mouse up: `00 00 <btn> 10`  (btn 01 left, 04 middle, 02 right)
  - delay: `<ms lo> <ms hi> 00 50`, ms = max(10, recorded delay)
  (flags: bit7 = press, 0x30 keyboard, 0x10 mouse, 0x50 delay)
- Total length L = end offset; packet count P = L/64 + 1 if L%64==0 else L/64 + 2 (always ≥1 spare packet); signature `AA 55` at the last two bytes of P×64.
```
04 19                                   (rb)   ← note: 0x19, not 0x18
04 15 00 00 00 00 00 00 P               (rb)
Sleep(30)
DATA P×64 bytes (chunked, rb)
Sleep(30)
04 02                                   (rb)
```

### 2.6 User (static per-key) lighting — `FUN_0044b800` + `FUN_0044b910` / `FUN_00434980` (task 11)  [OBS]
Step 1 (`FUN_0044b800`) select user mode:
```
04 18 (rb);  04 13 .. [8]=1 (rb);
DATA (rb=0): [0]=0x80 [1..8]=0 [9]=brightness (main+0x814, 0..5) [10..11]=0 [14]=AA [15]=55
04 02 (rb);  04 F0 (rb=0)
```
Step 2 upload colours:
```
04 18 (rb);  04 23 00 00 00 00 00 00 09 (rb)         (03 if rgb_keyboard=0)
DATA 0x240 bytes (rb): for each key with light_index L>0: [4L+0]=L, [4L+1]=R, [4L+2]=G, [4L+3]=B
                       [0x23e]=AA [0x23f]=55
     (mono: 0xC0 bytes, [L]=0xFF if lit, [0xBE..0xBF]=AA 55)
04 02 (rb);  04 F0 (rb)
```
Colour source: `t_userlightrgb_data.key_rgb` COLORREF (+0x10 R, +0x11 G, +0x12 B).

### 2.7 Custom / real-time lighting stream — `FUN_00427fe0` (idle loop, page 6) and `FUN_00432920`  [OBS framing; data layout partly INF]
Uses `send_fast` (Sleep 2–5 ms, no 35 ms delay):
```
04 20 00 00 00 00 00 00 08      (03 if mono)
DATA 0x200 bytes (8 packets) RGB, or 0xC0 (3 packets) mono  — 4 bytes per light index, same layout as 2.6 [INF: same as 04 23]
04 02
```
(no 04 18 and no 04 F0). **DATA layout differs from 04 23** (read from asm 0x4280f9–0x428207, a block Ghidra's decompiler dropped): entries are written *sequentially in key-item order*, 4 bytes each: `[light_index, R·k>>8, G·k>>8, B·k>>8]` where k = item intensity (0..255, item+0x48) and RGB = item colour (+0x30..+0x32); RGB stays 0 when the item is off (+0x40==0) but light_index is still written. Max 0x200/4 = 128 tuples; the rest is zero. Mono variant: 1 byte per key-item = intensity, sequential.
This is the natural "direct mode" for a Linux tool (real-time per-key colours, no 04 18/04 F0, probably not persisted [INF]).
Wired **music rhythm** (`FUN_00433320` → `FUN_00432920`) uses exactly this same 04 20 stream with colours rendered on the PC.

### 2.8 Read live per-key colours — `FUN_0042ae20` (idle loop, page 3, wired only)  [OBS]
```
Sleep(10)
SetFeature: 04 F5 00 00 00 00 00 00 09        (03 if mono)
Sleep(5); GetFeature #0 (ack)  — app checks resp payload[3] == 0x01
then up to 9 × { Sleep(3); GetFeature(65) } → each 64-byte payload appended to a 0x240 buffer;
stops early if a read returns ≠ 64 bytes or takes > 360 ms.
04 02 (rb)   ← sent afterwards
```
Parse: for light index L: RGB = buf[4L+1], buf[4L+2], buf[4L+3] (COLORREF = B<<16|G<<8|R). Mono: brightness = buf[L]*255>>8.
(Windows quirk: the first GetFeature is issued with a too-short length (3/9) and always fails, so the ack is effectively the first retry. On Linux just do SetFeature, then GetFeature, check [3]==1, then read 9 more.)

### 2.9 TFT clock — `FUN_00423b10` (task 19; also sent on connect if screen menu enabled, `FUN_00434750`)  [OBS]
```
04 18 (rb);  04 28 00 00 00 00 00 00 01 (rb)
DATA (rb): [0]=0x00 [1]=selected screen image index+1 [2]=0x5A [3]=year%2000 [4]=month [5]=day
           [6]=hour [7]=minute [8]=second [9]=0 [10]=day-of-week (0=Sunday) [62]=AA [63]=55
04 02 (rb)
```

### 2.10 TFT GIF/animation upload — `FUN_00422b50` (task 16)  [OBS, summary]
Image = up to gif_maxframes(141) frames of 240×135 RGB565 (2 bytes/pixel), preceded by gif_headlength(256)-byte header: header[0]=frame count, header[1+i]=per-frame delay/2 (min 1). Buffer pre-filled with 0xFF, length = 256 + 240·135·2·frames, padded to 4096.
```
04 18 (rb)
04 72 <slot> 00 00 00 00 00 <nChunks lo> <nChunks hi> (rb)   (payload[2] = LCD list selection + 1)
nChunks × WriteFile(MI_02, 0x00 + 4096 bytes) each followed by ReadFile ack (300 ms timeout)
04 02 (rb)
```

### 2.11 "Reset keyboard" / "Factory reset" (UI 152/153)  [OBS]
There is **no dedicated wired reset opcode**.
- *Reset Keyboard* handler (~0x4146f0): `DELETE FROM t_key_macro_data WHERE profile = ?`, then enqueues task 6 (wired: full key-map upload with all-zero entries = firmware defaults, both layers) and task 13 (2.4G only: dongle cmd `0x1F`).
- *Factory Reset* handler (~0x41495d): deletes/recreates the local DB, re-parses the XML defaults, enqueues task 14 = `FUN_00434ee0`: wired → re-upload macros (04 19/04 15), key-maps (04 11 + 04 27), user light (04 23), effect (04 13), mode, settings (04 17) with default values; 2.4G → dongle cmd `0x0F`, then Sleep(50) + light effect.
So a Linux tool can "reset" the wired keyboard by uploading an all-zero key map and the default effect (mode 11, brightness 5, speed 3, colorful 1).

## 3. 2.4 GHz dongle protocol (05AC:024F, MI_03, 32-byte output/input reports, no report ID)  [OBS]

### 3.1 Framing — `FUN_0044f4e0`
- Write: WriteFile 33 bytes = `00` (report ID) + 32-byte payload `p[0..31]`.
- `p[0]` = command, `p[1]` = data length, `p[2]` = chunk index / sub-index, `p[3..]` = data (≤ 28 bytes), **`p[31]` = checksum = (sum of p[0..30]) & 0xFF** (the code sums the whole 65-byte staging buffer before writing byte 32; all other bytes are 0, so it equals the 8-bit sum of p[0..30]).
- If WriteFile fails: Sleep(10), retry once. Then Sleep(5) and up to 20 × { ReadFile(33, timeout 5 ms); accept if `resp[0..2] == p[0..2]`; else Sleep(10) }. Accepted response (32 bytes) is copied back to the caller (used by battery query).
- No BEGIN/END framing; Sleep(2) between chunks of multi-chunk transfers.
- Wired 64-byte "data packet" fields map to dongle `p[3+k] = data[k]` for the small commands (signature `AA 55` sits at p[17..18] = data[14..15]).

### 3.2 Dongle command table
| p[0] | p[1] | p[2] | data | wired equivalent | fn |
|---|---|---|---|---|---|
| 0x02 | 0 | 0 | – ; response must have r[0]=0x02 | probe at enumeration (online flag) | `FUN_0044f680` |
| 0x03 / 0x0D | 0x04 | key_index | 4-byte key entry (main / Fn layer); default entry = `02 00 <usage> 00` | single-key update | `FUN_004191c0` |
| 0x05 | 0x10 | 0 | 16 bytes = wired 04 13 DATA[0..15] (mode,R,G,B,…,colorful,brightness,speed,direction,…,AA 55) | 04 13 | `FUN_0042b1e0` |
| 0x05 | 0x01 | 0 | p[3]=side-light mode (0x1F+n), p[17..18]=AA 55 | 04 13 side-light | `FUN_00434900` |
| 0x05 | 0x10 | 0 | p[3]=0x80, p[12]=brightness, p[17..18]=AA 55 | user-light mode | `FUN_0044bd80` |
| 0x07 | 0x10 | 0 | 16 bytes = wired 04 17 DATA[0..15] | 04 17 | `FUN_004144a0` |
| 0x09 | 0x1C (last: remainder) | chunk# | macro buffer (§2.5) in 28-byte chunks, count = L/28 + 1 + (L%28≠0) | 04 15 | `FUN_0042dbb0` |
| 0x0C | 0x10 | 0 | clock: p[3]=img#+1, p[4]=0x5A, p[5]=year%2000, p[6]=mon, p[7]=day, p[8]=h, p[9]=m, p[10]=s, p[12]=dow, p[17..18]=AA 55 | 04 28 | `FUN_00423c40` |
| 0x0F | 0 | 0 | – | factory reset (task 14) | `FUN_00434ee0` |
| 0x10 / 0x12 | 0x1C (chunk 20: 0x10) | chunk 0..20 | key map 0x240 bytes (main / Fn) in 21 chunks | 04 11 / 04 27 | `FUN_00418e80` |
| 0x14 | 0x1C (last: 0x10 RGB / 0x18 mono) | chunk 0..20 (0..6 mono) | user-light buffer 0x240 (0xC0) | 04 23 | `FUN_0044bd80`, `FUN_00434980` |
| 0x1F | 0 | 0 | – | "reset keys" (task 13) | inline in `FUN_00434230` |
| 0x20 | 0x01 | 0 | – ; **response r[3] = battery %** (clamped to 100) | (none) | `FUN_004357d0`, polled every 15 s |

### 3.3 Dongle-only streaming / large transfers  [OBS, summary]
- **Music rhythm (2.4G)** `FUN_00432b60`: `p[0]=0x0B p[1]=0x1C p[2]=0`, p[3]=combo(0x618) value, p[4]=combo(0x630) value, p[5]=slider(0x638) value, p[6..26]=21 spectrum/level bytes (trace "mxn: …"); checksum over 0x21 bytes. Firmware renders the effect.
- **TFT GIF (2.4G)** `FUN_004233f0`: header `p[0]=0x7F p[1]=0x03 p[2]=0 p[3]=slot p[4..6]=chunk count (LE24)`; then chunks of 28 bytes: `p[0]=0x80|(idx>>16) p[1]=idx&0xFF p[2]=(idx>>8)&0xFF p[3..30]=data`, Sleep(2) each. Same image buffer as §2.10.

## 4. Read / status commands (complete list found)  [OBS]
| channel | request | response |
|---|---|---|
| wired | `04 F5 … [8]=9` (§2.8) | ack payload[3]==1, then 9×64 B per-light RGB (light-index × 4) |
| wired | every `FUN_0044edc0` with readback flag does a GetFeature after the SetFeature, but the result is ignored | (echo/status, not parsed) |
| wired | notify input report ID 5 (§1.0b) | `05 A6 FF 01` / `05 A6 FE 02` state, `05 xx id` software key |
| dongle | `0x20 0x01` | r[3] = battery % |
| dongle | `0x02` | echo r[0]=0x02 = keyboard reachable |
| any | firmware version | **not a protocol command**: = HIDD_ATTRIBUTES.VersionNumber (USB bcdDevice) stored at entry+0x418 and returned by `FUN_0044f850` (asm 0x44f92b); compared against `<firmware version="120">` |
No commands were found that read back key maps, macros, effect settings or system settings.

## 5. Firmware update / bootloader — AVOID  [OBS]
DeviceDriver.exe contains **no** ISP/bootloader/firmware packets. Firmware update is delegated to an external program: strings `%s\\temp\\FirmwareUpdateTool.zip`, `%s\\temp\\FirmwareUpdateTool.exe` (downloaded from the `<firmware url>`/upgrade URL, launched via CreateProcessW/ShellExecuteW); while it runs the app closes all its HID handles (`FUN_0044e920`) and waits on the process (`OpenProcess`+`WaitForSingleObject`, `FUN_00434230` top). `<firmware file="" url="">` are empty for this build.
Opcodes a Linux tool should never send blindly (unknown/unused here, typical SONiX bootloader space): anything not listed in §2/§3, in particular unlisted `04 xx` values (e.g. 04 01, 04 FE, 04 FF, 05 xx …) and any packet whose payload[0] ≠ 0x04 on the wired feature channel. Only the opcodes in the tables above are known-safe-by-observation.

## 6. Ordering / timing summary
- Wired: one transaction = `04 18` → header (`04 op … n`) → n data packets → `04 02` [→ `04 F0`]. 35 ms before every packet (cmd_delaytime), 35 ms after each data packet; readback GetFeature after header/control packets (35 ms later). Macro transfer uses `04 19`, plus Sleep(30) around the data.
- The app serialises everything through one worker thread and a busy flag (devmgr+4); never interleave transactions.
- Real-time streams (04 20) use 2–5 ms gaps and skip 04 18/04 F0, but the header and the closing 04 02 are each followed by a GetFeature, and the frame is only sent if that reply has payload[3]==0x01 (§9); `send_fast` aborts a multi-packet frame if it takes > 100 ms.
- Dongle: no framing packets; Sleep(2) between chunks; each packet is acknowledged by an input report echoing p[0..2] (≤20 polls × 10 ms).

## 7. Open questions / not determined statically
1. Exact semantics of `04 F0` (sent after END in light/keymap uploads, not after settings/macros) — "apply/reload" assumed.
2. Physical meaning of direction values 0/1/2/3, and of key-entry byte patterns for "double click" (`01 01 03`), Windows-shortcut values 10/11 (`02 02 00`/`02 01 00`), Multi-key (`07 v1 v2 v3`). (Macro play-mode bytes: resolved in §10.)
3. (resolved in §8: settings encodings and checkbox mapping; only the fn_switch handler↔button binding is inferred.)
4. Contents of the GetFeature replies after ordinary writes (ignored by the app).
5. Whether 04 20 streaming is volatile (not saved) — inferred only.
6. Which wired HID collection is the UsagePage 0xFFFF/Usage 1 notify input (assumed MI_01 report ID 5).
7. Report-rate (polling rate) setting: no code/UI for it was found in this app version.
8. Side light: builder found (`FUN_00433fd0`, 04 13 [0]=0x1F+n, see §2.1); not applicable to F108Pro (`sidelight="0"`).

## 8. Settings value encodings (04 17 DATA / dongle 0x07)  [OBS unless marked]
All three values are stored in `t_config_data` as decimal strings (`"%d"`, 0x56aa54) and copied into the packet via `_wtoi` (`FUN_00414230` wired, `FUN_004144a0` dongle). On load the app calls `MComboBox::SelectData(_wtoi(value))`, i.e. **stored value == combobox ItemData** (`FUN_00413930`-area, asm 0x413961–0x4139e8).

| packet byte (wired DATA / dongle p[]) | setting | control | values (ItemData) | evidence |
|---|---|---|---|---|
| [5] / p[8] | fn_switch | KeyLayerButton main+0x380 "Momentary" (str 293, ctrl id 0x4e) / main+0x384 "Toggle" (str 294, ctrl id 0x4f), created at 0x436f0d / 0x436ff4 | **0 = Momentary, 1 = Toggle** | `FUN_004199b0`: unchecks +0x384, writes `fn_switch`="0" (DAT_0056d43c) and queues task 12; `FUN_00419b30`: unchecks +0x380, writes "1" (DAT_0056ceac). Handler↔button binding inferred from the radio pattern [INF] |
| [6] / p[9] | sleep_time | MComboBox main+0x658 (built at 0x43b6b3–0x43b82f via `MComboBox::AddItem(text, data, …)`) | **0 = No Sleep (str 142), 1 = 1 min (143), 2 = 5 min (144), 3 = 30 min (145)**; UI default SelectData(0) | pushes `0/1/2/3` before AddItem with string ids 0x8e/0x8f/0x90/0x91; saved by `FUN_00414f20` (GetItemData(+0x658), "%d") |
| [8] / p[11] | key_respondtime | MComboBox main+0x64c (built at 0x43b922–0x43bc18) | **1..5 = "Level 1".."Level 5"** (each item text = str 149 "Level" + n); UI default SelectData(2) | pushes `1..5` before AddItem with string id 0x95; saved by `FUN_00414d80`-area (asm 0x414d9d GetCurSel/GetItemData(+0x64c), 0x414e12 "%d", 0x414e47 "key_respondtime"). Debounce per UI text 600–624: L1 ≈2–3 ms, L2 ≈5–6, L3 ≈8–9, L4 ≈13–14, L5 ≈17–18 ms (wired) |
| [2] / p[5] | disable_alttab | CCheckButton main+0x678 (str 162 "Disable ALT + TAB", ctrl id 0x12e) | 0/1 | creation 0x43c300–0x43c38e; load/save key "disable_alttab" (0x413a18 → +0x678) |
| [3] / p[6] | disable_altf4 | CCheckButton main+0x67c (str 161 "Disable ALT + F4", ctrl id 0x12f) | 0/1 | creation 0x43c242–0x43c2f0; key "disable_altf4" (0x413a8f → +0x67c) |
| [4] / p[7] | disable_win (Win-lock) | CCheckButton main+0x680 (str 160 "Disable Windows Key", ctrl id 0x130) | 0/1 | creation 0x43c181–0x43c232; key "disable_win" (0x413b05 → +0x680) |

Defaults when `t_config_data` has no row: the app never inserts default rows for these keys (the only references to "sleep_time"/"key_respondtime" are load 0x413961/0x4139b1, send 0x414379/0x4143cb/0x4145a2/0x4145f4 and save 0x414e47/0x414ff7). In the send path an empty sleep_time or key_respondtime is replaced by DAT_0056d43c = **"0"**; an empty fn_switch gives `_wtoi("") = 0`. So a fresh install sends **fn_switch 0, sleep_time 0 (No sleep), key_respondtime 0** (0 is not one of the combobox items; the UI pre-selects Level 2, but that is not written until the user changes it), and the three lock checkboxes as unchecked (0).

## 9. Real-time stream prerequisites (04 20)  [OBS]
What the app does, exactly (wired, `FUN_00427fe0`; music `FUN_00432920` is byte-identical apart from the colour source):
1. **No mode switch.** Entering the "Real-time Lighting" page (tab id 6, `FUN_00431830` → `FUN_00428710` → `FUN_00427750`/`FUN_004284a0`) is UI/DB only; none of these reach a SetFeature wrapper (the only SetFeature callers are the three wrappers whose call sites are all listed in §1.3/§1.6). No 04 13, no 04 18, no 04 F0 precede the stream.
2. The stream is produced by the worker thread's idle path (`FUN_00434230`, virtual, vtable 0x56d5b0) **every idle iteration** while tab 6 is shown and main+0x774 (device connected) is set, wrapped in `timeBeginPeriod(1)`. i.e. it is re-sent continuously, not once.
3. Header via **send_fast** (`FUN_0044efb0`, asm 0x44f00e–0x44f113):
   ```
   Sleep(5); SetFeature(00 | 04 20 00 00 00 00 00 00 08 00…)        (03 instead of 08 if rgb_keyboard=0)
   Sleep(5); GetFeature(65)                      ← mandatory read-back
   if reply payload[3] == 0xFF: SetFeature(same) ; Sleep(5) ; GetFeature(65)   (one retry)
   success  ⇔  reply payload[3] == 0x01          (CMP byte [EBP-0x44],1 → AL=1)
   ```
   `FUN_00427fe0` sends the frame **only if this returns 1** (asm 0x428055 `test al,al / je 0x4282b0`).
4. Frame via send_fast multi-packet path (len 0x200 > 0x41): for each of 8 packets: SetFeature(00 + 64 B), Sleep(2); **no GetFeature**; aborts (returns 0) if a SetFeature fails or GetTickCount delta > 100 ms. Returns 1 otherwise.
5. Only if the frame call returned 1: `04 02` via **send_fast** again → Sleep(5), SetFeature, Sleep(5), GetFeature (+0xFF retry); result ignored.
6. Frame layout (0x200 bytes, from a 600-byte zeroed buffer): sequential 4-byte tuples `[light_index, R, G, B]` in CustomLightMode key-item order (asm 0x4280f9–0x428207); RGB = item colour × item intensity / 256; unused tail = 0. **No `AA 55` signature and no terminator** (no 0x55aa store in 0x427fe0–0x4282b0).

Probable reasons the hardware test showed no change (to try, in order): (a) the GetFeature after the 04 20 header is missing — the firmware likely only arms the data phase after that read and answers payload[3]=0x01 (send nothing else until it does); (b) the GetFeature after 04 02; (c) the app streams continuously (one frame per idle tick); a single frame may be overwritten by the stored effect/user-light on the next firmware tick [INF]; (d) 04 F5 may read the stored per-key table rather than the live output (the app only uses 04 F5 on the Lighting-Mode tab, id 3, to mirror effects) — verify visually [INF].
Dongle: there is no 2.4G equivalent of 04 20 for the custom-light page (only 0x0B music spectrum, §3.3).

## 10. Macro play modes (key entry `06 <macro#> <v2> <v3>`)  [OBS]
Key-assign dialog (class around 0x410000): play-mode combobox at dlg+0x30c is filled at 0x410369–0x410525 with `MComboBox::AddItem(text, data)`; count edit at dlg+0x310 (label str 245 "Loop Count (1 ~ 255)"), shown only when data==1 (`FUN_00412280`).
OK handler `FUN_004122d0` (macro_type 3 branch, 0x41233b–0x412433) fills the record (zero-initialised by `FUN_00405c30`): +0x1c macro_value = macro id (combobox dlg+0x2f0), **+0x20 macro_value2 = play-mode ItemData**, **+0x24 macro_value3 = count** (only for mode 1: `_wtoi(edit text)`, empty → "1", <1 → 1, >255 → 255; all other modes leave 0). The key-map encoder copies them verbatim to entry bytes 2 and 3.

| v2 | UI (1033.lan) | v3 |
|---|---|---|
| 0 | 242 Play Once | 0 |
| 1 | 243 Play Multiple Times | 1..255 = repeat count (245) |
| 2 | 244 Stop when key is pressed again (toggle loop) | 0 |
| 3 | 246 Release to stop (repeat while held) | 0 |
| 4 | 247 Click to play | 0 |

(Note the order: data 3 = string 246 and data 4 = string 247; string 245 is the count label, not a mode.) byte1 = macro# = index of the macro in the list returned by `FUN_0040a9a0`, which is also its slot in the 04 15 / dongle 0x09 offset table (§2.5).

## Appendix A — F108Pro key table (rgb-keyboard.xml; key entry offset = key_index*4, light entry offset = light_index*4)

| key_index | HID usage (code) | name | light_index | fnlayer_disable |
|---|---|---|---|---|
| 1 | 0x29 | Esc | 1 | 0 |
| 2 | 0x3a | F1 | 2 | 0 |
| 3 | 0x3b | F2 | 3 | 0 |
| 4 | 0x3c | F3 | 4 | 0 |
| 5 | 0x3d | F4 | 5 | 0 |
| 6 | 0x3e | F5 | 6 | 0 |
| 7 | 0x3f | F6 | 7 | 0 |
| 8 | 0x40 | F7 | 8 | 0 |
| 9 | 0x41 | F8 | 9 | 0 |
| 10 | 0x42 | F9 | 10 | 0 |
| 11 | 0x43 | F10 | 11 | 0 |
| 12 | 0x44 | F11 | 12 | 0 |
| 13 | 0x45 | F12 | 13 | 0 |
| 19 | 0x35 | ~` | 19 | 0 |
| 20 | 0x1e | !1 | 20 | 0 |
| 21 | 0x1f | @2 | 21 | 0 |
| 22 | 0x20 | #3 | 22 | 0 |
| 23 | 0x21 | $4 | 23 | 0 |
| 24 | 0x22 | %5 | 24 | 0 |
| 25 | 0x23 | ^6 | 25 | 0 |
| 26 | 0x24 | &amp;7 | 26 | 0 |
| 27 | 0x25 | *8 | 27 | 0 |
| 28 | 0x26 | (9 | 28 | 0 |
| 29 | 0x27 | )0 | 29 | 0 |
| 30 | 0x2d | _- | 30 | 0 |
| 31 | 0x2e | += | 31 | 0 |
| 32 | 0x53 | Num | 32 | 0 |
| 33 | 0x54 | // | 33 | 0 |
| 34 | 0x55 | * | 34 | 0 |
| 37 | 0x2b | Tab | 37 | 0 |
| 38 | 0x14 | Q | 38 | 0 |
| 39 | 0x1a | W | 39 | 0 |
| 40 | 0x8 | E | 40 | 0 |
| 41 | 0x15 | R | 41 | 0 |
| 42 | 0x17 | T | 42 | 0 |
| 43 | 0x1c | Y | 43 | 0 |
| 44 | 0x18 | U | 44 | 0 |
| 45 | 0xc | I | 45 | 0 |
| 46 | 0x12 | O | 46 | 0 |
| 47 | 0x13 | P | 47 | 0 |
| 48 | 0x2f | {[ | 48 | 0 |
| 49 | 0x30 | }} | 49 | 0 |
| 50 | 0x5f | 7 | 50 | 0 |
| 51 | 0x60 | 8 | 51 | 0 |
| 52 | 0x61 | 9 | 52 | 0 |
| 55 | 0x39 | CapsLock | 55 | 0 |
| 56 | 0x4 | A | 56 | 0 |
| 57 | 0x16 | S | 57 | 0 |
| 58 | 0x7 | D | 58 | 0 |
| 59 | 0x9 | F | 59 | 0 |
| 60 | 0xa | G | 60 | 0 |
| 61 | 0xb | H | 61 | 0 |
| 62 | 0xd | J | 62 | 0 |
| 63 | 0xe | K | 63 | 0 |
| 64 | 0xf | L | 64 | 0 |
| 65 | 0x33 | :; | 65 | 0 |
| 66 | 0x34 | &quot;&apos; | 66 | 0 |
| 67 | 0x31 | |\ | 67 | 0 |
| 68 | 0x5c | 4 | 68 | 0 |
| 69 | 0x5d | 5 | 69 | 0 |
| 70 | 0x5e | 6 | 70 | 0 |
| 73 | 0xe1 | Shift_L | 73 | 0 |
| 74 | 0x1d | Z | 74 | 0 |
| 75 | 0x1b | X | 75 | 0 |
| 76 | 0x6 | C | 76 | 0 |
| 77 | 0x19 | V | 77 | 0 |
| 78 | 0x5 | B | 78 | 0 |
| 79 | 0x11 | N | 79 | 0 |
| 80 | 0x10 | M | 80 | 0 |
| 81 | 0x36 | ,&lt; | 81 | 0 |
| 82 | 0x37 | .&gt; | 82 | 0 |
| 83 | 0x38 | /? | 83 | 0 |
| 84 | 0xe5 | Shift_R | 84 | 0 |
| 85 | 0x28 | Enter | 85 | 0 |
| 86 | 0x59 | 1 | 86 | 0 |
| 87 | 0x5a | 2 | 87 | 0 |
| 88 | 0x5b | 3 | 88 | 0 |
| 91 | 0xe0 | Ctrl_L | 91 | 0 |
| 92 | 0xe3 | Win_L | 92 | 0 |
| 93 | 0xe2 | Alt_L | 93 | 0 |
| 94 | 0x2c | Space | 94 | 0 |
| 95 | 0xe6 | Alt_R | 95 | 0 |
| 96 | 0xAF | Fn | 96 | 0 |
| 97 | 0x65 | APP | 97 | 0 |
| 98 | 0xE4 | Ctrl_R | 98 | 0 |
| 99 | 0x50 | ← | 99 | 0 |
| 100 | 0x51 | ↓ | 100 | 0 |
| 101 | 0x52 | ↑ | 101 | 0 |
| 102 | 0x4f | → | 102 | 0 |
| 103 | 0x2a | Backspace | 103 | 0 |
| 104 | 0x62 | 0 | 104 | 0 |
| 105 | 0x63 | . | 105 | 0 |
| 106 | 0x58 | Enter | 106 | 0 |
| 112 | 0x46 | PRINT | 112 | 0 |
| 113 | 0x47 | SCROOL | 113 | 0 |
| 115 | 0x48 | pause | 115 | 0 |
| 116 | 0x49 | insert | 116 | 0 |
| 117 | 0x4a | home | 117 | 0 |
| 118 | 0x4b | page up | 118 | 0 |
| 119 | 0x4c | del | 119 | 0 |
| 120 | 0x4d | end | 120 | 0 |
| 121 | 0x4e | page down | 121 | 0 |
| 122 | 0x56 | - | 122 | 0 |
| 123 | 0x57 | + | 123 | 0 |

key_index range 1..123 (n=104); light_index range 1..123
