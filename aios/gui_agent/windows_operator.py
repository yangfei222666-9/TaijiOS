"""Windows-native GUI operator for TaijiOS.

The public operator maps parsed UI-TARS actions to backend operations. The
default backend uses Win32 APIs, while tests can inject a fake backend so no
real input is sent.
"""

from __future__ import annotations

import base64
import ctypes
import re
import struct
import sys
import time
import zlib
from ctypes import wintypes
from typing import Protocol

from .actions import Action
from .operators import ExecutionResult, Screenshot


class WindowsBackend(Protocol):
    """Low-level Windows operations used by TaijiWindowsOperator."""

    def capture_screen(self) -> Screenshot:
        """Capture the current screen."""

    def move_to(self, x: float, y: float) -> None:
        """Move the pointer to screen coordinates."""

    def left_click(self) -> None:
        """Perform a left click."""

    def double_click(self) -> None:
        """Perform a double left click."""

    def right_click(self) -> None:
        """Perform a right click."""

    def scroll(self, direction: str, amount: int = 5) -> None:
        """Scroll vertically or horizontally."""

    def type_text(self, text: str) -> None:
        """Type Unicode text without using the clipboard."""

    def hotkey(self, key_spec: str) -> None:
        """Press and release a key chord such as ctrl+l."""


class TaijiWindowsOperator:
    """UI-TARS compatible operator for Windows desktop control."""

    SUPPORTED_ACTIONS = {
        "click",
        "left_click",
        "left_single",
        "left_double",
        "double_click",
        "right_click",
        "right_single",
        "scroll",
        "type",
        "hotkey",
        "wait",
        "finished",
        "call_user",
        "user_stop",
    }

    def __init__(self, backend: WindowsBackend | None = None, wait_seconds: float = 5.0):
        self.backend = backend or Win32Backend()
        self.wait_seconds = wait_seconds

    def screenshot(self) -> Screenshot:
        return self.backend.capture_screen()

    def execute(self, action: Action) -> ExecutionResult:
        action_type = action.action_type
        inputs = action.inputs

        if action_type not in self.SUPPORTED_ACTIONS:
            return ExecutionResult(
                status="unsupported",
                message=f"unsupported Windows action: {action_type}",
                metadata={"action_type": action_type},
            )

        if action_type in {"finished", "call_user", "user_stop"}:
            return ExecutionResult(
                status="end",
                message=f"terminal action: {action_type}",
                metadata={"action_type": action_type},
            )

        if action_type == "wait":
            time.sleep(self.wait_seconds)
            return ExecutionResult(status="executed", message="wait completed")

        if action_type in {"click", "left_click", "left_single"}:
            self._move_if_coords(inputs)
            self.backend.left_click()
        elif action_type in {"left_double", "double_click"}:
            self._move_if_coords(inputs)
            self.backend.double_click()
        elif action_type in {"right_click", "right_single"}:
            self._move_if_coords(inputs)
            self.backend.right_click()
        elif action_type == "scroll":
            self._move_if_coords(inputs)
            self.backend.scroll(str(inputs.get("direction", "down")))
        elif action_type == "type":
            content = str(inputs.get("content", ""))
            submit = content.endswith("\\n") or content.endswith("\n")
            content = content.removesuffix("\\n").removesuffix("\n")
            if content:
                self.backend.type_text(content)
            if submit:
                self.backend.hotkey("enter")
        elif action_type == "hotkey":
            key_spec = str(inputs.get("key") or inputs.get("hotkey") or "")
            if not key_spec:
                return ExecutionResult(status="skipped", message="empty hotkey")
            self.backend.hotkey(key_spec)

        return ExecutionResult(
            status="executed",
            message=f"executed {action_type}",
            metadata={"action_type": action_type, "inputs": dict(inputs)},
        )

    def _move_if_coords(self, inputs: dict) -> None:
        coords = inputs.get("start_coords")
        if not coords:
            return
        x, y = coords
        self.backend.move_to(float(x), float(y))


class Win32Backend:
    """Win32 backend implemented with ctypes and no extra dependencies."""

    SM_CXSCREEN = 0
    SM_CYSCREEN = 1
    SRCCOPY = 0x00CC0020
    CAPTUREBLT = 0x40000000
    DIB_RGB_COLORS = 0
    BI_RGB = 0

    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_HWHEEL = 0x01000
    WHEEL_DELTA = 120

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004

    VK_MAP = {
        "ctrl": 0x11,
        "control": 0x11,
        "shift": 0x10,
        "alt": 0x12,
        "option": 0x12,
        "win": 0x5B,
        "meta": 0x5B,
        "cmd": 0x5B,
        "command": 0x5B,
        "enter": 0x0D,
        "return": 0x0D,
        "tab": 0x09,
        "esc": 0x1B,
        "escape": 0x1B,
        "backspace": 0x08,
        "delete": 0x2E,
        "space": 0x20,
        "left": 0x25,
        "arrowleft": 0x25,
        "up": 0x26,
        "arrowup": 0x26,
        "right": 0x27,
        "arrowright": 0x27,
        "down": 0x28,
        "arrowdown": 0x28,
        "pageup": 0x21,
        "page up": 0x21,
        "pagedown": 0x22,
        "page down": 0x22,
        "home": 0x24,
        "end": 0x23,
    }

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Win32Backend is only available on Windows")
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        self.kernel32 = ctypes.windll.kernel32
        self._configure_signatures()

    def capture_screen(self) -> Screenshot:
        width = int(self.user32.GetSystemMetrics(self.SM_CXSCREEN))
        height = int(self.user32.GetSystemMetrics(self.SM_CYSCREEN))
        bgra = self._capture_bgra(width, height)
        png = _png_from_bgra(bgra, width, height)
        return Screenshot(
            base64=base64.b64encode(png).decode("ascii"),
            width=width,
            height=height,
            scale_factor=1.0,
            mime="image/png",
        )

    def move_to(self, x: float, y: float) -> None:
        self.user32.SetCursorPos(int(round(x)), int(round(y)))

    def left_click(self) -> None:
        self._mouse_click(self.MOUSEEVENTF_LEFTDOWN, self.MOUSEEVENTF_LEFTUP)

    def double_click(self) -> None:
        self.left_click()
        time.sleep(0.08)
        self.left_click()

    def right_click(self) -> None:
        self._mouse_click(self.MOUSEEVENTF_RIGHTDOWN, self.MOUSEEVENTF_RIGHTUP)

    def scroll(self, direction: str, amount: int = 5) -> None:
        normalized = direction.lower()
        delta = self.WHEEL_DELTA * amount
        if normalized in {"down", "left"}:
            delta = -delta
        if normalized in {"left", "right"}:
            self.user32.mouse_event(self.MOUSEEVENTF_HWHEEL, 0, 0, delta, 0)
        else:
            self.user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)

    def type_text(self, text: str) -> None:
        for char in text:
            self._send_unicode_char(char)
            time.sleep(0.005)

    def hotkey(self, key_spec: str) -> None:
        keys = [part for part in re.split(r"[\s+]+", key_spec.strip()) if part]
        virtual_keys = [self._vk(part) for part in keys]
        for vk in virtual_keys:
            self._key_event(vk, key_up=False)
        for vk in reversed(virtual_keys):
            self._key_event(vk, key_up=True)

    def _capture_bgra(self, width: int, height: int) -> bytes:
        hdc_screen = self.user32.GetDC(None)
        hdc_mem = self.gdi32.CreateCompatibleDC(hdc_screen)
        hbmp = self.gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        old_obj = self.gdi32.SelectObject(hdc_mem, hbmp)

        try:
            ok = self.gdi32.BitBlt(
                hdc_mem,
                0,
                0,
                width,
                height,
                hdc_screen,
                0,
                0,
                self.SRCCOPY | self.CAPTUREBLT,
            )
            if not ok:
                raise OSError("BitBlt failed")

            bitmap_info = BITMAPINFO()
            bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bitmap_info.bmiHeader.biWidth = width
            bitmap_info.bmiHeader.biHeight = -height
            bitmap_info.bmiHeader.biPlanes = 1
            bitmap_info.bmiHeader.biBitCount = 32
            bitmap_info.bmiHeader.biCompression = self.BI_RGB

            buffer = ctypes.create_string_buffer(width * height * 4)
            rows = self.gdi32.GetDIBits(
                hdc_mem,
                hbmp,
                0,
                height,
                buffer,
                ctypes.byref(bitmap_info),
                self.DIB_RGB_COLORS,
            )
            if rows != height:
                raise OSError(f"GetDIBits returned {rows}, expected {height}")
            return buffer.raw
        finally:
            self.gdi32.SelectObject(hdc_mem, old_obj)
            self.gdi32.DeleteObject(hbmp)
            self.gdi32.DeleteDC(hdc_mem)
            self.user32.ReleaseDC(None, hdc_screen)

    def _configure_signatures(self) -> None:
        self.user32.GetDC.argtypes = [wintypes.HWND]
        self.user32.GetDC.restype = wintypes.HDC
        self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.SetCursorPos.restype = wintypes.BOOL
        self.user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        ]
        self.user32.SendInput.restype = wintypes.UINT

        self.gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi32.CreateCompatibleBitmap.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
        ]
        self.gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self.gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self.gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self.gdi32.BitBlt.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
        ]
        self.gdi32.BitBlt.restype = wintypes.BOOL
        self.gdi32.GetDIBits.argtypes = [
            wintypes.HDC,
            wintypes.HBITMAP,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.LPVOID,
            ctypes.POINTER(BITMAPINFO),
            wintypes.UINT,
        ]
        self.gdi32.GetDIBits.restype = ctypes.c_int
        self.gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self.gdi32.DeleteObject.restype = wintypes.BOOL
        self.gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi32.DeleteDC.restype = wintypes.BOOL

    def _mouse_click(self, down_flag: int, up_flag: int) -> None:
        self.user32.mouse_event(down_flag, 0, 0, 0, 0)
        time.sleep(0.04)
        self.user32.mouse_event(up_flag, 0, 0, 0, 0)

    def _send_unicode_char(self, char: str) -> None:
        scan = ord(char)
        self._send_input(scan, key_up=False)
        self._send_input(scan, key_up=True)

    def _send_input(self, scan: int, key_up: bool) -> None:
        flags = self.KEYEVENTF_UNICODE | (self.KEYEVENTF_KEYUP if key_up else 0)
        input_struct = INPUT()
        input_struct.type = self.INPUT_KEYBOARD
        input_struct.ki = KEYBDINPUT(0, scan, flags, 0, 0)
        sent = self.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))
        if sent != 1:
            raise OSError("SendInput failed")

    def _key_event(self, vk: int, key_up: bool) -> None:
        flags = self.KEYEVENTF_KEYUP if key_up else 0
        self.user32.keybd_event(vk, 0, flags, 0)

    def _vk(self, key: str) -> int:
        normalized = key.lower()
        if normalized in self.VK_MAP:
            return self.VK_MAP[normalized]
        f_key = re.fullmatch(r"f(\d{1,2})", normalized)
        if f_key:
            number = int(f_key.group(1))
            if 1 <= number <= 24:
                return 0x70 + number - 1
        if len(key) == 1:
            return ord(key.upper())
        raise ValueError(f"unsupported hotkey key: {key}")


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def _png_from_bgra(bgra: bytes, width: int, height: int) -> bytes:
    """Encode a BGRA buffer as a PNG with RGBA pixels."""

    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)
        start = y * stride
        end = start + stride
        row = bgra[start:end]
        for i in range(0, len(row), 4):
            b, g, r, _ = row[i : i + 4]
            rows.extend((r, g, b, 255))

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        signature
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )
