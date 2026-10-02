// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Globalization;
using System.IO;
using Microsoft.Win32;

namespace QiZhang.Shared {
    internal static class InstallationLocation {
        internal const string RegistryPath = @"Software\EeryFrank\QiZhangPanelFree";
        internal const string ExecutableName = "七章控制面板.exe";

        private static string ValidatedDirectory(string directory) {
            try {
                if (String.IsNullOrWhiteSpace(directory) || !Path.IsPathRooted(directory)) return null;
                string full = Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                if (!Directory.Exists(full) || !File.Exists(Path.Combine(full, ExecutableName)) || !File.Exists(Path.Combine(full, "native-host.py"))) return null;
                if (!File.Exists(Path.Combine(full, "runtime", "python.exe")) && !File.Exists(Path.Combine(full, "portable.flag"))) return null;
                return full;
            } catch { return null; }
        }

        internal static void Remember(string bundleRoot, string version) {
            try { Remember(bundleRoot, version, Registry.CurrentUser, RegistryPath); }
            catch { /* Location discovery must never prevent the app from opening. */ }
        }

        internal static string FindExisting() {
            try { return FindExisting(Registry.CurrentUser, RegistryPath); }
            catch { return null; }
        }

        // An explicit root/key overload keeps QA registrations separate from the
        // current user's real installation record. The caller owns registryRoot.
        internal static void Remember(string bundleRoot, string version, RegistryKey registryRoot, string keyPath) {
            try {
                string full = ValidatedDirectory(bundleRoot);
                if (full == null || registryRoot == null || String.IsNullOrWhiteSpace(keyPath)) return;
                using (RegistryKey key = registryRoot.CreateSubKey(keyPath)) {
                    if (key == null) return;
                    key.SetValue("InstallPath", full, RegistryValueKind.String);
                    key.SetValue("ExecutablePath", Path.Combine(full, ExecutableName), RegistryValueKind.String);
                    key.SetValue("Version", version ?? "", RegistryValueKind.String);
                    key.SetValue("UpdatedAtUtc", DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture), RegistryValueKind.String);
                }
            } catch { /* A locked-down registry is compatible with portable use. */ }
        }

        internal static string FindExisting(RegistryKey registryRoot, string keyPath) {
            try {
                if (registryRoot == null || String.IsNullOrWhiteSpace(keyPath)) return null;
                using (RegistryKey key = registryRoot.OpenSubKey(keyPath, false)) {
                    if (key == null) return null;
                    string directory = key.GetValue("InstallPath", null, RegistryValueOptions.DoNotExpandEnvironmentNames) as string;
                    return ValidatedDirectory(directory);
                }
            } catch { return null; }
        }
    }
}
