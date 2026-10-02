// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace QiZhang.Installer {
    internal static class InstallationOptions {
        internal static string ReadThemeAccent(string target) {
            try {
                var values = ReadRecord(Path.Combine(target, "data", "native-ui-settings.json")); object value;
                string accent = values.TryGetValue("theme_accent", out value) ? Convert.ToString(value) : "green";
                return accent == "blue" || accent == "violet" || accent == "rose" || accent == "amber" || accent == "teal" || accent == "slate" ? accent : "green";
            } catch { return "green"; }
        }
        internal static string ReadThemeMode(string target) {
            try {
                var values = ReadRecord(Path.Combine(target, "data", "native-ui-settings.json")); object value;
                string mode = values.TryGetValue("theme_mode", out value) ? Convert.ToString(value) : "system";
                return mode == "light" || mode == "dark" ? mode : "system";
            } catch { return "system"; }
        }
        internal static string DefaultInstallDirectory() {
            string known = QiZhang.Shared.InstallationLocation.FindExisting();
            if (!String.IsNullOrEmpty(known)) return known;
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "七章控制面板免费版");
        }
        private static Dictionary<string, object> ReadRecord(string file) {
            return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(file, Encoding.UTF8));
        }
        internal static bool HasAccounts(string target) {
            try {
                string file = Path.Combine(target, "data", "accounts.json");
                if (!File.Exists(file)) return false;
                var record = ReadRecord(file); object accounts;
                if (record == null || !record.TryGetValue("accounts", out accounts) || !(accounts is ICollection)) return true;
                return ((ICollection)accounts).Count > 0;
            } catch { return true; }
        }
        internal static bool ReadStartupEnabled(string target) {
            try {
                string file = Path.Combine(target, "data", "startup-registration.json");
                if (!File.Exists(file)) return false;
                var record = ReadRecord(file); object enabled;
                return record != null && record.TryGetValue("enabled", out enabled) && enabled is bool && (bool)enabled;
            } catch { return false; }
        }
        private static string Quote(string value) {
            var result = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value) {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); slashes = 0; continue; }
                result.Append('\\', slashes); slashes = 0; result.Append(c);
            }
            result.Append('\\', slashes * 2); result.Append('"'); return result.ToString();
        }
        internal static List<string> Apply(string target, bool startup, bool desktop) {
            return ApplyOptions(target, startup, desktop, true);
        }
        private static List<string> ApplyOptions(string target, bool startup, bool desktop, bool rememberLocation) {
            var warnings = new List<string>();
            if (rememberLocation) QiZhang.Shared.InstallationLocation.Remember(target, System.Reflection.Assembly.GetExecutingAssembly().GetName().Version.ToString(3));
            if(rememberLocation) try {PackageUninstaller.Register(target);} catch(Exception error) {warnings.Add("卸载入口登记未完成："+error.Message);}
            string cache = Path.Combine(Path.GetTempPath(), "QiZhangControlPanel-installer");
            string report = Path.Combine(cache, "install-options-" + Guid.NewGuid().ToString("N") + ".json");
            try {
                Directory.CreateDirectory(cache);
                // The helper validates state paths before writing any installation data.
                string helper = Path.Combine(target, "backend", "native_install_options.py");
                string args = "-B " + Quote(helper) + " --target " + Quote(target)
                    + " --startup " + (startup ? "true" : "false") + " --desktop " + (desktop ? "true" : "false")
                    + " --desktop-directory " + Quote(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory))
                    + " --result-file " + Quote(report);
                var info = new ProcessStartInfo(Path.Combine(target, "runtime", "python.exe"), args) {
                    UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden,
                    WorkingDirectory = target, RedirectStandardError = true, RedirectStandardOutput = true
                };
                using (var process = Process.Start(info)) {
                    process.BeginOutputReadLine(); process.BeginErrorReadLine();
                    if (!process.WaitForExit(210000)) { try { process.Kill(); } catch { } throw new IOException("安装选项设置超时，可在软件设置中检查开机启动。"); }
                    if (process.ExitCode != 0 || !File.Exists(report)) throw new IOException("安装选项设置未完成，可从安装目录直接运行面板。");
                }
                var result = ReadRecord(report); object values;
                if (result != null && result.TryGetValue("warnings", out values) && values is IEnumerable)
                    foreach (object value in (IEnumerable)values) warnings.Add(Convert.ToString(value));
            } catch (Exception error) { warnings.Add(error.Message); }
            finally { try { if (File.Exists(report)) File.Delete(report); } catch { } }
            return warnings;
        }
    }
}
