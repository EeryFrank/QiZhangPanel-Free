// Copyright (c) 2026 EeryFrank — https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using QiZhang.NativePanel;
using QiZhang.Shared;

[assembly: AssemblyTitle("七章控制面板安装程序")]
[assembly: AssemblyProduct("七章控制面板")]
[assembly: AssemblyCompany("EeryFrank")]
[assembly: AssemblyCopyright("Copyright © 2026 EeryFrank")]
[assembly: AssemblyVersion("2.5.7.0")]
[assembly: AssemblyFileVersion("2.5.7.0")]

namespace QiZhang.Installer {
    internal sealed class InstallFailure : Exception {
        internal readonly int Code;
        internal InstallFailure(int code, string message) : base(message) { Code = code; }
        internal InstallFailure(int code, string message, Exception inner) : base(message, inner) { Code = code; }
    }
    internal sealed class InstallResult {
        public bool ok;
        public int exit_code;
        public string target;
        public string executable;
        public int files;
        public bool upgraded;
        public string message;
    }
    internal static class InstallerProgram {
        internal const string Product = "七章控制面板";
        internal const string MainExe = Product + ".exe";
        internal const string EditionLabel = "免费版";
        [DllImport("user32.dll")] private static extern bool SetProcessDPIAware();
        [STAThread]
        private static int Main(string[] args) {
            if(args.Length==2&&args[0]=="--uninstall")return UninstallerProgram.Run(args[1]);
            if (args.Length > 0 && args[0] == "--extract-test") {
                string target = args.Length > 1 ? args[1] : "";
                string resultFile = args.Length == 4 && args[2] == "--result-file" ? args[3] : "";
                InstallResult result;
                try {
                    if (args.Length != 2 && resultFile.Length == 0) throw new InstallFailure(2, "用法：--extract-test <安装目录> [--result-file <报告文件>]");
                    result = PackageInstaller.Install(target, delegate(int percent, string message) { });
                } catch (Exception ex) {
                    InstallFailure failure = ex as InstallFailure;
                    result = new InstallResult { ok = false, exit_code = failure == null ? 4 : failure.Code, target = target, message = ex.Message };
                }
                if (resultFile.Length > 0) {
                    try {
                        string full = Path.GetFullPath(resultFile);
                        Directory.CreateDirectory(Path.GetDirectoryName(full));
                        File.WriteAllText(full, new JavaScriptSerializer().Serialize(result), new UTF8Encoding(false));
                    } catch { return 6; }
                }
                return result.exit_code;
            }
            if (args.Length > 0) return 2;
            SetProcessDPIAware();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string existingDirectory = InstallationOptions.DefaultInstallDirectory();
            AppTheme.Initialize(InstallationOptions.ReadThemeMode(existingDirectory), InstallationOptions.ReadThemeAccent(existingDirectory));
            try { Application.Run(new InstallerForm()); }
            finally { AppTheme.Shutdown(); }
            return 0;
        }
    }

    internal static class PackageInstaller {
        private const long MaximumExpandedBytes = 1024L * 1024 * 1024;
        private const int MaximumFiles = 20000;
        private sealed class Entry {
            internal ZipArchiveEntry Source;
            internal string Relative;
            internal bool Directory;
        }
        private sealed class Change {
            internal string Target;
            internal string Backup;
            internal bool BackedUp;
            internal bool Installed;
        }
        private static string Full(string path) { return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar); }
        private static bool Within(string path, string root) { return path.StartsWith(root.TrimEnd('\\', '/') + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase); }
        private static string CheckedChild(string root, string relative) {
            string path = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!Within(path, root)) throw new InstallFailure(2, "安装包含越界路径，已拒绝安装。");
            return path;
        }
        private static bool Exists(string path) { return File.Exists(path) || Directory.Exists(path); }


        internal static string ReadDisclaimer() {
            using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("panel.zip"))
            using (ZipArchive archive = new ZipArchive(resource, ZipArchiveMode.Read, false)) {
                ZipArchiveEntry document = archive.Entries.FirstOrDefault(entry => String.Equals(entry.FullName.Replace('\\', '/').Split('/').Last(), "免责说明.md", StringComparison.OrdinalIgnoreCase));
                if (document == null || document.Length > 262144) return "当前程序包未附有效的免责说明，请联系提供程序包的人获取说明。";
                using (StreamReader reader = new StreamReader(document.Open(), Encoding.UTF8, true)) {
                    StringBuilder text = new StringBuilder(); char[] buffer = new char[4096]; int count;
                    while ((count = reader.Read(buffer, 0, buffer.Length)) > 0) {
                        if (text.Length + count > 262144) throw new InstallFailure(2, "免责说明文件过大。");
                        text.Append(buffer, 0, count);
                    }
                    return text.ToString();
                }
            }
        }
        internal static void CheckNoReparse(string path) {
            string current = Path.GetFullPath(path);
            while (!String.IsNullOrEmpty(current)) {
                if (Exists(current) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                    throw new InstallFailure(2, "安装路径不能包含符号链接、目录联接或重解析点：" + current);
                DirectoryInfo parent = Directory.GetParent(current);
                if (parent == null) break;
                current = parent.FullName;
            }
        }
        internal static string ValidateTarget(string input) {
            if (String.IsNullOrWhiteSpace(input) || !Path.IsPathRooted(input) || input.StartsWith("\\\\", StringComparison.Ordinal))
                throw new InstallFailure(2, "请选择本机磁盘中的完整安装目录。");
            string path;
            try { path = Path.GetFullPath(input.Trim()); }
            catch (Exception ex) { throw new InstallFailure(2, "安装目录格式无效。", ex); }
            string root = Path.GetPathRoot(path);
            if (root.Length != 3 || root[1] != ':' || String.Equals(path.TrimEnd('\\', '/'), root.TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase))
                throw new InstallFailure(2, "不能安装到磁盘根目录，请选择一个专用文件夹。");
            path = Full(path);
            ValidateName(path.Substring(root.Length));
            string windows = Full(Environment.GetFolderPath(Environment.SpecialFolder.Windows));
            if (String.Equals(path, windows, StringComparison.OrdinalIgnoreCase) || Within(path, windows))
                throw new InstallFailure(2, "不能将程序安装到 Windows 系统目录。");
            if (File.Exists(path)) throw new InstallFailure(2, "安装路径被同名文件占用，请选择其他文件夹。");
            CheckNoReparse(path);
            string editionFile=Path.Combine(path,"edition.json");
            if(File.Exists(editionFile)){
                CheckNoReparse(editionFile);
                if(new FileInfo(editionFile).Length>16384)throw new InstallFailure(2,"现有安装标识无效，请选择新的独立目录。");
                try {
                    var record=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(editionFile,Encoding.UTF8));object edition;
                    if(record==null||!record.TryGetValue("edition",out edition)||Convert.ToString(edition)!="free")throw new InstallFailure(2,"当前目录不是免费版安装，请选择新的独立目录。");
                }catch(InstallFailure){throw;}catch(Exception error){throw new InstallFailure(2,"无法确认现有安装标识，请选择新的独立目录。",error);}
            }
            return path;
        }
        private static void ValidateName(string name) {
            string[] segments = name.Replace('\\', '/').TrimEnd('/').Split('/');
            if (name.Length == 0 || name.StartsWith("/") || name.StartsWith("\\") || segments.Length == 0)
                throw new InstallFailure(2, "安装包含无效路径。");
            foreach (string segment in segments) {
                if (segment.Length == 0 || segment == "." || segment == ".." || segment.EndsWith(".") || segment.EndsWith(" ") || segment.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                    throw new InstallFailure(2, "安装包含不安全的文件名：" + name);
                string stem = segment.Split('.')[0].ToUpperInvariant();
                if (stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL" || (stem.Length == 4 && (stem.StartsWith("COM") || stem.StartsWith("LPT")) && stem[3] >= '1' && stem[3] <= '9'))
                    throw new InstallFailure(2, "安装包含保留设备名：" + name);
            }
        }
        private static List<Entry> ReadEntries(ZipArchive archive) {
            if (archive.Entries.Count == 0 || archive.Entries.Count > MaximumFiles) throw new InstallFailure(2, "安装包文件数量无效。");
            List<string> executablePaths = new List<string>();
            foreach (ZipArchiveEntry entry in archive.Entries) {
                ValidateName(entry.FullName);
                string name = entry.FullName.Replace('\\', '/');
                int unixType = (entry.ExternalAttributes >> 16) & 0xf000;
                if ((entry.ExternalAttributes & (int)FileAttributes.ReparsePoint) != 0 || (unixType != 0 && unixType != 0x8000 && unixType != 0x4000))
                    throw new InstallFailure(2, "安装包含符号链接或不支持的文件类型。");
                if (String.Equals(name.Split('/').Last(), InstallerProgram.MainExe, StringComparison.OrdinalIgnoreCase)) executablePaths.Add(name);
            }
            if (executablePaths.Count != 1) throw new InstallFailure(2, "安装包缺少唯一的“" + InstallerProgram.MainExe + "”主程序。");
            string executable = executablePaths[0];
            string prefix = executable.Contains("/") ? executable.Substring(0, executable.LastIndexOf('/') + 1) : "";
            if (prefix.Count(c => c == '/') > 1) throw new InstallFailure(2, "安装包目录结构无效。");
            List<Entry> result = new List<Entry>();
            Dictionary<string, bool> names = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
            long total = 0;
            foreach (ZipArchiveEntry entry in archive.Entries) {
                string raw = entry.FullName.Replace('\\', '/');
                if (prefix.Length > 0 && String.Equals(raw, prefix, StringComparison.OrdinalIgnoreCase)) continue;
                if (prefix.Length > 0 && !raw.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new InstallFailure(2, "安装包存在主程序目录以外的内容。");
                string relative = raw.Substring(prefix.Length).TrimEnd('/');
                ValidateName(relative);
                string top = relative.Split('/')[0];
                if (String.Equals(top, "data", StringComparison.OrdinalIgnoreCase) || String.Equals(top, "profiles", StringComparison.OrdinalIgnoreCase) || String.Equals(top, "mcSever", StringComparison.OrdinalIgnoreCase) || String.Equals(top, "accounts.json", StringComparison.OrdinalIgnoreCase) || String.Equals(top, "native-state.json", StringComparison.OrdinalIgnoreCase))
                    throw new InstallFailure(2, "安装包不能携带或覆盖账号、工作区及 data 数据。");
                bool directory = raw.EndsWith("/");
                if (names.ContainsKey(relative)) throw new InstallFailure(2, "安装包存在重复路径：" + relative);
                names.Add(relative, directory);
                if (!directory) {
                    total = checked(total + entry.Length);
                    if (entry.Length > MaximumExpandedBytes || total > MaximumExpandedBytes) throw new InstallFailure(2, "安装包展开后超过允许大小。");
                }
                result.Add(new Entry { Source = entry, Relative = relative, Directory = directory });
            }
            foreach (Entry entry in result) {
                string[] parts = entry.Relative.Split('/');
                string ancestor = "";
                for (int i = 0; i < parts.Length - 1; ++i) {
                    ancestor = ancestor.Length == 0 ? parts[i] : ancestor + "/" + parts[i];
                    bool isDirectory;
                    if (names.TryGetValue(ancestor, out isDirectory) && !isDirectory) throw new InstallFailure(2, "安装包中的文件和文件夹路径冲突。");
                }
            }
            return result;
        }
        internal static void CheckRunning(string target) {
            int ownPid = Process.GetCurrentProcess().Id;
            foreach (Process process in Process.GetProcesses()) {
                using (process) {
                    if (process.Id == ownPid) continue;
                    string executable;
                    try { executable = process.MainModule.FileName; } catch { continue; }
                    if (Within(Path.GetFullPath(executable), target)) throw new InstallFailure(3, "此目录中的程序仍在运行。请从系统托盘退出七章控制面板，再重新安装。");
                }
            }
        }
        private static void Preflight(string target, List<Entry> entries) {
            CheckNoReparse(target);
            CheckRunning(target);
            foreach (Entry entry in entries) {
                string destination = CheckedChild(target, entry.Relative);
                CheckNoReparse(destination);
                if (entry.Directory) {
                    if (File.Exists(destination)) throw new InstallFailure(2, "目标目录与已有文件冲突：" + entry.Relative);
                    continue;
                }
                if (Directory.Exists(destination)) throw new InstallFailure(2, "目标文件与已有目录冲突：" + entry.Relative);
                if (File.Exists(destination)) {
                    try { using (FileStream probe = new FileStream(destination, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { } }
                    catch (Exception ex) { throw new InstallFailure(3, "文件正在使用或无法写入，请退出面板后重试：" + entry.Relative, ex); }
                }
            }
        }


        private static void EnsureDirectory(string directory, string target, List<string> created) {
            if (Directory.Exists(directory)) { CheckNoReparse(directory); return; }
            if (!String.Equals(directory, target, StringComparison.OrdinalIgnoreCase) && !Within(directory, target)) throw new InstallFailure(2, "安装目录越界。");
            string parent = Path.GetDirectoryName(directory);
            if (!Directory.Exists(parent) && (String.Equals(parent, target, StringComparison.OrdinalIgnoreCase) || Within(parent, target))) EnsureDirectory(parent, target, created);
            CheckNoReparse(directory);
            Directory.CreateDirectory(directory);
            created.Add(directory);
        }
        private static void DeleteOwnStage(string stage, string parent) {
            string full = Path.GetFullPath(stage);
            if (!Within(full, parent) || !Path.GetFileName(full).StartsWith(".qizhang-install-", StringComparison.Ordinal)) throw new InstallFailure(5, "临时目录验证失败，已保留文件。");
            if (!Directory.Exists(full)) return;
            DeleteCheckedTree(full, full);
        }
        private static void DeleteCheckedTree(string directory, string stage) {
            if (!String.Equals(directory, stage, StringComparison.OrdinalIgnoreCase) && !Within(directory, stage)) throw new InstallFailure(5, "临时目录越界，已保留文件。");
            CheckNoReparse(directory);
            foreach (string file in Directory.GetFiles(directory)) { CheckNoReparse(file); File.Delete(file); }
            foreach (string child in Directory.GetDirectories(directory)) DeleteCheckedTree(child, stage);
            Directory.Delete(directory, false);
        }
        internal static InstallResult Install(string input, Action<int, string> progress) {
            string target = ValidateTarget(input);
            string parent = Path.GetDirectoryName(target);
            string mutexName;
            using (SHA256 hash = SHA256.Create()) mutexName = "Local\\QiZhangInstaller-" + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(target.ToUpperInvariant()))).Replace("-", "");
            using (Mutex mutex = new Mutex(false, mutexName)) {
                bool acquired;
                try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) throw new InstallFailure(3, "此目录已有安装任务正在执行。");
                try {
                    using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("panel.zip")) {
                        if (resource == null) throw new InstallFailure(2, "安装程序没有包含程序包。");
                        using (ZipArchive archive = new ZipArchive(resource, ZipArchiveMode.Read, false)) {
                            List<Entry> entries = ReadEntries(archive);
                            progress(5, "检查安装目录和运行状态…");
                            Preflight(target, entries);
                            CheckNoReparse(parent);
                            Directory.CreateDirectory(parent);
                            string stage = Path.Combine(parent, ".qizhang-install-" + Guid.NewGuid().ToString("N"));
                            string unpacked = Path.Combine(stage, "payload"), backup = Path.Combine(stage, "backup");
                            Directory.CreateDirectory(unpacked); Directory.CreateDirectory(backup);
                            List<Change> changes = new List<Change>();
                            List<string> created = new List<string>();
                            bool keepRecovery = false, upgraded = false;
                            try {
                                int index = 0; long expanded = 0;
                                foreach (Entry entry in entries) {
                                    string destination = CheckedChild(unpacked, entry.Relative);
                                    if (entry.Directory) Directory.CreateDirectory(destination);
                                    else {
                                        Directory.CreateDirectory(Path.GetDirectoryName(destination));
                                        using (Stream source = entry.Source.Open())
                                        using (FileStream file = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                                            byte[] buffer = new byte[81920]; int count; long length = 0;
                                            while ((count = source.Read(buffer, 0, buffer.Length)) != 0) {
                                                length += count; expanded += count;
                                                if (length > entry.Source.Length || expanded > MaximumExpandedBytes) throw new InstallFailure(2, "安装包内容大小异常。");
                                                file.Write(buffer, 0, count);
                                            }
                                            if (length != entry.Source.Length) throw new InstallFailure(2, "安装包文件不完整。");
                                            file.Flush(true);
                                        }
                                    }
                                    progress(5 + (int)(50.0 * (++index) / entries.Count), "正在准备程序文件…");
                                }
                                // Revalidate under the installation mutex immediately before replacements.
                                Preflight(target, entries);
                                EnsureDirectory(target, target, created);
                                index = 0;
                                foreach (Entry entry in entries) {
                                    string destination = CheckedChild(target, entry.Relative);
                                    if (entry.Directory) { EnsureDirectory(destination, target, created); continue; }
                                    EnsureDirectory(Path.GetDirectoryName(destination), target, created);
                                    CheckNoReparse(destination);
                                    Change change = new Change { Target = destination, Backup = CheckedChild(backup, entry.Relative) };
                                    changes.Add(change);
                                    if (File.Exists(destination)) {
                                        Directory.CreateDirectory(Path.GetDirectoryName(change.Backup));
                                        File.Move(destination, change.Backup); change.BackedUp = true; upgraded = true;
                                    }
                                    File.Move(CheckedChild(unpacked, entry.Relative), destination); change.Installed = true;
                                    progress(55 + (int)(40.0 * (++index) / entries.Count), "正在安装“" + entry.Relative + "”…");
                                }
                                progress(100, "安装完成");
                                return new InstallResult { ok = true, exit_code = 0, target = target, executable = Path.Combine(target, InstallerProgram.MainExe), files = changes.Count, upgraded = upgraded, message = "七章控制面板安装完成。" };
                            } catch (Exception ex) {
                                List<string> rollbackErrors = new List<string>();
                                for (int i = changes.Count - 1; i >= 0; --i) {
                                    Change change = changes[i];
                                    try {
                                        if (!Within(change.Target, target) || !Within(change.Backup, backup)) throw new IOException("恢复路径无效。");
                                        CheckNoReparse(change.Target); CheckNoReparse(change.Backup);
                                        if (change.Installed && File.Exists(change.Target)) File.Delete(change.Target);
                                        if (change.BackedUp && File.Exists(change.Backup)) File.Move(change.Backup, change.Target);
                                    } catch { rollbackErrors.Add(change.Target); }
                                }
                                for (int i = created.Count - 1; i >= 0; --i) {
                                    try { if (Directory.Exists(created[i]) && Directory.GetFileSystemEntries(created[i]).Length == 0) { CheckNoReparse(created[i]); Directory.Delete(created[i], false); } }
                                    catch { }
                                }
                                if (rollbackErrors.Count > 0) {
                                    keepRecovery = true;
                                    throw new InstallFailure(5, "安装未完成，部分原文件无法自动恢复。请保留恢复目录：\r\n" + stage + "\r\n原因：" + ex.Message, ex);
                                }
                                InstallFailure known = ex as InstallFailure;
                                throw new InstallFailure(known == null ? 4 : known.Code, "安装未完成，已还原本次修改。\r\n" + ex.Message, ex);
                            } finally {
                                if (!keepRecovery) { try { DeleteOwnStage(stage, parent); } catch { } }
                            }
                        }
                    }
                } catch (InvalidDataException ex) { throw new InstallFailure(2, "内嵌程序包无效或已损坏。", ex); }
                finally { mutex.ReleaseMutex(); }
            }
        }
    }

    internal sealed class InstallerForm : Form {
        private readonly TextBox folder;
        private readonly Button browse, install, open, uninstall;
        private readonly CheckBox startup, desktop, launch;
        private readonly ProgressBar progress;
        private readonly Label state, explanation, startupHint;
        private readonly LinkLabel agreement;
        private readonly Panel scrollBody, explanationScroll;
        private readonly TableLayoutPanel body, footer;
        private readonly List<Label> wrappedLabels = new List<Label>();
        private bool busy;
        private string installedDirectory;
        internal InstallerForm() {
            Text = "安装七章控制面板 · " + InstallerProgram.EditionLabel; AutoScaleMode = AutoScaleMode.Dpi; AutoScaleDimensions = new SizeF(96F, 96F); ClientSize = new Size(700, 650); MinimumSize = new Size(620, 610); StartPosition = FormStartPosition.CenterScreen;
            Icon = Icon.ExtractAssociatedIcon(typeof(InstallerForm).Assembly.Location);
            Font = new Font("Microsoft YaHei UI", 10F); BackColor = Ui.Canvas; MaximizeBox = true;
            scrollBody = new Panel { Name = "InstallerFixedBody", Dock = DockStyle.Fill, AutoScroll = false, Padding = new Padding(24, 12, 24, 6) };
            body = new TableLayoutPanel { Name = "InstallerBody", Dock = DockStyle.Fill, AutoSize = false, ColumnCount = 1, Padding = new Padding(0), Margin = new Padding(0) };
            body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            Ui.Role(AddBodyLabel("七章控制面板", new Font(Font.FontFamily, 22F, FontStyle.Bold), Ui.Ink, 0, 4), "title");
            Ui.Role(AddBodyLabel(InstallerProgram.EditionLabel + " " + Assembly.GetExecutingAssembly().GetName().Version.ToString(3) + " · 可自定义安装位置", Font, Ui.Muted, 0, 10), "muted");
            AddBodyLabel("安装目录", Font, ForeColor, 0, 4);
            var folderRow = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2, Margin = new Padding(0, 0, 0, 8) };
            folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            folder = new TextBox { Name = "InstallFolder", Text = InstallationOptions.DefaultInstallDirectory(), Dock = DockStyle.Fill, Margin = new Padding(0, 5, 10, 5) };
            browse = new NativeActionButton { Text = "浏览…", AutoSize = true, MinimumSize = new Size(92, 34), Margin = new Padding(0) };
            browse.Click += delegate { using (FolderBrowserDialog dialog = new FolderBrowserDialog { Description = "选择七章控制面板的安装目录", ShowNewFolderButton = true }) { if (Directory.Exists(folder.Text)) dialog.SelectedPath = folder.Text; if (dialog.ShowDialog(this) == DialogResult.OK) folder.Text = dialog.SelectedPath; } };
            folderRow.Controls.Add(folder, 0, 0); folderRow.Controls.Add(browse, 1, 0); AddBody(folderRow);
            explanationScroll = new Panel { Name = "InstallerExplanationScroll", Dock = DockStyle.Fill, AutoScroll = true, Padding = new Padding(10, 8, 10, 8), Margin = new Padding(0, 0, 0, 8), TabStop = true };
            Ui.Role(explanationScroll, "surface");
            explanation = new Label { Text = "程序包已包含 Python 运行组件，无需单独安装。需要 64 位 Windows 与 .NET Framework 4.8。安装过程无需联网，不会开停游戏服务器，也不会覆盖账号与工作区数据。升级前请先从系统托盘退出面板。", Font = Font, AutoSize = true, Dock = DockStyle.Top, UseMnemonic = false, Name = "InstallerExplanation" };
            explanation.Text = "免费版提供单服务器、安装导入、控制台、基础设置和手动备份恢复。每份安装仅管理一个服务器，账号共享此数量限制。升级或更换版本保留原账号、配置和服务器文件。已包含 Python；需要 64 位 Windows 与 .NET Framework 4.8。安装无需密钥。升级前请从系统托盘退出面板。";
            Ui.Role(explanation, "muted"); explanationScroll.Controls.Add(explanation); AddBody(explanationScroll); body.RowStyles[body.RowCount-1].SizeType=SizeType.Percent;body.RowStyles[body.RowCount-1].Height=100;
            startup = AddOption("Windows 登录后启动七章控制面板（普通权限）", false); startup.Name = "StartupOption";
            startupHint = AddBodyLabel("开机启动权限可在面板的软件设置中调整。", Font, Ui.Muted, 0, 5); startupHint.Name = "StartupHint"; Ui.Role(startupHint, "muted");
            desktop = AddOption("创建桌面快捷方式", true); desktop.Name = "DesktopShortcutOption";
            launch = AddOption("安装完成后启动七章控制面板", false); launch.Name = "LaunchOption";
            scrollBody.Controls.Add(body);
            footer = new TableLayoutPanel { Name = "InstallerPinnedFooter", Dock = DockStyle.Bottom, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, ColumnCount = 1, Padding = new Padding(24, 8, 24, 0), BackColor = Ui.Surface, Margin = new Padding(0) }; Ui.Role(footer, "surface");
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            agreement = new LinkLabel { Name = "InstallAgreement", Text = "点击“安装”即表示你已阅读并同意《免责声明》。", AutoSize = true, Dock = DockStyle.Top, Font = new Font(Font, FontStyle.Bold), ForeColor = Ui.Ink, LinkColor = Ui.Primary, ActiveLinkColor = Ui.Primary, Margin = new Padding(0, 0, 0, 10), UseMnemonic = false };
            int linkStart = agreement.Text.IndexOf("《免责声明》", StringComparison.Ordinal); agreement.Links.Clear(); agreement.Links.Add(linkStart, "《免责声明》".Length, "disclaimer"); agreement.LinkClicked += delegate { ShowDisclaimer(); }; AddFooter(agreement);
            progress = new ProgressBar { Name = "InstallProgress", Dock = DockStyle.Top, Height = 12, Margin = new Padding(0, 0, 0, 7) }; AddFooter(progress);
            state = new Label { Name = "InstallState", Text = "选择目录后点击安装。", Dock = DockStyle.Top, Height = 27, AutoEllipsis = true, Margin = new Padding(0, 0, 0, 6), UseMnemonic = false }; AddFooter(state);
            var actions = new FlowLayoutPanel { Name = "InstallActions", Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, FlowDirection = FlowDirection.RightToLeft, WrapContents = true, Margin = new Padding(0) };
            install = new NativeActionButton { Name = "InstallButton", Text = "安装", AutoSize = true, MinimumSize = new Size(128, 39), Padding = new Padding(12, 3, 12, 3), BackColor = Ui.Primary, ForeColor = Ui.OnPrimary, FlatStyle = FlatStyle.Flat, Margin = new Padding(10, 0, 0, 8) }; Ui.Role(install, "primary"); install.Click += async delegate { await InstallAsync(); };
            open = new NativeActionButton { Name = "OpenInstallFolder", Text = "打开安装目录", AutoSize = true, MinimumSize = new Size(148, 39), Padding = new Padding(8, 3, 8, 3), Enabled = false, Margin = new Padding(0, 0, 0, 8) }; open.Click += delegate { if (Directory.Exists(installedDirectory)) Process.Start(new ProcessStartInfo("explorer.exe", Quote(installedDirectory)) { UseShellExecute = true }); };
            uninstall = new NativeActionButton {Name="UninstallButton",Text="卸载…",AutoSize=true,MinimumSize=new Size(96,39),Margin=new Padding(0,0,8,8)};
            uninstall.Click+=delegate{if(busy)return;try{using(var dialog=new UninstallerForm(folder.Text))dialog.ShowDialog(this);}catch(Exception error){Ui.Message(this,error.Message,"无法卸载",MessageBoxIcon.Warning);}};
            actions.Controls.Add(install); actions.Controls.Add(open);actions.Controls.Add(uninstall); AddFooter(actions);
            LinkLabel ownership = OwnershipFooter(); ownership.Dock = DockStyle.Top; ownership.Margin = new Padding(0); AddFooter(ownership);
            Controls.Add(scrollBody); Controls.Add(footer); AcceptButton = install;
            folder.TextChanged += delegate { RefreshStartupChoice();  }; scrollBody.ClientSizeChanged += delegate { UpdateWrapping(); }; explanationScroll.ClientSizeChanged += delegate { UpdateWrapping(); }; footer.ClientSizeChanged += delegate { UpdateWrapping(); }; FontChanged += delegate { UpdateWrapping(); }; Shown += delegate { UpdateWrapping(); };
            RefreshStartupChoice();  UpdateWrapping();
            Ui.ApplyTheme(this); AppTheme.Changed += ThemeChanged; Disposed += delegate { AppTheme.Changed -= ThemeChanged; };
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) { e.Cancel = true; state.Text = "正在安装，请等待文件写入完成。"; } };
        }
        private void ThemeChanged(object sender, EventArgs e) {
            if (IsDisposed || !IsHandleCreated) return;
            if (InvokeRequired) { try { BeginInvoke((Action)delegate { ThemeChanged(sender, e); }); } catch (InvalidOperationException) { } return; }
            foreach (Form form in Application.OpenForms) { Ui.ApplyTheme(form); form.Invalidate(true); }
            UpdateWrapping();
        }
        private void AddBody(Control control) { int row = body.RowCount++; body.RowStyles.Add(new RowStyle(SizeType.AutoSize)); body.Controls.Add(control, 0, row); }
        private void AddFooter(Control control) { int row = footer.RowCount++; footer.RowStyles.Add(new RowStyle(SizeType.AutoSize)); footer.Controls.Add(control, 0, row); }
        private Label AddBodyLabel(string text, Font font, Color color, int top, int bottom) { var label = new Label { Text = text, Font = font, ForeColor = color, AutoSize = false, Dock = DockStyle.Top, Margin = new Padding(0, top, 0, bottom), UseMnemonic = false }; wrappedLabels.Add(label); AddBody(label); return label; }
        private CheckBox AddOption(string text, bool selected) { var option = new CheckBox { Text = text, Checked = selected, Dock = DockStyle.Top, AutoSize = false, Height = 30, Margin = new Padding(0, 0, 0, 5), UseMnemonic = false }; AddBody(option); return option; }
        private void UpdateWrapping() {
            if (scrollBody == null || footer == null) return;
            int width = Math.Max(160, scrollBody.ClientSize.Width - scrollBody.Padding.Horizontal - 2);
            foreach (Label label in wrappedLabels) { int height=TextRenderer.MeasureText(label.Text,label.Font,new Size(width,Int32.MaxValue),TextFormatFlags.WordBreak|TextFormatFlags.TextBoxControl|TextFormatFlags.NoPrefix).Height; if(label.Height!=height)label.Height=height; }
            foreach (CheckBox option in new CheckBox[] { startup, desktop, launch }) if (option != null) { int desired = Math.Max(30, TextRenderer.MeasureText(option.Text, option.Font, new Size(Math.Max(80, width - 30), Int32.MaxValue), TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl).Height + 12); if (option.Height != desired) option.Height = desired; }
            if (agreement != null) { int footerWidth = Math.Max(160, footer.ClientSize.Width - footer.Padding.Horizontal); if (agreement.MaximumSize.Width != footerWidth) agreement.MaximumSize = new Size(footerWidth, 0); }
            if (explanation != null && explanationScroll != null) { int noteWidth=Math.Max(120,explanationScroll.ClientSize.Width-explanationScroll.Padding.Horizontal-SystemInformation.VerticalScrollBarWidth-2);if(explanation.MaximumSize.Width!=noteWidth)explanation.MaximumSize=new Size(noteWidth,0); }
            if (body != null && launch != null && footer.IsHandleCreated) {
                int fixedHeight=scrollBody.Padding.Vertical+footer.Height+64;
                foreach(Control control in body.Controls) if(control!=explanationScroll) fixedHeight+=control.Height+control.Margin.Vertical;
                fixedHeight+=Math.Max(42,Height-ClientSize.Height+42);
                if(MinimumSize.Height!=fixedHeight) MinimumSize=new Size(MinimumSize.Width,fixedHeight);
            }
        }
        private void RefreshStartupChoice() {
            if (busy || startup == null || startupHint == null) return;
            bool existingAccounts = InstallationOptions.HasAccounts(folder.Text);
            startup.Checked = InstallationOptions.ReadStartupEnabled(folder.Text); startup.Enabled = !existingAccounts;
            startupHint.Text = existingAccounts ? "已有账号的开机启动设置将保留，请在面板软件设置中调整。" : "开机启动权限可在面板的软件设置中调整。";


            UpdateWrapping();
        }

        private void ShowDisclaimer() {
            try {
                using (Form dialog = new Form { Text = "七章控制面板 · 免责声明", ClientSize = new Size(720, 520), MinimumSize = new Size(480, 360), StartPosition = FormStartPosition.CenterParent, Font = Font, Icon = Icon, MinimizeBox = false }) {
                    RichTextBox text = new RichTextBox { Name = "DisclaimerFullText", Dock = DockStyle.Fill, ReadOnly = true, DetectUrls = false, BorderStyle = BorderStyle.None, BackColor = Ui.Surface, Font = Font, WordWrap = true, ScrollBars = RichTextBoxScrollBars.Vertical, Text = PackageInstaller.ReadDisclaimer() };
                    Button close = new NativeActionButton { Text = "关闭", Dock = DockStyle.Bottom, Height = 42, DialogResult = DialogResult.OK };
                    dialog.Controls.Add(text); dialog.Controls.Add(OwnershipFooter()); dialog.Controls.Add(close); dialog.AcceptButton = close; dialog.CancelButton = close; Ui.ApplyTheme(dialog); dialog.ShowDialog(this);
                }
            } catch (Exception ex) { Ui.Message(this, ex.Message, "读取免责声明失败", MessageBoxIcon.Warning); }
        }
        private LinkLabel OwnershipFooter() {
            LinkLabel footer = new LinkLabel { Name = "OwnershipFooter", Text = "© 2026 EeryFrank 所有", Dock = DockStyle.Bottom, Height = 30, TextAlign = ContentAlignment.MiddleCenter, LinkColor = Ui.Primary };
            footer.LinkClicked += delegate { try { Process.Start(new ProcessStartInfo("https://github.com/EeryFrank") { UseShellExecute = true }); } catch (Exception ex) { Ui.Message(this, ex.Message, "无法打开链接", MessageBoxIcon.Information); } };
            return footer;
        }
        private static string Quote(string value) { return "\"" + value.Replace("\"", "") + "\""; }
        private async Task InstallAsync() {
            if (busy) return;
            bool startAfter = launch.Checked, startWithWindows = startup.Checked, desktopShortcut = desktop.Checked;
            busy = true; install.Enabled = browse.Enabled = folder.Enabled = launch.Enabled = startup.Enabled = desktop.Enabled = open.Enabled = uninstall.Enabled = false;
            string target = folder.Text;
            try {
                InstallResult result = await Task.Run(delegate { return PackageInstaller.Install(target, delegate(int percent, string message) { BeginInvoke((Action)delegate { progress.Value = Math.Max(0, Math.Min(100, percent)); state.Text = message; }); }
                ); });
                var warnings = new List<string>();
                try { warnings.AddRange(await Task.Run(delegate { return InstallationOptions.Apply(result.target, startWithWindows, desktopShortcut); })); }
                catch (Exception ex) { warnings.Add("程序已安装，但附加选项未能完成：" + ex.Message); }
                installedDirectory = result.target; folder.Text = installedDirectory; state.Text = "安装完成：" + installedDirectory; open.Enabled = true; install.Text = "重新安装";
                if (warnings.Count > 0) Ui.Message(this, "程序已安装，但以下选项需要留意：\r\n\r\n" + String.Join("\r\n", warnings), "安装完成", MessageBoxIcon.Warning);
                if (startAfter) {
                    try { Process.Start(new ProcessStartInfo(result.executable) { UseShellExecute = false, WorkingDirectory = result.target, WindowStyle = ProcessWindowStyle.Normal }); }
                    catch (Exception ex) { Ui.Message(this, "安装已完成，但程序未能自动启动：\r\n" + ex.Message, "七章控制面板", MessageBoxIcon.Warning); }
                }
            } catch (Exception ex) { progress.Value = 0; state.Text = "安装未完成，请查看提示。"; Ui.Message(this, ex.Message, "安装未完成", MessageBoxIcon.Warning); }
            finally {
                busy = false; install.Enabled = browse.Enabled = folder.Enabled = launch.Enabled = desktop.Enabled = uninstall.Enabled = true; open.Enabled = Directory.Exists(installedDirectory); RefreshStartupChoice(); }
        }
    }
}
