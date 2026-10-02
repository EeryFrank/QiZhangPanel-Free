# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""A private, never activated Windows desktop for unadaptable launchers.

No polling thread, screen capture, input injection or SwitchDesktop is used.
Only windows whose live process is in the retained launch Job can be closed.
Invisible framework/owner/message windows are never used as a shutdown route.
"""
import ctypes
from ctypes import wintypes as w
import uuid


class HiddenDesktop:
    def __init__(self):
        self.handle = None
        self.name = "QiZhang-" + uuid.uuid4().hex
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p]
        self.user.CreateDesktopW.restype = w.HANDLE
        self.user.CloseDesktop.argtypes = [w.HANDLE]
        self.user.CloseDesktop.restype = w.BOOL
        # READOBJECTS | CREATEWINDOW | ENUMERATE | WRITEOBJECTS. No switch right.
        self.handle = self.user.CreateDesktopW(self.name, None, None, 0, 0xC3, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle and self.user.CloseDesktop(self.handle):
            self.handle = None

    def __del__(self):
        self.close()

    def windows(self):
        callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        self.user.EnumDesktopWindows.argtypes = [w.HANDLE, callback_type, w.LPARAM]
        self.user.EnumDesktopWindows.restype = w.BOOL
        self.user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        self.user.GetWindowThreadProcessId.restype = w.DWORD
        result = []
        @callback_type
        def visit(window, _):
            pid = w.DWORD()
            self.user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            result.append((int(window), int(pid.value)))
            return True
        if not self.handle or not self.user.EnumDesktopWindows(self.handle, visit, 0):
            raise OSError("hidden launcher window enumeration unavailable")
        return result

    def _user_window(self, window):
        """Identify a displayed application window on its own private desktop.

        WS_VISIBLE does not mean visible on the interactive/default desktop.
        An unrecognizable, borderless or explicitly hidden launcher is kept
        alive; closing its helper HWND can bypass the real form's close event.
        """
        self.user.IsWindowVisible.argtypes = [w.HWND]
        self.user.IsWindowVisible.restype = w.BOOL
        self.user.GetParent.argtypes = [w.HWND]
        self.user.GetParent.restype = w.HWND
        self.user.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        self.user.GetClassNameW.restype = ctypes.c_int
        self.user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        self.user.GetWindowTextW.restype = ctypes.c_int
        if not self.user.IsWindowVisible(window):
            return False, "not_visible_on_own_desktop"
        # EnumDesktopWindows normally excludes message-only windows; retain an
        # explicit check in case the enumeration source ever changes.
        parent = self.user.GetParent(window)
        if parent and int(parent) == ctypes.c_void_p(-3).value:  # HWND_MESSAGE
            return False, "message_only_window"
        class_name = ctypes.create_unicode_buffer(256)
        if not self.user.GetClassNameW(window, class_name, len(class_name)):
            return False, "window_class_unavailable"
        name = class_name.value.casefold()
        if (name in {"ime", "msctfime ui", "cicmarshalwndclass", "olemainthreadwndclass",
                     "sysshadow", "tooltips_class32"}
                or name.startswith((".net-broadcasteventwindow", "windowsformsparkingwindow"))):
            return False, "framework_helper_window"
        title = ctypes.create_unicode_buffer(1024)
        if not self.user.GetWindowTextW(window, title, len(title)) or not title.value.strip():
            return False, "untitled_or_unreadable_window"
        if title.value.casefold().startswith(("windowsformsparkingwindow", "gdi+ window",
                                             "windowsformssynchronizationcontext")):
            return False, "framework_helper_window"
        get_style = (self.user.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
                     else self.user.GetWindowLongW)
        get_style.argtypes = [w.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        values = []
        for index in (-16, -20):  # GWL_STYLE, GWL_EXSTYLE
            ctypes.set_last_error(0)
            value = get_style(window, index)
            if not value and ctypes.get_last_error():
                return False, "window_style_unavailable"
            values.append(value)
        style, extended = values
        if style & 0x40000000:  # WS_CHILD
            return False, "child_window"
        caption_and_menu = style & 0x00C80000 == 0x00C80000
        explicit_app_window = bool(extended & 0x00040000)  # WS_EX_APPWINDOW
        if not caption_and_menu and not explicit_app_window:
            return False, "unrecognized_application_window"
        return True, "application_window"

    def request_close(self, is_owned):
        self.user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.user.PostMessageW.restype = w.BOOL
        self.user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        self.user.GetWindowThreadProcessId.restype = w.DWORD

        def current_owner(window):
            owner = w.DWORD()
            thread = self.user.GetWindowThreadProcessId(window, ctypes.byref(owner))
            return int(owner.value) if thread else 0

        submitted = 0
        # Keep the integer return API, and expose why an unknown/invisible
        # launcher was deliberately left running rather than closing a helper.
        self.last_close_status = {"requested": 0, "skipped": []}
        for window, pid in self.windows():
            # A successful close of the main form can destroy several hidden
            # WinForms helper windows before we reach their enumerated handles.
            # Recycled handles must not receive a message meant for another PID.
            if current_owner(window) == pid and is_owned(pid) and current_owner(window) == pid:
                accepted, reason = self._user_window(window)
                if not accepted:
                    self.last_close_status["skipped"].append({"pid": pid, "window": window, "reason": reason})
                    continue
                # A handle can be recycled or repurposed while styles are read.
                # Recheck both identity and the application-window classification.
                accepted, reason = self._user_window(window)
                if current_owner(window) != pid or not accepted:
                    self.last_close_status["skipped"].append({"pid": pid, "window": window,
                                                               "reason": reason if not accepted else "owner_changed"})
                    continue
                ctypes.set_last_error(0)
                if not self.user.PostMessageW(window, 0x0010, 0, 0):  # WM_CLOSE, never terminate
                    error = ctypes.get_last_error()
                    if error == 1400 and current_owner(window) != pid:  # HWND disappeared/replaced
                        continue
                    raise OSError(error, "hidden launcher refused a normal close request")
                submitted += 1
                self.last_close_status["requested"] = submitted
        return submitted
