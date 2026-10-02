// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

namespace QiZhang.Shared {
    internal static class AppTheme {
        private static readonly object Sync = new object();
        private static string mode = "system";
        private static string accent = "green";
        private static bool dark;
        private static bool subscribed;
        internal static Func<bool> SystemDarkReader = ReadSystemDark;
        internal static event EventHandler Changed;

        static AppTheme() { SetMode("system"); }

        internal static string Mode { get { lock (Sync) { return mode; } } }
        internal static string Accent { get { lock (Sync) { return accent; } } }
        internal static bool IsDark { get { lock (Sync) { return dark; } } }

        internal static void Initialize(string requestedMode) { SetMode(requestedMode); }
        internal static void Initialize(string requestedMode, string requestedAccent) { Initialize(requestedMode); SetAccent(requestedAccent); }

        internal static void SetAccent(string requestedAccent) {
            string normalized = (requestedAccent ?? "green").Trim().ToLowerInvariant();
            if (normalized != "green" && normalized != "blue" && normalized != "violet" && normalized != "rose"
                    && normalized != "amber" && normalized != "teal" && normalized != "slate") normalized = "green";
            bool changed;
            lock (Sync) { changed = normalized != accent; accent = normalized; }
            if (changed) NotifyChanged();
        }

        internal static void SetMode(string requestedMode) {
            string normalized = (requestedMode ?? "system").Trim().ToLowerInvariant();
            if (normalized != "light" && normalized != "dark" && normalized != "system") normalized = "system";
            bool changed;
            lock (Sync) {
                Subscribe();
                bool nextDark = normalized == "dark" || normalized == "system" && SafeReadSystemDark();
                changed = normalized != mode || nextDark != dark;
                mode = normalized;
                dark = nextDark;
            }
            if (changed) NotifyChanged();
        }

        internal static void RefreshSystemTheme() {
            bool changed = false;
            lock (Sync) {
                if (mode != "system") return;
                bool nextDark = SafeReadSystemDark();
                changed = nextDark != dark;
                dark = nextDark;
            }
            if (changed) NotifyChanged();
        }

        private static bool SafeReadSystemDark() {
            try { return (SystemDarkReader ?? ReadSystemDark)(); }
            catch { return false; }
        }

        private static bool ReadSystemDark() {
            try {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", false)) {
                    object value = key == null ? null : key.GetValue("AppsUseLightTheme", null, RegistryValueOptions.DoNotExpandEnvironmentNames);
                    return value is int && (int)value == 0;
                }
            } catch { return false; }
        }

        private static void Subscribe() {
            if (subscribed) return;
            try {
                SystemEvents.UserPreferenceChanged += OnSystemPreferenceChanged;
                subscribed = true;
            } catch { /* SystemEvents can be unavailable in headless environments. */ }
        }

        private static void OnSystemPreferenceChanged(object sender, UserPreferenceChangedEventArgs args) {
            RefreshSystemTheme();
        }

        private static void NotifyChanged() {
            EventHandler handler = Changed;
            if (handler != null) handler(null, EventArgs.Empty);
        }

        internal static void Shutdown() {
            lock (Sync) {
                if (!subscribed) return;
                try { SystemEvents.UserPreferenceChanged -= OnSystemPreferenceChanged; }
                catch { }
                subscribed = false;
            }
        }

        [DllImport("dwmapi.dll", PreserveSig = true)]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int valueSize);

        internal static void ApplyTitleBar(Form window) {
            // Callers own UI-thread marshalling. Do not create a hidden handle or
            // force a Form to become visible merely to request title-bar styling.
            if (window == null || window.IsDisposed || !window.IsHandleCreated || window.InvokeRequired) return;
            try {
                int value = IsDark ? 1 : 0;
                if (DwmSetWindowAttribute(window.Handle, 20, ref value, sizeof(int)) < 0)
                    DwmSetWindowAttribute(window.Handle, 19, ref value, sizeof(int));
            } catch { /* Older Windows versions retain their standard title bar. */ }
        }
    }
}
