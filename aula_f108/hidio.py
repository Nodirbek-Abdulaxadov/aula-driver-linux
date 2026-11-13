"""Low-level Linux hidraw access (no external dependencies).

Finds hidraw nodes through sysfs and talks to them with plain read/write and
the HIDIOC[SG]FEATURE ioctls.
"""
from __future__ import annotations

import fcntl
import glob
import os
import select
from dataclasses import dataclass, field

# <linux/hidraw.h>
_IOC_WRITE, _IOC_READ = 1, 2


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("H") << 8) | nr


def HIDIOCSFEATURE(size: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, 0x06, size)


def HIDIOCGFEATURE(size: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, 0x07, size)


@dataclass
class Collection:
    usage_page: int
    usage: int
    input_len: int = 0
    output_len: int = 0
    feature_len: int = 0
    report_ids: list[int] = field(default_factory=list)


def parse_report_descriptor(desc: bytes) -> list[Collection]:
    """Very small HID report-descriptor parser: top-level collections with
    their usage page/usage and the byte length of input/output/feature
    reports (summed per main item, report IDs noted)."""
    cols: list[Collection] = []
    usage_page = usage = 0
    rsize = rcount = 0
    depth = 0
    cur: Collection | None = None
    i = 0
    while i < len(desc):
        b = desc[i]
        if b == 0xFE:  # long item
            i += 3 + desc[i + 1]
            continue
        size = (0, 1, 2, 4)[b & 3]
        typ = (b >> 2) & 3
        tag = b >> 4
        data = int.from_bytes(desc[i + 1:i + 1 + size], "little")
        i += 1 + size
        if typ == 1:  # global
            if tag == 0:
                usage_page = data
            elif tag == 7:
                rsize = data
            elif tag == 9:
                rcount = data
            elif tag == 8 and cur is not None:
                cur.report_ids.append(data)
        elif typ == 2:  # local
            if tag == 0 and depth == 0:
                usage = data
        elif typ == 0:  # main
            if tag == 0xA:  # collection
                if depth == 0:
                    cur = Collection(usage_page, usage)
                    cols.append(cur)
                depth += 1
            elif tag == 0xC:  # end collection
                depth -= 1
            elif cur is not None and tag in (0x8, 0x9, 0xB):
                n = rsize * rcount // 8
                if tag == 0x8:
                    cur.input_len += n
                elif tag == 0x9:
                    cur.output_len += n
                else:
                    cur.feature_len += n
    return cols


@dataclass
class HidrawInfo:
    path: str
    vid: int
    pid: int
    name: str
    interface: int
    collections: list[Collection]

    @property
    def usage_pages(self) -> list[int]:
        return [c.usage_page for c in self.collections]

    def __str__(self) -> str:
        cols = ", ".join(
            f"{c.usage_page:04x}/{c.usage:02x}(in{c.input_len}/out{c.output_len}/feat{c.feature_len})"
            for c in self.collections)
        return f"{self.path} {self.vid:04x}:{self.pid:04x} if{self.interface} '{self.name}' [{cols}]"


def enumerate_hidraw() -> list[HidrawInfo]:
    out: list[HidrawInfo] = []
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        dev = os.path.join(node, "device")
        try:
            uevent = dict(
                line.split("=", 1) for line in open(os.path.join(dev, "uevent")).read().splitlines() if "=" in line)
            desc = open(os.path.join(dev, "report_descriptor"), "rb").read()
        except OSError:
            continue
        _bus, vid, pid = uevent.get("HID_ID", "0:0:0").split(":")
        phys = uevent.get("HID_PHYS", "")
        iface = int(phys.rsplit("input", 1)[1]) if "input" in phys else -1
        out.append(HidrawInfo(
            path="/dev/" + os.path.basename(node),
            vid=int(vid, 16), pid=int(pid, 16),
            name=uevent.get("HID_NAME", ""),
            interface=iface,
            collections=parse_report_descriptor(desc)))
    return out


class HidrawDevice:
    def __init__(self, info: HidrawInfo):
        self.info = info
        self.fd = os.open(info.path, os.O_RDWR | os.O_NONBLOCK)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # Report ID 0 means "device does not use report IDs".
    def set_feature(self, data: bytes, report_id: int = 0) -> int:
        buf = bytearray([report_id]) + bytearray(data)
        return fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(buf)), buf, True)

    def get_feature(self, length: int, report_id: int = 0) -> bytes:
        buf = bytearray(length + 1)
        buf[0] = report_id
        n = fcntl.ioctl(self.fd, HIDIOCGFEATURE(len(buf)), buf, True)
        return bytes(buf[1:n])

    def write(self, data: bytes, report_id: int = 0) -> int:
        return os.write(self.fd, bytes([report_id]) + bytes(data))

    def read(self, timeout: float = 1.0, size: int = 4096) -> bytes | None:
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        return os.read(self.fd, size)

    def drain(self) -> None:
        while self.read(0.0) is not None:
            pass
