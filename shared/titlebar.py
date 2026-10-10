"""Windows 标题栏主题同步（DWM）。

让系统标题栏（最小化/最大化/关闭那一条）跟随应用的深浅色主题：
- Win10 1809+ / Win11：沉浸式暗色标题栏（文字、按钮变白，背景变暗）
- Win11 22000+：额外设置标题栏背景色 / 文字色，和页面顶部颜色完全一致，实现“沉浸”

非 Windows 或调用失败时静默忽略，不影响程序运行。
"""
import sys
import ctypes
from ctypes import wintypes

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20      # Win10 20H1+ / Win11
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19  # Win10 1809 - 1903
_DWMWA_CAPTION_COLOR = 35                # Win11 22000+
_DWMWA_TEXT_COLOR = 36                   # Win11 22000+
_DWMWA_COLOR_DEFAULT = 0xFFFFFFFF


def _hex_to_colorref(hex_color: str) -> int:
    """'#rrggbb' -> COLORREF(0x00BBGGRR)"""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def _set_attr(dwm, hwnd, attr: int, data) -> bool:
    hr = dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(data), ctypes.sizeof(data))
    return hr == 0


def apply_titlebar(widget, dark: bool, caption_hex: str = None, text_hex: str = None) -> None:
    """按主题设置窗口标题栏。

    dark        : 是否深色（控制系统按钮/文字的明暗）
    caption_hex : 标题栏背景色，如 '#0f1724'；None 表示恢复系统默认
    text_hex    : 标题栏文字色，如 '#e5e7eb'；None 表示恢复系统默认
    """
    if sys.platform != 'win32':
        return
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                              ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long

        flag = ctypes.c_int(1 if dark else 0)
        if not _set_attr(dwm, hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, flag):
            _set_attr(dwm, hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, flag)

        # 以下两项仅 Win11 22000+ 生效，旧系统返回失败码，忽略即可
        cap = ctypes.c_uint(_DWMWA_COLOR_DEFAULT if caption_hex is None
                            else _hex_to_colorref(caption_hex))
        _set_attr(dwm, hwnd, _DWMWA_CAPTION_COLOR, cap)
        txt = ctypes.c_uint(_DWMWA_COLOR_DEFAULT if text_hex is None
                            else _hex_to_colorref(text_hex))
        _set_attr(dwm, hwnd, _DWMWA_TEXT_COLOR, txt)
    except Exception:
        pass
