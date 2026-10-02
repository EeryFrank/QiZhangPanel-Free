// QiZhang Control Panel - original panel code belongs to EeryFrank.
// https://github.com/EeryFrank - third-party rights and licenses remain unchanged.
using System;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal sealed partial class NativeMainForm {
        private sealed class AdminOption {
            internal string Key;
            internal string Label;
            internal AdminOption(string key, string label) { Key = key; Label = label; }
            public override string ToString() { return Label; }
        }

        private Control BuildAdministrationPage(string key) {
            if (key == "servers") return AdminServers();
            if (key == "settings") return AdminSettings(false);
            if (key == "backups") return AdminBackups();
            if (key == "account") return AdminAccount();
            return null;
        }

        private static ComboBox AdminCombo(params string[] pairs) {
            ComboBox combo = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 290 };
            for (int i = 0; i + 1 < pairs.Length; i += 2) combo.Items.Add(new AdminOption(pairs[i], pairs[i + 1]));
            if (combo.Items.Count > 0) combo.SelectedIndex = 0;
            return combo;
        }
        private static string AdminKey(ComboBox combo) { return combo.SelectedItem is AdminOption ? ((AdminOption)combo.SelectedItem).Key : ""; }
        private static void AdminChoose(ComboBox combo, string key) {
            for (int i = 0; i < combo.Items.Count; ++i) if (((AdminOption)combo.Items[i]).Key == key) { combo.SelectedIndex = i; return; }
        }
        private static NumericUpDown AdminNumber(decimal low, decimal high, decimal value) {
            return new NumericUpDown { Minimum = low, Maximum = high, Value = Math.Max(low, Math.Min(high, value)), Width = 190, ThousandsSeparator = true };
        }
        private static decimal AdminDecimal(Dictionary<string, object> source, string key, decimal fallback) {
            object value;
            decimal parsed;
            return source.TryGetValue(key, out value) && Decimal.TryParse(Convert.ToString(value, CultureInfo.InvariantCulture), NumberStyles.Number, CultureInfo.InvariantCulture, out parsed) ? parsed : fallback;
        }
        private static TextBox AdminText(string value, bool password) {
            return new TextBox { Text = value ?? "", Width = 370, UseSystemPasswordChar = password, MaxLength = password ? 128 : 1000 };
        }
        private static Panel AdminContainer(string title, string description, Control body, params Control[] actions) {
            Panel panel = new Panel { Dock = DockStyle.Fill, Padding = new Padding(20, 16, 20, 14), Name = "AdminPage" };
            Panel heading = new Panel { Dock = DockStyle.Top, Height = 76, Name = "AdminPageHeadingPanel" };
            Label headingTitle = new Label { Text = title, Dock = DockStyle.Top, Height = 34, Name = "AdminPageHeading", AutoEllipsis = true, Font = new Font("Microsoft YaHei UI", 13F, FontStyle.Bold) };
            Label headingDescription = new Label { Text = description, Dock = DockStyle.Fill, Name = "AdminPageDescription", AutoEllipsis = false, Padding = new Padding(0, 2, 0, 10) };
            Ui.Role(headingTitle, "title"); Ui.Role(headingDescription, "muted"); Ui.Role(panel, "canvas");
            heading.Controls.Add(headingDescription); heading.Controls.Add(headingTitle);
            heading.SizeChanged += delegate { AdminFitHeading(heading); };
            body.Dock = DockStyle.Fill;
            FlowLayoutPanel toolbar = Ui.Toolbar(actions);
            toolbar.Dock = DockStyle.Top;
            toolbar.AutoSize = true;
            toolbar.WrapContents = true;
            panel.Controls.Add(body);
            panel.Controls.Add(toolbar);
            panel.Controls.Add(heading);
            return panel;
        }
        private static Panel AdminScroll(Control content) {
            Panel scroll = new Panel { AutoScroll = true, Dock = DockStyle.Fill };
            content.Dock = DockStyle.Top;
            scroll.Controls.Add(content);
            return scroll;
        }
        private Form AdminDialog(string title, TableLayoutPanel fields, Func<Task> save) {
            Form dialog = new Form { Text = title, Width = 690, Height = 655, MinimumSize = new Size(580, 420), StartPosition = FormStartPosition.CenterParent, Font = Font, MinimizeBox = false, MaximizeBox = false };
            Button submit = Ui.Button("保存", async delegate { await save(); dialog.DialogResult = DialogResult.OK; dialog.Close(); });
            submit.Name="AdminDialogSave";
            Button cancel = new Button { Text = "取消", AutoSize = true, DialogResult = DialogResult.Cancel, Padding = new Padding(10, 4, 10, 4) };
            Panel formPanel = AdminContainer(title, "填写后点击保存。", AdminScroll(fields), submit, cancel);
            dialog.Controls.Add(formPanel);
            dialog.CancelButton = cancel;
            Ui.ApplyTheme(dialog);
            return dialog;
        }
        private static bool AdminConfirm(string text) {
            return Ui.Confirm(Form.ActiveForm, text, "请确认");
        }
        private static Dictionary<string, object> AdminSelected(DataGridView grid) {
            Dictionary<string, object> item = Ui.Selected(grid);
            if (item == null || item.Count == 0) throw new InvalidOperationException("请先在列表中选择一项。");
            return item;
        }
        private static string AdminRowId(Dictionary<string, object> row) { return Ui.Text(row, "id", Ui.Text(row, "filename", Ui.Text(row, "name"))); }
        private static void AdminRefill(DataGridView grid, List<Dictionary<string, object>> rows, Func<Dictionary<string, object>, object[]> cells) {
            Dictionary<string, object> selected = Ui.Selected(grid);
            string selectedId = selected == null ? "" : AdminRowId(selected);
            int selectedIndex = -1;
            grid.Rows.Clear();
            foreach (Dictionary<string, object> row in rows) {
                int index = grid.Rows.Add(cells(row));
                grid.Rows[index].Tag = row;
                if (AdminRowId(row) == selectedId) selectedIndex = index;
            }
            if (selectedIndex >= 0 && grid.Columns.Count > 0) { grid.CurrentCell = grid.Rows[selectedIndex].Cells[0]; grid.Rows[selectedIndex].Selected = true; }
        }
        private static void AdminMessage(Dictionary<string, object> result, string fallback) { Ui.Message(Form.ActiveForm, Ui.Text(result, "message", fallback), "七章控制面板", MessageBoxIcon.Information); }

        private Control AdminServers() {
            DataGridView grid = Ui.Grid("服务器", "当前状态", "正在执行", "平台 / MC 版本", "服务器目录");
            grid.Name = "ServerSelectionGrid"; grid.RowTemplate.Height = 48;
            grid.Columns[0].FillWeight = 95; grid.Columns[1].FillWeight = 66; grid.Columns[2].FillWeight = 125; grid.Columns[3].FillWeight = 95; grid.Columns[4].FillWeight = 150;
            bool compact = false, arranging = false;
            string installHeadline = "安装任务 · 正在读取", installDetail = "正在读取安装任务…";
            ToolTip details = new ToolTip { AutoPopDelay = 18000, InitialDelay = 350, ReshowDelay = 100, ShowAlways = true };
            TextBox search = AdminText("", false); search.Name = "ServerSearch"; search.Width = 280;
            Label count = new Label { AutoSize = true, Padding = new Padding(8), Text = "正在读取服务器…" }; Ui.Role(count, "muted");
            Label problem = AdminSummary(""); problem.Visible = false; Ui.Role(problem, "warning");
            Label selection = AdminSummary("选择一台服务器，查看信息并进入管理。"); selection.Height = 68;
            Label installation = AdminSummary("正在读取安装任务…"); installation.Name = "ServerInstallationStatus"; installation.Height = 58;
            Button viewInstall = Ui.Button("查看安装详情", AdminShowInstallStatusAsync);
            Panel installStatus = new Panel { Dock = DockStyle.Top, Height = 68 };
            viewInstall.Dock = DockStyle.Right; viewInstall.Width = 176; viewInstall.AutoSize = false;
            installation.Dock = DockStyle.Fill; installStatus.Controls.Add(installation); installStatus.Controls.Add(viewInstall);
            Panel body = new Panel { Dock = DockStyle.Fill };
            body.Disposed += delegate { details.Dispose(); };
            Label empty = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, Text = "工作区中还没有服务器\r\n从上方选择：官方安装、导入 ZIP，或绑定已有文件夹。", Font = new Font(Font, FontStyle.Bold), Visible = false };
            Ui.Role(empty, "muted");
            Panel list = new Panel { Dock = DockStyle.Fill }; list.Controls.Add(grid); list.Controls.Add(empty);
            FlowLayoutPanel searchBar = Ui.Toolbar(new Label { Text = "搜索服务器", AutoSize = true, Padding = new Padding(0, 8, 8, 0) }, search, count);
            body.Controls.Add(list); body.Controls.Add(searchBar); body.Controls.Add(installStatus); body.Controls.Add(problem);
            List<Dictionary<string, object>> cached = new List<Dictionary<string, object>>(); string workspaceError = "";
            Button add = null, choose = null, remove = null, relocate = null, install = null, archive = null;
            Action updateSelection = delegate {
                Dictionary<string, object> row = Ui.Selected(grid); bool valid = row.Count > 0;
                if (choose != null) choose.Enabled = valid && workspaceError.Length == 0 && (!Ui.Bool(row, "edition_locked") || freeSlotAvailable);
                if (remove != null) remove.Enabled = valid && workspaceError.Length == 0 && (Ui.Text(row, "id") != selectedServerId || true) && !Ui.Bool(row, "edition_locked") && !Ui.Bool(row, "running") && !Ui.Bool(row, "starting");
                if (relocate != null) relocate.Enabled = valid && !Ui.Bool(row, "edition_locked") && !Ui.Bool(row, "running") && !Ui.Bool(row, "starting");
                selection.Text = valid ? Ui.Text(row, "name") + "  ·  " + AdminServerState(row, workspaceError) + (compact ? "" : "  ·  " + Ui.Text(row, "platform") + " " + Ui.Text(row, "minecraft_version") + "  ·  " + Ui.Text(row, "content_version", "未填写整合包版本")) + "\r\n" + AdminServerActivity(row) + (compact ? "" : "\r\n" + Ui.Text(row, "path")) : "选择一台服务器，查看信息并进入管理。";
                if(valid && Ui.Bool(row,"edition_locked"))selection.Text = Ui.Text(row,"name")+"  ·  "+(freeSlotAvailable?"尚未选定免费版服务器": "免费版已锁定")+"\r\n"+Ui.Text(row,"edition_lock_reason","原服务器文件与记录保留。");
                if(choose != null)choose.Text=valid && Ui.Bool(row,"edition_locked") && freeSlotAvailable ? "设为免费服务器并进入 →" : "进入服务器管理 →";
                selection.Padding = compact ? new Padding(8, 5, 8, 3) : new Padding(12, 10, 12, 8);
                selection.Height = valid ? compact ? Math.Max(52, selection.Font.Height * 2 + selection.Padding.Vertical + 4) : 89 : compact ? Math.Max(34, selection.Font.Height + selection.Padding.Vertical + 4) : 56;
                details.SetToolTip(selection, valid ? Ui.Text(row, "name") + "\r\n" + Ui.Text(row, "platform") + " " + Ui.Text(row, "minecraft_version") + "  " + Ui.Text(row, "content_version") + "\r\n" + AdminServerActivity(row) + "\r\n" + Ui.Text(row, "path") : "");
            };
            Action render = delegate {
                List<Dictionary<string, object>> rows = new List<Dictionary<string, object>>(); string query = search.Text.Trim();
                foreach (Dictionary<string, object> row in cached) {
                    string haystack = Ui.Text(row, "name") + " " + Ui.Text(row, "platform") + " " + Ui.Text(row, "minecraft_version") + " " + Ui.Text(row, "content_version") + " " + Ui.Text(row, "path");
                    if (query.Length == 0 || haystack.IndexOf(query, StringComparison.CurrentCultureIgnoreCase) >= 0) rows.Add(row);
                }
                AdminRefill(grid, rows, delegate(Dictionary<string, object> row) {
                    return new object[] { Ui.Text(row, "name"), Ui.Bool(row,"edition_locked") ? (freeSlotAvailable ? "待选择免费槽位" : "免费版锁定") : AdminServerState(row, workspaceError), AdminServerActivity(row), Ui.Text(row, "platform") + " " + Ui.Text(row, "minecraft_version"), Ui.Text(row, "path") };
                });
                count.Text = rows.Count + " / " + cached.Count + " 台服务器";
                empty.Visible = rows.Count == 0; grid.Visible = rows.Count > 0;
                empty.Text = cached.Count == 0 ? "工作区中还没有服务器\r\n从上方选择：官方安装、导入 ZIP，或绑定已有文件夹。" : "没有符合搜索条件的服务器。";
                updateSelection();
            };
            Func<Task> load = async delegate {
                Dictionary<string, object> result = await Call("servers.list");
                if (grid.IsDisposed) return;
                ReadEditionSlot(result);
                workspaceError = Ui.Text(result, "workspace_error"); problem.Visible = workspaceError.Length > 0;
                problem.Text = "工作区待修复：" + workspaceError + "\r\n目录搬移后，可选择服务器 → 更多操作 → 更改目录。";
                add.Enabled = install.Enabled = archive.Enabled = workspaceError.Length == 0 && (freeCanAddServer);
                cached = Ui.List(result, "servers"); 
                render();
                try {
                    Dictionary<string, object> job = await Call("server.install.status"); if (grid.IsDisposed) return;
                    bool active = Ui.Bool(job, "active"); string error = Ui.Text(job, "error");
                    installHeadline = "安装任务 · " + AdminInstallPhase(job) + (active ? "  " + Math.Max(0, Math.Min(100, Ui.Num(job, "progress"))).ToString("0") + "%" : "");
                    installDetail = Ui.Text(job, "message") + (error.Length > 0 ? "  " + error : "");
                    installation.Text = compact ? installHeadline : installHeadline + "\r\n" + installDetail;
                    details.SetToolTip(installation, installHeadline + "\r\n" + installDetail);
                    Ui.Role(installation, error.Length > 0 ? "danger" : active ? "warning" : "muted");
                    install.Enabled = archive.Enabled = !active && workspaceError.Length == 0 && (freeCanAddServer);
                } catch (Exception error) { if (!grid.IsDisposed) { installHeadline = "安装任务 · 状态读取失败"; installDetail = error.Message; installation.Text = compact ? installHeadline : installHeadline + "\r\n" + installDetail; details.SetToolTip(installation, installDetail); Ui.Role(installation, "warning"); } }
            };
            pageRefresh = load;
            add = Ui.Button("绑定已有文件夹\r\n自动识别启动配置", async delegate { await AdminAddServer(); await RefreshServers(); await load(); });
            choose = Ui.Button("进入服务器管理 →", async delegate {
                Dictionary<string, object> row = AdminSelected(grid);
                string target = Ui.Text(row, "id");
                await EnterServerAsync(target);
            });
            remove = Ui.Button("从面板移除（保留文件）", async delegate { await RemoveServerSelectionBindingAsync(new Dictionary<string, object>(AdminSelected(grid)), load); });
            relocate = Ui.Button("更改目录…", async delegate {
                Dictionary<string, object> row = AdminSelected(grid);
                
                using (FolderBrowserDialog picker = new FolderBrowserDialog { Description = "选择“" + Ui.Text(row, "name") + "”搬移后的服务器目录。配置会保留。请先停止这台服务器。", ShowNewFolderButton = false }) {
                    string previous = Ui.Text(row, "path");
                    if (Directory.Exists(previous)) picker.SelectedPath = previous;
                    if (picker.ShowDialog(this) != DialogResult.OK) return;
                    if (!PlatformFolderRecognized(picker.SelectedPath,PlatformUiProfile.Read(row))) throw new InvalidOperationException("请选择包含对应服务端配置或启动核心的目录。");
                    Dictionary<string, object> result = await Call("servers.relocate", Ui.Obj("id", Ui.Text(row, "id"), "path", picker.SelectedPath));
                    await RefreshServers();
                    await load();
                    SetStatus(Ui.Text(result, "message", "服务器目录已更新。"));
                }
            });
            install = Ui.Button("安装服务端\r\nJava / 基岩 / 代理", async delegate { await InstallServerWizardAsync(); await RefreshServers(); await load(); });
            archive = Ui.Button("导入 ZIP 压缩包\r\n也可直接拖入此页", async delegate {
                using (OpenFileDialog picker = new OpenFileDialog { Title = "选择服务器 ZIP 压缩包", Filter = "服务器 ZIP 压缩包 (*.zip)|*.zip", CheckFileExists = true }) {
                    if (picker.ShowDialog(this) != DialogResult.OK) return;
                    await ImportServerArchiveAsync(picker.FileName); await RefreshServers(); await load();
                }
            });
            foreach (Button entry in new Button[] { install, archive, add }) { entry.MinimumSize = new Size(190, 60); entry.TextAlign = ContentAlignment.MiddleLeft; Ui.Role(entry, "secondary"); }
            Ui.Role(choose, "primary"); Ui.Role(remove, "danger");
            FlowLayoutPanel selectedActions = Ui.Toolbar(choose, AdminMore(relocate, remove), Ui.Button("刷新状态", load)); selectedActions.Dock = DockStyle.Bottom;
            selection.Dock = DockStyle.Bottom; body.Controls.Add(selection); body.Controls.Add(selectedActions);
            grid.SelectionChanged += delegate { updateSelection(); }; search.TextChanged += delegate { render(); };
            foreach (Button command in new Button[] { choose, relocate, remove }) { Button target = command; target.EnabledChanged += delegate { if (target.Enabled) updateSelection(); }; }
            grid.CellDoubleClick += async delegate(object sender, DataGridViewCellEventArgs args) { if (args.RowIndex >= 0 && choose.Enabled) await Safe(async delegate { await EnterServerAsync(Ui.Text(AdminSelected(grid), "id")); }); };
            AttachServerSelectionMenu(grid, delegate { return workspaceError; }, load);
            updateSelection();
            Panel page = AdminContainer("服务器工作区", ("免费版：全安装共 1 台服务器。右键服务器可打开常用操作；其他记录和文件保留。"), body, install, archive, add);
            FlowLayoutPanel entryBar = install.Parent as FlowLayoutPanel;
            Action arrange = delegate {
                if (arranging || page.IsDisposed) return;
                arranging = true; page.SuspendLayout(); body.SuspendLayout();
                try {
                    compact = page.ClientSize.Height < 610 || page.ClientSize.Width < 900;
                    string[] labels = compact ? new string[] { "安装服务端", "导入 ZIP 压缩包", "绑定已有文件夹" } : new string[] { "安装服务端\r\nJava / 基岩 / 代理", "导入 ZIP 压缩包\r\n也可直接拖入此页", "绑定已有文件夹\r\n自动识别启动配置" };
                    int entryWidth = Math.Max(160, (page.ClientSize.Width - page.Padding.Horizontal - 24) / 3);
                    Button[] entries = new Button[] { install, archive, add };
                    for (int index = 0; index < entries.Length; ++index) {
                        Button entry = entries[index]; entry.Text = labels[index]; entry.AutoSize = !compact;
                        entry.MinimumSize = compact ? new Size(160, 36) : new Size(190, 60);
                        if (compact) entry.Size = new Size(entryWidth, 38);
                        details.SetToolTip(entry, new string[] { "从官方下载原版、NeoForge、Forge 或 Fabric 服务端。", "解压可信的服务器 ZIP 并自动绑定，也可直接拖入此页。", "绑定已存在的服务器文件夹，识别启动配置。" }[index]);
                    }
                    if (entryBar != null) { entryBar.WrapContents = !compact; entryBar.Padding = compact ? new Padding(0, 2, 0, 2) : new Padding(0, 6, 0, 6); }
                    installation.Padding = compact ? new Padding(8, 8, 8, 4) : new Padding(12, 10, 12, 8);
                    installStatus.Height = compact ? Math.Max(38, Math.Max(installation.Font.Height + installation.Padding.Vertical + 4, viewInstall.Font.Height + viewInstall.Padding.Vertical + 6)) : 68; viewInstall.Width = compact ? 154 : 176;
                    installation.Text = compact ? installHeadline : installHeadline + "\r\n" + installDetail;
                    searchBar.WrapContents = !compact; searchBar.Padding = compact ? new Padding(0) : new Padding(0, 6, 0, 6);
                    selectedActions.Padding = compact ? new Padding(0, 2, 0, 0) : new Padding(0, 6, 0, 6);
                    updateSelection();
                } finally { body.ResumeLayout(true); page.ResumeLayout(true); arranging = false; }
            };
            page.SizeChanged += delegate { arrange(); }; page.PaddingChanged += delegate { arrange(); };
            arrange(); return page;
        }
        private async Task InstallServerWizardAsync() {
            await ShowServerSetupWizardAsync(null);
        }
        private async Task ImportServerArchiveAsync(string archive) {
            if (!File.Exists(archive) || !String.Equals(Path.GetExtension(archive), ".zip", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("请选择现有的服务器 ZIP 压缩包。");
            await ShowServerSetupWizardAsync(Path.GetFullPath(archive));
        }
        private static string AdminDefaultServerDirectory(string serverName, string parentOverride = null) {
            string folder = (serverName ?? "").Trim();
            foreach (char invalid in Path.GetInvalidFileNameChars()) folder = folder.Replace(invalid, '_');
            folder = folder.TrimEnd(' ', '.');
            if (folder.Length == 0) folder = "服务器";
            if (folder.Length > 80) folder = folder.Substring(0, 80).TrimEnd(' ', '.');
            string stem = folder.Split('.')[0].ToUpperInvariant();
            if (stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL" || (stem.Length == 4 && (stem.StartsWith("COM") || stem.StartsWith("LPT")) && stem[3] >= '1' && stem[3] <= '9')) folder = "服务器-" + folder;
            string parent = parentOverride ?? Path.Combine(NativeProgram.BundleRoot, "mcSever");
            string candidate = Path.Combine(parent, folder);
            for (int index = 2; parentOverride == null && (Directory.Exists(candidate) || File.Exists(candidate)); ++index) candidate = Path.Combine(parent, folder + "-" + index.ToString(CultureInfo.InvariantCulture));
            return candidate;
        }
        private async Task<bool> EnsureServerEulaAsync() {
            string targetServer = selectedServerId;
            Dictionary<string, object> status = await Call("server.eula.get", null, targetServer);
            if (selectedServerId != targetServer) return false;
            if (status.ContainsKey("required")&&!Ui.Bool(status,"required")) return true;
            if (Ui.Bool(status, "accepted")) return true;
            using (Form dialog = new Form { Text = "开服前确认 Minecraft EULA", ClientSize = new Size(650, 360), StartPosition = FormStartPosition.CenterParent, FormBorderStyle = FormBorderStyle.FixedDialog, Font = Font, MinimizeBox = false, MaximizeBox = false }) {
                TableLayoutPanel fields = Ui.Fields();
                Label explanation = new Label { Text = "这台服务器尚未接受 Minecraft EULA。请阅读官方协议；只有你明确同意后，面板才会保存接受状态并继续开服。", AutoSize = true, MaximumSize = new Size(410, 0) };
                LinkLabel official = new LinkLabel { Text = "打开官方协议：https://www.minecraft.net/eula", AutoSize = true, MaximumSize = new Size(410, 0) };
                official.LinkClicked += delegate { try { Process.Start(new ProcessStartInfo("https://www.minecraft.net/eula") { UseShellExecute = true }); } catch (Exception error) { Ui.Message(dialog, error.Message, "打开协议失败", MessageBoxIcon.Warning); } };
                CheckBox agree = new CheckBox { Text = "我已阅读并同意 Minecraft EULA", Checked = false, AutoSize = true };
                Ui.Field(fields, "开服条件", explanation); Ui.Field(fields, "官方协议", official); Ui.Field(fields, "确认", agree);
                Button accept = Ui.Button("同意并继续开服", async delegate {
                    if (!agree.Checked) return;
                    await Call("server.eula.accept", Ui.Obj("accepted", true), targetServer);
                    dialog.DialogResult = DialogResult.OK; dialog.Close();
                });
                accept.Enabled = false;
                agree.CheckedChanged += delegate { accept.Enabled = agree.Checked; };
                Button cancel = Ui.Button("暂不开服", delegate { dialog.DialogResult = DialogResult.Cancel; dialog.Close(); return Task.FromResult(0); });
                dialog.Controls.Add(AdminContainer("Minecraft EULA", "此确认只对当前选择的服务器生效。", AdminScroll(fields), accept, cancel));
                dialog.CancelButton = cancel; Ui.ApplyTheme(dialog);
                return dialog.ShowDialog(this) == DialogResult.OK;
            }
        }
        private async Task ShowServerSetupWizardAsync(string archive) {
            bool fromArchive = !String.IsNullOrEmpty(archive);
            Dictionary<string, object> options = await Call("server.install.options", Ui.Obj("from_archive", fromArchive));
            
            ComboBox platform = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 350 };
            var installProfiles=new Dictionary<string,PlatformUiProfile>();foreach (Dictionary<string, object> item in Ui.List(options, "platforms")) {string key=Ui.Text(item,"id");installProfiles[key]=PlatformUiProfile.Read(item);platform.Items.Add(new AdminOption(key,Ui.Text(item,"label",Ui.Text(item,"name"))));}
            if (platform.Items.Count == 0) {
                platform.Items.Add(new AdminOption("vanilla", "原版 Vanilla")); platform.Items.Add(new AdminOption("neoforge", "NeoForge"));
                platform.Items.Add(new AdminOption("forge", "Forge")); platform.Items.Add(new AdminOption("fabric", "Fabric"));
            }
            platform.SelectedIndex = 0; AdminChoose(platform, "neoforge");
            Func<PlatformUiProfile> selectedProfile=delegate{PlatformUiProfile found;return installProfiles.TryGetValue(AdminKey(platform),out found)?found:PlatformUiProfile.Read(Ui.Obj("platform",AdminKey(platform)));};
            ComboBox version = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 350 };
            ComboBox loaderVersion = new ComboBox { Name="InstallLoaderVersion", DropDownStyle=ComboBoxStyle.DropDownList, Width=350 };
            Label catalogNote = new Label {Text="正在读取官方版本列表…",AutoSize=true,MaximumSize=new Size(470,0)};
            Label javaNote = new Label {AutoSize=true,MaximumSize=new Size(470,0)};
            platform.Name="InstallPlatform";version.Name="InstallMinecraft";
            ComboBox java = new ComboBox { Name="InstallJava", DropDownStyle = ComboBoxStyle.DropDown, Width = 430 };
            object choices;
            if (options.TryGetValue("minecraft_versions", out choices) && choices is IEnumerable) foreach (object choice in (IEnumerable)choices) version.Items.Add(Convert.ToString(choice));
            if (version.Items.Count > 0) version.SelectedIndex = 0;
            java.Items.Add(""); // Empty explicitly means automatic selection for the detected/selected MC version.
            if (options.TryGetValue("java_candidates", out choices) && choices is IEnumerable) foreach (object choice in (IEnumerable)choices) java.Items.Add(Convert.ToString(choice));
            if (java.Items.Count > 0) java.SelectedIndex = 0;
            TextBox name = AdminText(fromArchive ? Path.GetFileNameWithoutExtension(archive) : "新服务器", false), path = AdminText("", false);
            name.Name="InstallServerName";path.Name="InstallDirectory";
            name.MaxLength = 40; path.Width = 430;
            if (name.Text.Length > 40) name.Text = name.Text.Substring(0, 40);
            bool customPath = false, updatingDefaultPath = false;
            Action refreshDefaultPath = delegate {
                if (customPath) return;
                updatingDefaultPath = true;
                try { path.Text = AdminDefaultServerDirectory(name.Text); }
                finally { updatingDefaultPath = false; }
            };
            path.TextChanged += delegate { if (!updatingDefaultPath) customPath = true; };
            name.TextChanged += delegate { refreshDefaultPath(); };
            refreshDefaultPath();
            Button folder = Ui.Button("选择空文件夹…", delegate {
                
                using (FolderBrowserDialog picker = new FolderBrowserDialog { Description = "选择一个新的空文件夹保存服务端文件，可点击新建文件夹。", ShowNewFolderButton = true }) {
                    if (Directory.Exists(path.Text)) picker.SelectedPath = path.Text;
                    if (picker.ShowDialog(this) == DialogResult.OK) { path.Text = picker.SelectedPath; if (name.Text == "新服务器") name.Text = new DirectoryInfo(path.Text).Name; }
                }
            return Task.FromResult(0);
            });
            Button javaBrowse = Ui.Button("选择 Java…", delegate {
                using (OpenFileDialog picker = new OpenFileDialog { Title = "选择与该服务端版本匹配的 java.exe", Filter = "Java 程序 (java.exe)|java.exe|可执行文件 (*.exe)|*.exe", CheckFileExists = true }) if (picker.ShowDialog(this) == DialogResult.OK) java.Text = picker.FileName;
                return Task.FromResult(0);
            });
            
            CheckBox eula = new CheckBox { Text = "我已阅读并同意 Minecraft EULA", AutoSize = true, Checked = false };
            CheckBox adaptStartup = new CheckBox { Name = "ArchiveAdaptStartup", Text = "生成七章面板专用启动文件（推荐）", AutoSize = true, Checked = true, MaximumSize = new Size(470, 0) };
            LinkLabel agreement = new LinkLabel { Text = "查看 Minecraft EULA（打开官方网页）", AutoSize = true };
            agreement.LinkClicked += delegate { try { Process.Start(new ProcessStartInfo("https://www.minecraft.net/eula") { UseShellExecute = true }); } catch (Exception error) { Ui.Message(Form.ActiveForm, error.Message, "打开协议失败", MessageBoxIcon.Warning); } };
            TableLayoutPanel fields = Ui.Fields();
            AdminSection(fields, "1 · 选择服务端", fromArchive ? "从已有服务器 ZIP 导入，自动识别加载器和启动配置。" : "选择基础服务端平台及 Minecraft 版本。");
            var corePanel=new TableLayoutPanel {Name="ArchiveCorePanel",ColumnCount=1,AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,Dock=DockStyle.Top,Visible=false,Padding=new Padding(10),Margin=new Padding(0,4,0,10)};
            var coreHeading=new Label {Text="检测到多个可用启动目标，请明确选择",AutoSize=true,Dock=DockStyle.Top,Font=Ui.HeaderFont,MaximumSize=new Size(630,0)};Ui.Role(coreHeading,"warning");
            var coreChoice=new ComboBox {Name="ArchiveCoreChoice",DropDownStyle=ComboBoxStyle.DropDownList,Dock=DockStyle.Top,DropDownWidth=760,Margin=new Padding(0,8,0,8)};
            var coreDetail=new TextBox {Name="ArchiveCoreDetails",Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,WordWrap=true,Height=128,Dock=DockStyle.Top};
            var coreHint=new Label {Name="ArchiveCoreHint",Text="不会自动选中第一个核心。选定后点击“重新导入选中核心”，将从原 ZIP 重新解压，可能需要等待；原 ZIP 和已有服务器文件不会删除。",AutoSize=true,Dock=DockStyle.Top,MaximumSize=new Size(630,0),Margin=new Padding(0,8,0,2)};
            corePanel.Controls.Add(coreHeading);corePanel.Controls.Add(coreChoice);corePanel.Controls.Add(coreDetail);corePanel.Controls.Add(coreHint);
            int coreRow=fields.RowCount++;fields.RowStyles.Add(new RowStyle(SizeType.AutoSize));fields.Controls.Add(corePanel,0,coreRow);fields.SetColumnSpan(corePanel,2);
            Ui.Field(fields, "服务器名称", name);
            if (fromArchive) {
                Ui.Field(fields, "服务器压缩包", new TextBox { Text = archive, ReadOnly = true, Width = 430 });
                Ui.Field(fields, "启动适配", adaptStartup);
                Ui.Field(fields, "适配说明", new Label { Name = "ArchiveAdaptStartupHint", Text = "识别 Java、原生程序或 PHP 启动核心及参数，生成独立入口并绑定；原文件保留。关闭后沿用原启动文件，需自行核对运行环境。", AutoSize = true, MaximumSize = new Size(470, 0) });
            }
            else { Ui.Field(fields, "服务端类型", platform); Ui.Field(fields, "游戏 / 核心版本", version); Ui.Field(fields,"构建 / 加载器版本",loaderVersion);Ui.Field(fields,"版本来源",catalogNote); }
            AdminSection(fields, "2 · 保存位置与运行环境", "为新服务器使用独立空目录，避免覆盖原有文件。");
            Ui.Field(fields, "安装目录", path); Ui.Field(fields, "", folder);
            Ui.Field(fields, "目录提示", new Label { Text = "默认在程序目录的 mcSever 内为每台服务器创建独立文件夹；可改为其他空目录。", AutoSize = true, MaximumSize = new Size(470, 0) });
            Ui.Field(fields, fromArchive ? "备用 Java 路径" : "Java 路径", java); Ui.Field(fields, "", javaBrowse);
            javaNote.Text=fromArchive?"导入时按启动核心识别运行环境。Java 核心优先使用包内兼容的 64 位 Java，缺失时查找本机；PHP 与原生核心不使用此 Java 选项。无法确定版本时需要手动确认，不会强行选用 Java 21。"+("可指定本机 java.exe 作为备用选择。") : "Java 核心留空时按核心与版本要求匹配已安装环境；无法识别时需要手动确认。原生 / PHP 核心不使用 Java。";
            Ui.Field(fields, "运行环境提示", javaNote);
            var officialLink=new LinkLabel {Name="InstallOfficialLink",Text="打开此平台官方安装说明",AutoSize=true,Visible=false};officialLink.LinkClicked+=delegate{var url=selectedProfile().OfficialUrl;Uri uri;if(Uri.TryCreate(url,UriKind.Absolute,out uri)&&(uri.Scheme=="https"||uri.Scheme=="http"))Process.Start(new ProcessStartInfo(url){UseShellExecute=true});};if(!fromArchive)Ui.Field(fields,"官方说明",officialLink);
            AdminSection(fields, "3 · 协议与安装", "安装完成后返回工作区，手动选择服务器并开服。");
            if (!fromArchive) { Ui.Field(fields, "使用协议", eula); Ui.Field(fields, "", agreement); }
            Ui.Field(fields, "协议提示", new Label { Text = fromArchive ? "导入不会自动开服，也不会代替你接受 Minecraft EULA。首次开服前请确认协议状态。" : "未同意时仍可下载，首次开服前需要先接受协议。安装后不会自动开服。", AutoSize = true, MaximumSize = new Size(470, 0) });
            Label progressText = new Label { Name="InstallProgressMessage", Text = fromArchive ? "准备就绪。将解压服务器文件并自动识别服务端类型和启动方式。" : "准备就绪。首次安装需要联网下载官方文件。", AutoSize = true, MaximumSize = new Size(470, 0) };
            ProgressBar progress = new ProgressBar { Minimum = 0, Maximum = 100, Width = 430, Height = 22 };
            Ui.Field(fields, "安装进度", progress); Ui.Field(fields, "状态", progressText);
            using (Form dialog = new Form { Text = fromArchive ? "导入服务器压缩包" : "安装 Minecraft 服务器", Width = 850, Height = 790, MinimumSize = new Size(700, 620), StartPosition = FormStartPosition.CenterParent, Font = Font, MinimizeBox = false, MaximizeBox = false })
            using (Timer timer = new Timer { Interval = 1000 }) {
                bool active = false, polling = false, catalogBusy=false, catalogReady=fromArchive, fillingCatalog=false, awaitingSelection=false;
                string previewToken="",previewChoice="";
                bool renderingPreview=false;
                var coreChoices=new Dictionary<string,Dictionary<string,object>>(StringComparer.Ordinal);
                Func<Dictionary<string,object>,string,string> coreValue=delegate(Dictionary<string,object> row,string key){string value=Ui.Text(row,key);return value.Length>0?value:"未识别";};
                Button start = null;
                Button close = Ui.Button("关闭", delegate { dialog.Close(); return Task.FromResult(0); });
                Action<bool> setActive = delegate(bool value) {
                    active = value;
                    foreach (Control input in new Control[] { name, path, platform, version, loaderVersion, java, folder, javaBrowse, eula, adaptStartup, start, close }) input.Enabled = !value;
                    platform.Enabled=version.Enabled=!value&&!catalogBusy;
                    var profile=selectedProfile();bool builtin=profile.InstallMethod=="builtin",usesJava=fromArchive||profile.Runtime=="java";
                    loaderVersion.Enabled=!value&&!catalogBusy&&builtin&&loaderVersion.Items.Count>0;
                    version.Enabled=!value&&!catalogBusy&&builtin;
                    java.Enabled=!value&&usesJava;javaBrowse.Enabled=!value&&usesJava;
                    PlatformFieldVisible(fields,java,usesJava);PlatformFieldVisible(fields,javaBrowse,usesJava);
                    if(!fromArchive){officialLink.Visible=profile.OfficialUrl.Length>0;eula.Enabled=!value&&profile.Family!="proxy"&&profile.Family!="custom";PlatformFieldVisible(fields,eula,profile.Family!="proxy"&&profile.Family!="custom");PlatformFieldVisible(fields,agreement,profile.Family!="proxy"&&profile.Family!="custom");}
                    coreChoice.Enabled=!value&&awaitingSelection;
                    start.Enabled=!value&&catalogReady&&!catalogBusy&&(!awaitingSelection||coreChoices.ContainsKey(AdminKey(coreChoice)));
                    start.Text=fromArchive?(previewToken.Length>0?"确认预览并导入":awaitingSelection?"预览选中核心":"识别并预览"):"下载并安装";
                };
                Action invalidatePreview=delegate{if(!fromArchive||renderingPreview||active)return;previewToken="";if(corePanel.Visible)coreHeading.Text="配置已变化，请重新识别后确认导入。";if(start!=null)setActive(false);};
                java.TextChanged+=delegate{invalidatePreview();};path.TextChanged+=delegate{invalidatePreview();};adaptStartup.CheckedChanged+=delegate{invalidatePreview();};
                coreChoice.SelectedIndexChanged+=delegate{
                    if(renderingPreview)return;
                    invalidatePreview();
                    Dictionary<string,object> row;
                    coreDetail.Text=coreChoices.TryGetValue(AdminKey(coreChoice),out row)?"服务器目录："+coreValue(row,"server_path")+"\r\n服务端类型："+coreValue(row,"platform")+" · "+coreValue(row,"kind")+"\r\nMinecraft："+coreValue(row,"minecraft_version")+"\r\n加载器版本："+coreValue(row,"loader_version")+"\r\n启动入口："+coreValue(row,"entry")+(Ui.Text(row,"startup_script").Length>0?"\r\n原启动文件："+Ui.Text(row,"startup_script"):"")+"\r\n识别依据："+coreValue(row,"reason"):"请选择要导入的具体服务器目录和启动核心。未识别的版本信息不会作为确定结果。";
                    if(start!=null)setActive(active);
                };
                Func<Task> pollCatalog=async delegate {
                    if(!catalogBusy)return;
                    var state=await Call("server.install.catalog.status");if(dialog.IsDisposed)return;
                    if(Ui.Bool(state,"active"))return;
                    catalogBusy=false;var data=AdminPart(state,"result");string error=Ui.Text(state,"error");
                    if(data.ContainsKey("platform_profile")||data.ContainsKey("profile"))installProfiles[AdminKey(platform)]=PlatformUiProfile.Read(data);
                    catalogReady=error.Length==0&&selectedProfile().InstallMethod=="builtin"&&Ui.Text(data,"minecraft_version").Length>0;
                    if(!catalogReady){catalogNote.Text="官方版本读取失败："+(error.Length>0?error:"未返回可安装版本")+"。请点击重新读取。";setActive(active);return;}
                    fillingCatalog=true;
                    try {
                        version.Items.Clear();object rows;if(data.TryGetValue("minecraft_versions",out rows)&&rows is IEnumerable)foreach(object row in (IEnumerable)rows)version.Items.Add(Convert.ToString(row));
                        version.SelectedItem=Ui.Text(data,"minecraft_version");
                        loaderVersion.Items.Clear();foreach(var row in Ui.List(data,"loader_versions"))loaderVersion.Items.Add(new AdminOption(Ui.Text(row,"version"),Ui.Text(row,"version")+(Ui.Bool(row,"recommended")?"（推荐）":"")+(!Ui.Bool(row,"stable")?"（未标记稳定）":"")));
                        if(loaderVersion.Items.Count>0){loaderVersion.SelectedIndex=0;AdminChoose(loaderVersion,Ui.Text(data,"default_loader_version"));}
                        catalogNote.Text="版本与加载器来自官方列表，安装前会再次核对组合。"+Ui.Text(data,"support_scope");
                        var requirement=AdminPart(data,"java_requirement");var runtimeRequirement=AdminPart(data,"runtime_requirement");string major=Ui.Text(requirement,"major");var selectedPlatform=selectedProfile();javaNote.Text=selectedPlatform.Runtime=="java"?(major.Length>0?"所选核心要求 64 位 Java "+major+"。留空时匹配已安装环境；指定路径仍会检查版本。":"此核心的 Java 要求尚未确定；请按官方说明选择，面板不会默认套用 Java 21。"):Ui.Text(runtimeRequirement,"label",selectedPlatform.Runtime=="php"?"需要与 PocketMine 版本匹配的专用 PHP 和扩展；不使用 Java。":"使用平台自带的原生程序，不需要 Java。");
                    } finally {fillingCatalog=false;}
                    setActive(active);
                };
                Func<bool,Task> requestCatalog=async delegate(bool keepVersion){
                    if(fromArchive||fillingCatalog||catalogBusy||active)return;
                    var profile=selectedProfile();if(profile.InstallMethod!="builtin"){catalogReady=false;version.Items.Clear();loaderVersion.Items.Clear();catalogNote.Text="此平台通过官方文件导入，当前不提供自动下载。请打开官方说明准备服务端，然后在服务器选择页导入 ZIP 或绑定已有目录。";javaNote.Text=profile.Runtime=="php"?"需要对应 PocketMine 版本的专用 PHP、扩展及 VC++ 运行库。":profile.Runtime=="java"?"Java 要求取决于核心版本，请按官方说明准备。":"按官方说明准备完整服务端文件。";setActive(false);return;}
                    catalogReady=false;catalogBusy=true;setActive(false);catalogNote.Text="正在读取所选平台的官方版本列表…";
                    try {await Call("server.install.catalog.start",Ui.Obj("platform",AdminKey(platform),"minecraft_version",keepVersion?Convert.ToString(version.SelectedItem):""));timer.Start();await pollCatalog();}
                    catch(Exception error){catalogBusy=false;catalogNote.Text="官方版本读取失败："+error.Message;setActive(false);}
                };
                Button retryCatalog=Ui.Button("重新读取版本",async delegate{await requestCatalog(false);});
                retryCatalog.Visible=!fromArchive;Ui.Field(fields,"",retryCatalog);
                platform.SelectedIndexChanged+=async delegate{await requestCatalog(false);};
                version.SelectedIndexChanged+=async delegate{await requestCatalog(true);};
                Func<Task> pollInstall = async delegate {
                    if (polling || dialog.IsDisposed) return;
                    polling = true;
                    try {
                        Dictionary<string, object> result = await Call("server.install.status");
                        if (dialog.IsDisposed) return;
                        progress.Value = (int)Math.Max(0, Math.Min(100, Ui.Num(result, "progress")));
                        bool needsSelection=fromArchive&&Ui.Text(result,"phase")=="awaiting_selection";
                        progressText.Text = (needsSelection?"等待选择启动目标":AdminInstallPhase(result)) + " · " + progress.Value + "%\r\n" + Ui.Text(result, "message", "正在安装…");
                        string error = Ui.Text(result, "error");
                        if (error.Length > 0) progressText.Text += "\r\n" + error;
                        if (!Ui.Bool(result, "active")) {
                            if(!catalogBusy)timer.Stop();
                            if(fromArchive&&Ui.Text(result,"phase")=="previewed") {
                                var preview=AdminPart(result,"preview");renderingPreview=true;
                                try {
                                    awaitingSelection=Ui.Bool(preview,"selection_required");previewToken=Ui.Bool(preview,"can_install")?Ui.Text(preview,"preview_token"):"";
                                    coreChoices.Clear();coreChoice.Items.Clear();coreChoice.Items.Add(new AdminOption("","请选择启动目标（尚未选择）"));
                                    foreach(var row in Ui.List(preview,"candidates")){string candidateId=Ui.Text(row,"id");if(candidateId.Length==0||coreChoices.ContainsKey(candidateId))continue;coreChoices[candidateId]=row;coreChoice.Items.Add(new AdminOption(candidateId,coreValue(row,"server_path")+" · "+coreValue(row,"platform")+" · "+coreValue(row,"entry")));}
                                    coreChoice.SelectedIndex=0;coreChoice.Visible=awaitingSelection;
                                    corePanel.Visible=true;coreHeading.Text=previewToken.Length>0?"识别完成，请检查后点击“确认预览并导入”":"需要补充信息，请检查识别结果";
                                    coreDetail.Text=ArchivePreviewText(preview);coreDetail.Height=210;
                                    coreHint.Text="原启动文件保留。预览与安装共用解压结果；确认时再次核对文件指纹。修改目录、Java 或适配选项后需要重新识别。";
                                    progressText.Text=Ui.Text(preview,"summary","请检查识别预览。")+"\r\n"+String.Join("；",OpsValues(OpsValue(preview,"uncertainties")).Select(value=>Convert.ToString(value)));
                                    Ui.Role(progressText,previewToken.Length>0?"muted":"warning");setActive(false);
                                }finally {renderingPreview=false;}
                                corePanel.PerformLayout();var previewScroll=fields.Parent as ScrollableControl;if(previewScroll!=null)previewScroll.ScrollControlIntoView(corePanel);
                                polling=false;
                                return;
                            }
                            awaitingSelection=needsSelection;
                            if(needsSelection){
                                coreChoice.Visible=true;
                                coreChoices.Clear();coreChoice.Items.Clear();coreChoice.Items.Add(new AdminOption("","请选择启动目标（尚未选择）"));
                                foreach(var row in Ui.List(result,"choices")){string id=Ui.Text(row,"id");if(id.Length==0||coreChoices.ContainsKey(id))continue;coreChoices.Add(id,row);string original=Ui.Text(row,"startup_script");coreChoice.Items.Add(new AdminOption(id,(original.Length>0?original+" · ":"")+coreValue(row,"server_path")+" · "+coreValue(row,"platform")+" · MC "+coreValue(row,"minecraft_version")+" · "+coreValue(row,"entry")));}
                                coreChoice.SelectedIndex=0;corePanel.Visible=true;coreHeading.Text=coreChoices.Count>1?"检测到多个可用启动目标，请明确选择":coreChoices.Count==1?"启动目标已重新识别，请明确确认":"没有有效的启动目标，请关闭后重新选择服务器 ZIP";
                                Ui.Role(progressText,"warning");setActive(false);corePanel.PerformLayout();var scroll=fields.Parent as ScrollableControl;if(scroll!=null)scroll.ScrollControlIntoView(corePanel);coreChoice.Focus();
                            }else{corePanel.Visible=false;coreChoices.Clear();setActive(false);Ui.Role(progressText,error.Length>0?"danger":"muted");}
                            if (Ui.Text(result, "server_id").Length > 0 && error.Length == 0) { progress.Value = 100; start.Enabled = false; progressText.Text = Ui.Text(result, "message", "安装完成。") + "\r\n关闭此窗口后，选择服务器进入管理。"; }
                        }
                    } catch (Exception error) {
                        if (!dialog.IsDisposed) {
                             progressText.Text = "暂时无法读取进度：" + error.Message + "\r\n正在重新查询，请稍候。";
                        }
                    }
                    polling = false;
                };
                start = new Button { Name="InstallStart", Text = fromArchive ? "解压并导入" : "下载并安装", AutoSize = true, Padding = new Padding(12, 4, 12, 4), MinimumSize = new Size(116, 36), Margin = new Padding(0, 0, 8, 6) };
                start.Click += async delegate {
                    start.Enabled = false;
                    try {
                        string selectedCore=previewToken.Length>0?previewChoice:awaitingSelection?AdminKey(coreChoice):"";
                        if(awaitingSelection&&!coreChoices.ContainsKey(selectedCore))throw new InvalidOperationException("请先明确选择一个启动目标；面板不会自动选择第一个核心。");
                        if (String.IsNullOrWhiteSpace(name.Text) || String.IsNullOrWhiteSpace(path.Text)) throw new InvalidOperationException("请填写服务器名称并选择安装目录。");
                        if(!fromArchive&&(!catalogReady||catalogBusy))throw new InvalidOperationException("请先等待官方版本列表读取完成。");
                        if (!Path.IsPathRooted(path.Text.Trim())) throw new InvalidOperationException("安装目录请填写完整路径，或使用选择文件夹按钮。");
                        string destination = Path.GetFullPath(path.Text.Trim());
                        if (true && File.Exists(destination)) throw new InvalidOperationException("安装位置必须是文件夹。");
                        if (true && Directory.Exists(destination) && Directory.GetFileSystemEntries(destination).Length != 0) throw new InvalidOperationException("请选择新的空文件夹，避免覆盖已有服务器。");
                        setActive(true); progressText.Text = "正在提交安装任务…";
                        if (fromArchive) {
                            var archivePayload=Ui.Obj("path",destination,"java_path",java.Text.Trim(),"name",name.Text.Trim(),"adapt_startup",adaptStartup.Checked);
                            if(selectedCore.Length>0)archivePayload["selected_core"]=selectedCore;
                            bool confirming=previewToken.Length>0;
                            if(confirming)archivePayload["preview_token"]=previewToken;else previewChoice=selectedCore;
                            string archiveAction=confirming?"server.archive.start":"server.archive.preview";
                            {archivePayload["archive"]=archive;await Call(archiveAction,archivePayload);}
                            if(confirming)previewToken="";
                        }
                        else {var payload=Ui.Obj("platform",AdminKey(platform),"minecraft_version",Convert.ToString(version.SelectedItem),"loader_version",AdminKey(loaderVersion),"path",destination,"name",name.Text.Trim(),"eula_accepted",eula.Checked);if(selectedProfile().Runtime=="java")payload["java_path"]=java.Text.Trim();await Call("server.install.start",payload);}
                        timer.Start(); await pollInstall();
                    } catch (Exception error) { setActive(false); Ui.Message(dialog, error.Message, "安装未完成", MessageBoxIcon.Warning); }
                };
                bool catalogPolling=false;
                timer.Tick += async delegate {if(catalogPolling)return;catalogPolling=true;try{if(catalogBusy)await pollCatalog();if(active)await pollInstall();if(!catalogBusy&&!active)timer.Stop();}catch(Exception error){catalogNote.Text=error.Message;}finally{catalogPolling=false;} };
                dialog.Shown+=async delegate{try{var existing=await Call("server.install.status");if(Ui.Bool(existing,"active")){setActive(true);timer.Start();await pollInstall();}else if(!fromArchive)await requestCatalog(false);}catch(Exception error){progressText.Text=error.Message;if(rpc.HasExited)start.Enabled=false;}};
                dialog.FormClosing += delegate(object sender, FormClosingEventArgs args) { if (active) { args.Cancel = true; progressText.Text = "安装正在执行，请等待完成后关闭。"; } };
                dialog.Controls.Add(AdminContainer(fromArchive ? "导入服务器压缩包" : "安装服务器", fromArchive ? "将已有服务器 ZIP 解压到新的空目录，自动识别并加入当前账号。请选择可信的服务端压缩包。" : "按所选平台安装基础服务端；需要自行准备文件的平台会显示官方说明与导入方式。不会自动安装整合包内容。", AdminScroll(fields), start, close));
                setActive(false);Ui.ApplyTheme(dialog); dialog.ShowDialog(this); timer.Stop();
                if(fromArchive&&!active){try{await Call("server.archive.preview.clear");}catch{}}
            }
        }
        private async Task AdminAddServer() {
            TableLayoutPanel fields = Ui.Fields();
            TextBox name = AdminText("", false), id = AdminText("", false), path = AdminText("", false);
            name.MaxLength = 40; id.MaxLength = 32;
            TextBox launch = AdminText("", false), control = AdminText("", false), mc = AdminText("", false), loader = AdminText("", false), content = AdminText("", false);
            mc.MaxLength = 80; loader.MaxLength = 80; content.MaxLength = 80;
            var platformOptions=await Call("server.install.options",Ui.Obj("from_archive",true));ComboBox platform=new ComboBox {DropDownStyle=ComboBoxStyle.DropDownList,Width=350,Name="BindPlatform"};foreach(var choice in Ui.List(platformOptions,"platforms"))platform.Items.Add(new AdminOption(Ui.Text(choice,"id"),Ui.Text(choice,"label",Ui.Text(choice,"name"))));if(platform.Items.Count==0)throw new InvalidOperationException("后台未提供服务端平台列表，请重新连接后重试。");platform.SelectedIndex=0;
            AdminChoose(platform, "neoforge");
            NumericUpDown voice = AdminNumber(1, 65535, 24454);
            Label detected = new Label { Text = "选择已有服务器目录；可识别配置、JAR、EXE、PHAR 或启动文件。", AutoSize = true, MaximumSize = new Size(410, 0) };
            Button browse = Ui.Button("选择目录…", delegate {
                
                using (FolderBrowserDialog picker = new FolderBrowserDialog { Description = "选择 Minecraft 服务器文件夹", ShowNewFolderButton = false }) {
                    if (picker.ShowDialog(this) == DialogResult.OK) {
                        path.Text = picker.SelectedPath;
                        if (name.Text.Trim().Length == 0) name.Text = new DirectoryInfo(picker.SelectedPath).Name;
                        foreach (string candidate in new string[] { "qizhang-server-run-once.bat", "start-server.bat", "run.bat", "start.bat", "start.cmd", "start.ps1" }) if (File.Exists(Path.Combine(path.Text, candidate))) { launch.Text = candidate; break; }
                        control.Text = File.Exists(Path.Combine(path.Text, "qizhang-server-control.ps1")) ? "qizhang-server-control.ps1" : "";
                        detected.Text = "目录可用；导入时将检测启动方式。";
                    }
                }
                return Task.FromResult(0);
            });
            AdminSection(fields, "基本信息", "先选择服务器文件夹，再检查识别到的启动方式。");
            Ui.Field(fields, "服务器名称", name); Ui.Field(fields, "标识（留空自动生成）", id); Ui.Field(fields, "服务器目录", path); Ui.Field(fields, "", browse);
            AdminSection(fields, "平台与版本", "这些信息用于面板展示，请与已有服务端保持一致。");
            Ui.Field(fields, "平台", platform); Ui.Field(fields, "游戏 / 核心版本（可留空）", mc); Ui.Field(fields, "加载器版本（可留空）", loader); Ui.Field(fields, "整合包 / 模组版本", content);
            AdminSection(fields, "启动方式", "启动脚本可留空自动检测。");
            Ui.Field(fields, "启动脚本文件名", launch); Ui.Field(fields, "控制脚本（可留空）", control); Ui.Field(fields, "语音端口", voice); Ui.Field(fields, "目录检查", detected);
            using (Form dialog = AdminDialog("添加服务器", fields, async delegate {
                if (String.IsNullOrWhiteSpace(name.Text) || String.IsNullOrWhiteSpace(path.Text) || (true && !Directory.Exists(path.Text))) throw new InvalidOperationException("请填写名称并选择存在的服务器目录。");
                Dictionary<string, object> payload = Ui.Obj("name", name.Text.Trim(), "id", id.Text.Trim(), "path", path.Text.Trim(), "platform", AdminKey(platform), "minecraft_version", mc.Text.Trim(), "loader_version", loader.Text.Trim(), "content_version", content.Text.Trim(), "launch_script", launch.Text.Trim(), "voice_port", (int)voice.Value);
                if (control.Text.Trim().Length > 0) payload["control_script"] = control.Text.Trim();
                await Call("servers.add", payload);
            })) dialog.ShowDialog(this);
        }

        private Control AdminSettings(bool panelOnly) {
            string targetServer = selectedServerId;
            var settingsProfile=CurrentPlatform;bool javaGame=settingsProfile.Family=="java",javaRuntime=settingsProfile.Runtime=="java";
            TabControl tabs = new TabControl { Dock = DockStyle.Fill };
            TableLayoutPanel propertiesForm = Ui.Fields(), runtimeForm = Ui.Fields();
            // Populate the four settings tables as a batch. AutoSize otherwise
            // remeasures every earlier row after each added label and input.
            tabs.SuspendLayout();propertiesForm.SuspendLayout();runtimeForm.SuspendLayout();
            Dictionary<string, Control> properties = new Dictionary<string, Control>();
            
            Dictionary<string, string> names = new Dictionary<string, string> { {"motd", "服务器介绍"}, {"server-port", "游戏端口"}, {"server-ip", "本机绑定 IP"}, {"gamemode", "默认游戏模式"}, {"difficulty", "难度"}, {"max-players", "最大玩家数"}, {"view-distance", "视距（区块）"}, {"simulation-distance", "模拟距离（区块）"}, {"spawn-protection", "出生点保护半径"}, {"online-mode", "正版验证"}, {"white-list", "启用白名单"}, {"enforce-whitelist", "强制白名单"}, {"pvp", "允许玩家互相伤害"}, {"allow-flight", "允许飞行"}, {"enable-command-block", "启用命令方块"}, {"op-permission-level", "管理员权限等级"} };
            properties["motd"] = AdminText("", false);
            ((TextBox)properties["motd"]).MaxLength = 200;
            properties["server-port"] = AdminNumber(1, 65535, settingsProfile.Protocol.Equals("udp",StringComparison.OrdinalIgnoreCase)?19132:25565); properties["server-port"].Enabled = false;
            properties["server-port"].Name = "ServerEndpointPort";
            properties["server-ip"] = AdminText("", false); properties["server-ip"].Name = "ServerEndpointIp"; properties["server-ip"].Enabled = false;
            Label endpointNote = new Label {Name="ServerEndpointHint", Text="正在确认服务器是否已完全停止…", AutoSize=true, MaximumSize=new Size(470,0)};
            properties["gamemode"] = AdminCombo("survival", "生存", "creative", "创造", "adventure", "冒险", "spectator", "旁观");
            properties["difficulty"] = AdminCombo("peaceful", "和平", "easy", "简单", "normal", "普通", "hard", "困难");
            properties["max-players"] = AdminNumber(1, 200, 20); properties["view-distance"] = AdminNumber(2, 32, 8); properties["simulation-distance"] = AdminNumber(2, 32, 6); properties["spawn-protection"] = AdminNumber(0, 64, 16); properties["op-permission-level"] = AdminNumber(1, 4, 4);
            foreach (string key in new string[] { "online-mode", "white-list", "enforce-whitelist", "pvp", "allow-flight", "enable-command-block" }) properties[key] = new CheckBox { AutoSize = true, Text = "启用" };
            AdminSection(propertiesForm, "服务器信息", "保存后在下一次开服时应用游戏属性。");
            var missingNote = new Label { Name="ServerUnsetPropertiesHint", Text="标注“未设置”的项使用服务端核心默认值；空白或方框中的横线不表示 0 或关闭。只保存你实际编辑的项，其他原始设置保持不变。", AutoSize=true, MaximumSize=new Size(470,0) };
            Ui.Role(missingNote,"warning"); Ui.Field(propertiesForm,"未设置的属性",missingNote);
            foreach (string key in new string[] { "motd", "server-port", "server-ip", "max-players" }) Ui.Field(propertiesForm, names[key], properties[key]);
            Ui.Field(propertiesForm, "地址与端口", endpointNote);
            AdminSection(propertiesForm, "游戏体验与性能", "视距和模拟距离越大，服务器占用通常越高。");
            foreach (string key in new string[] { "gamemode", "difficulty", "view-distance", "simulation-distance", "spawn-protection", "pvp", "allow-flight" }) Ui.Field(propertiesForm, names[key], properties[key]);
            AdminSection(propertiesForm, "访问与权限", "控制谁可以加入服务器及管理员能力。");
            foreach (string key in new string[] { "online-mode", "white-list", "enforce-whitelist", "enable-command-block", "op-permission-level" }) Ui.Field(propertiesForm, names[key], properties[key]);
            TextBox xms = AdminText("", false), xmx = AdminText("", false);
            xms.Name = "ServerMemoryMinimum"; xmx.Name = "ServerMemoryMaximum";
            string originalXms = "", originalXmx = "";
            NumericUpDown sleepers = AdminNumber(0, 100, 30);
            CheckBox keepInventory = new CheckBox { Text = "死亡不掉落", AutoSize = true };
            var ruleControls = new Dictionary<string,Control> {{"keepInventory",keepInventory},{"playersSleepingPercentage",sleepers}};
            AdminSection(runtimeForm, "Java 内存", "填写 512M、4G 等整数大小；留空表示未设置，由 Java 自动分配。修改在下次开服生效。");
            Ui.Field(runtimeForm, "最小内存（留空自动）", xms); Ui.Field(runtimeForm, "最大内存（留空自动）", xmx);
            Ui.Field(runtimeForm, "保存规则", new Label {Text="只修改你编辑过的内存项；修改地址、端口等设置会保留原启动参数。清空某项可恢复 Java 自动分配。", AutoSize=true, MaximumSize=new Size(470,0)});
            AdminSection(runtimeForm, "游戏规则", "保存时按服务器可用能力应用。");
            Ui.Field(runtimeForm, "物品保留", keepInventory); Ui.Field(runtimeForm, "跳过夜晚所需睡眠比例（%）", sleepers);
            if(!javaGame){
                var keep=new HashSet<Control>(properties.Values);foreach(Control child in new List<Control>(System.Linq.Enumerable.Cast<Control>(propertiesForm.Controls)))if(!keep.Contains(child)&&child!=endpointNote)child.Dispose();
                propertiesForm.Controls.Clear();propertiesForm.RowStyles.Clear();propertiesForm.RowCount=0;
                AdminSection(propertiesForm,"平台配置",settingsProfile.Label+" · "+settingsProfile.RuntimeLabel+" 运行环境");
                Ui.Field(propertiesForm,"配置文件",new Label {Name="PlatformConfigFile",Text=settingsProfile.ConfigFile.Length>0?settingsProfile.ConfigFile:"由导入的启动入口管理",AutoSize=true,MaximumSize=new Size(470,0)});
                Ui.Field(propertiesForm,"编辑范围",new Label {Text="仅显示此平台支持修改的属性。其他原始配置请在停服后编辑对应配置文件；保存不会追加 Java 专有属性。",AutoSize=true,MaximumSize=new Size(470,0)});
                foreach(var field in properties)if(settingsProfile.PropertyAllowed(field.Key))Ui.Field(propertiesForm,names[field.Key],field.Value);
                if(settingsProfile.PropertyAllowed("server-port")||settingsProfile.PropertyAllowed("server-ip"))Ui.Field(propertiesForm,"地址与端口",endpointNote);
                foreach(Control child in new List<Control>(System.Linq.Enumerable.Cast<Control>(runtimeForm.Controls)))if(child!=xms&&child!=xmx&&child!=keepInventory&&child!=sleepers)child.Dispose();
                runtimeForm.Controls.Clear();runtimeForm.RowStyles.Clear();runtimeForm.RowCount=0;
                if(javaRuntime){AdminSection(runtimeForm,"Java 内存","此核心使用 Java；这里只修改运行时内存，不提供 Java 游戏规则。");Ui.Field(runtimeForm,"最小内存（留空自动）",xms);Ui.Field(runtimeForm,"最大内存（留空自动）",xmx);}
            }
            foreach(var field in properties)field.Value.Enabled=settingsProfile.PropertyAllowed(field.Key)&&field.Key!="server-ip"&&field.Key!="server-port";
            xms.Enabled=xmx.Enabled=javaRuntime;keepInventory.Enabled=sleepers.Enabled=javaGame;
            var propertyEdits = new AdminSettingEdits(properties);
            
            var ruleEdits = new AdminSettingEdits(ruleControls);
            tabs.Disposed += delegate {propertyEdits.Dispose();ruleEdits.Dispose();foreach(var field in properties.Values)if(field.Parent==null)field.Dispose();if(runtimeForm.Parent==null)runtimeForm.Dispose();};
            if (!panelOnly) {
                TabPage game = new TabPage(javaGame?"游戏设置":"平台设置"); game.Controls.Add(AdminScroll(propertiesForm)); tabs.TabPages.Add(game);
                if(javaRuntime){TabPage memory = new TabPage(javaGame?"内存与游戏规则":"Java 内存"); memory.Controls.Add(AdminScroll(runtimeForm)); tabs.TabPages.Add(memory);}
            }
            
            bool loaded = false;
            Func<Task> load = async delegate {
                Dictionary<string, object> settings;
                try {settings = await Call(loaded ? "settings.capabilities" : "settings.get", null, targetServer);}
                catch {if(!tabs.IsDisposed){properties["server-port"].Enabled=false;properties["server-ip"].Enabled=false;endpointNote.Text="无法确认停服状态，地址与端口暂不可修改。其他未保存的输入已保留。";}throw;}
                if (tabs.IsDisposed) return;
                Dictionary<string, object> props = AdminPart(settings, "server_properties"), panelPrefs = AdminPart(settings, "panel"), jvm = AdminPart(settings, "jvm"), rules = AdminPart(settings, "gamerules"), capabilities = AdminPart(settings, "capabilities");
                bool endpointEditable=Ui.Bool(capabilities,"server_endpoint_editable");
                properties["server-port"].Enabled=endpointEditable&&settingsProfile.PropertyAllowed("server-port");properties["server-ip"].Enabled=endpointEditable&&settingsProfile.PropertyAllowed("server-ip");
                endpointNote.Text=(endpointEditable?"监控显示已停服；保存时会再次检查进程与端口。":Ui.Text(capabilities,"server_endpoint_lock_reason","仅在服务器完全关闭时允许修改。"))+"\r\nIP 留空表示监听全部网卡；只填服务器电脑的本机 IPv4 / IPv6，不要填写隧道域名或公网连接地址。";
                Ui.Role(endpointNote,endpointEditable?"muted":"warning");
                if (!loaded) {
                propertyEdits.Load(props);  ruleEdits.Load(rules);
                originalXms = Ui.Text(jvm, "xms"); originalXmx = Ui.Text(jvm, "xmx");
                xms.Text = originalXms; xmx.Text = originalXmx;
                }
                loaded = true;
            };
            pageRefresh = load;
            Button save = Ui.Button("保存设置", async delegate {
                if (!loaded) throw new InvalidOperationException("请等待设置加载完成。");
                var memoryChanges = Ui.Obj();
                if (javaRuntime&&xms.Text.Trim() != originalXms) memoryChanges["xms"] = xms.Text.Trim();
                if (javaRuntime&&xmx.Text.Trim() != originalXmx) memoryChanges["xmx"] = xmx.Text.Trim();
                Dictionary<string, object> payload=AdminSettingsPayload(propertyEdits.Changes(),ruleEdits.Changes(),memoryChanges);
                if(payload.Count==0){Ui.Message(Form.ActiveForm,"没有修改任何设置。","七章控制面板",MessageBoxIcon.Information);return;}
                Dictionary<string, object> result = await Call("settings.update", payload, targetServer);
                loaded = false; await load(); AdminMessage(result, "设置已保存。游戏属性和内存将在下次开服时生效。");
            });
            var startupButton=Ui.Button("运行环境与启动参数…",ShowStartupSettingsAsync);startupButton.Visible=!panelOnly;
            propertiesForm.ResumeLayout(false);runtimeForm.ResumeLayout(false);tabs.ResumeLayout(false);
            return AdminContainer("服务器设置", "仅修改当前服务器。按上方分类设置后统一保存，不会立即重启游戏服务器。", tabs, save, startupButton, Ui.Button("重新读取", async delegate { loaded = false; await load(); }));
        }

        private static Dictionary<string,object> AdminSettingsPayload(Dictionary<string,object> properties,Dictionary<string,object> rules,Dictionary<string,object> memory) {
            var payload=Ui.Obj();if(properties.Count>0)payload["server_properties"]=properties;if(memory.Count>0)payload["jvm"]=memory;if(rules.Count>0)payload["gamerules"]=rules;return payload;
        }


        // Track user edit intent independently from control defaults. A missing
        // checkbox explicitly changed to false is a real edit, while an absent
        // value merely rendered by a control is never submitted.
        private sealed class AdminSettingEdits : IDisposable {
            private readonly Dictionary<string,Control> controls;
            private readonly Dictionary<string,object> defaults;
            private Dictionary<string,object> baseline = new Dictionary<string,object>();
            private readonly HashSet<string> present = new HashSet<string>();
            private readonly HashSet<string> touched = new HashSet<string>();
            private readonly ToolTip tips = new ToolTip {AutoPopDelay=20000,ShowAlways=true};
            private bool ready;
            internal AdminSettingEdits(Dictionary<string,Control> controls) {
                this.controls=controls;defaults=AdminReadFields(controls);
                foreach(var entry in controls){
                    string key=entry.Key;Control control=entry.Value;
                    EventHandler changed=delegate {if(ready)touched.Add(key);};
                    if(control is CheckBox)((CheckBox)control).CheckStateChanged+=changed;
                    else if(control is ComboBox)((ComboBox)control).SelectedIndexChanged+=changed;
                    else control.TextChanged+=changed;
                }
            }
            internal void Load(Dictionary<string,object> data) {
                ready=false;
                try{
                    present.Clear();touched.Clear();
                    AdminFillFields(controls,defaults);AdminFillFields(controls,data);
                    foreach(var entry in controls){
                        string key=entry.Key;Control control=entry.Value;bool exists=data.ContainsKey(key);
                        if(exists)present.Add(key);
                        string hint=exists?"原有属性；仅编辑后保存。":"未设置，采用核心默认值；明确选择或输入后才会写入。";
                        tips.SetToolTip(control,hint);control.AccessibleDescription=hint;
                        CheckBox check=control as CheckBox;
                        if(check!=null){check.ThreeState=!exists;if(!exists)check.CheckState=CheckState.Indeterminate;}
                        NumericUpDown number=control as NumericUpDown;if(number!=null&&!exists)number.Text="";
                        ComboBox combo=control as ComboBox;
                        if(combo!=null){
                            for(int index=combo.Items.Count-1;index>=0;index--)if(((AdminOption)combo.Items[index]).Label.StartsWith("原值：")||((AdminOption)combo.Items[index]).Key=="__qz_unset__")combo.Items.RemoveAt(index);
                            string value=exists?Ui.Text(data,key):"__qz_unset__";
                            bool known=false;foreach(AdminOption option in combo.Items)if(option.Key==value)known=true;
                            if(!known)combo.Items.Add(new AdminOption(value,exists?"原值："+value+"（未识别，保留）":"未设置，采用核心默认值"));
                            AdminChoose(combo,value);
                        }
                    }
                    baseline=AdminReadFields(controls);
                }finally{ready=true;}
            }
            internal Dictionary<string,object> Changes() {
                var result=new Dictionary<string,object>();var current=AdminReadFields(controls);
                foreach(string key in touched){
                    Control control=controls[key];
                    if(!control.Enabled)continue;
                    if(control is CheckBox&&((CheckBox)control).CheckState==CheckState.Indeterminate)continue;
                    if(control is ComboBox&&AdminKey((ComboBox)control)=="__qz_unset__")continue;
                    if(control is NumericUpDown&&String.IsNullOrWhiteSpace(control.Text))continue;
                    if(!present.Contains(key)||!Object.Equals(current[key],baseline[key]))result[key]=current[key];
                }
                return result;
            }
            public void Dispose(){tips.Dispose();}
        }
        private static Dictionary<string, object> AdminPart(Dictionary<string, object> value, string key) { object item; return value.TryGetValue(key, out item) ? Ui.Map(item) : new Dictionary<string, object>(); }
        private static decimal AdminMemory(string value) { decimal number; if (String.IsNullOrEmpty(value) || !Decimal.TryParse(value.Substring(0, value.Length - 1), out number)) return 4096; return value.EndsWith("G", StringComparison.OrdinalIgnoreCase) ? number * 1024 : number; }
        private static void AdminFillFields(Dictionary<string, Control> controls, Dictionary<string, object> data) {
            foreach (KeyValuePair<string, Control> item in controls) {
                if (item.Value is CheckBox) ((CheckBox)item.Value).Checked = Ui.Bool(data, item.Key);
                else if (item.Value is ComboBox) AdminChoose((ComboBox)item.Value, Ui.Text(data, item.Key));
                else if (item.Value is NumericUpDown) { NumericUpDown n = (NumericUpDown)item.Value; n.Value = Math.Max(n.Minimum, Math.Min(n.Maximum, AdminDecimal(data, item.Key, n.Value))); }
                else item.Value.Text = Ui.Text(data, item.Key);
            }
        }
        private static Dictionary<string, object> AdminReadFields(Dictionary<string, Control> controls) {
            Dictionary<string, object> result = new Dictionary<string, object>();
            foreach (KeyValuePair<string, Control> item in controls) {
                if (item.Value is CheckBox) result[item.Key] = ((CheckBox)item.Value).Checked;
                else if (item.Value is ComboBox) result[item.Key] = AdminKey((ComboBox)item.Value);
                else if (item.Value is NumericUpDown) result[item.Key] = (int)((NumericUpDown)item.Value).Value;
                else result[item.Key] = item.Value.Text;
            }
            return result;
        }

        private Control AdminBackups() {
            DataGridView grid = Ui.Grid("备份文件", "类型", "大小（MB）", "创建时间");
            grid.Name = "BackupGrid";
            Label summary = AdminSummary("正在读取备份及当前操作…"), selected = AdminSummary("选择备份后，可恢复或删除该文件。"); summary.Name = "BackupExecutionSummary"; selected.Dock = DockStyle.Bottom;
            Panel body = new Panel { Dock = DockStyle.Fill }; body.Controls.Add(grid); body.Controls.Add(selected); body.Controls.Add(summary);
            Button restore = null, remove = null, light = null, full = null; bool operationActive = true, serverStopped = false;
            Action selectionChanged = delegate {
                Dictionary<string, object> row = Ui.Selected(grid); bool valid = row.Count > 0;
                if (restore != null) restore.Enabled = valid && !operationActive && serverStopped;
                if (remove != null) remove.Enabled = valid && !operationActive;
                if (light != null) light.Enabled = !operationActive && serverStopped && CurrentPlatform.Family == "java";
                if (full != null) full.Enabled = !operationActive && serverStopped;
                selected.Text = valid ? "已选择：" + Ui.Text(row, "filename", Ui.Text(row, "name")) + "\r\n" + (Ui.Text(row, "mode") == "light" ? "轻量备份 · 不包含区块地形" : "完整地图备份") + "  ·  " + Ui.Text(row, "size_mb") + " MB  ·  请先停服；恢复前会创建安全备份。" : "选择备份后，可恢复或删除该文件。";
                selected.Height = valid ? 65 : 48;
            };
            Func<Task> load = async delegate {
                Dictionary<string, object> result = await Call("backups.list");
                if (grid.IsDisposed) return;
                List<Dictionary<string, object>> backups = Ui.List(result, "backups");
                AdminRefill(grid, backups, delegate(Dictionary<string, object> item) { return new object[] { Ui.Text(item, "filename", Ui.Text(item, "name")), Ui.Text(item, "mode") == "light" ? "轻量（不含地形）" : "完整地图", Ui.Text(item, "size_mb"), Ui.Text(item, "modified", Ui.Text(item, "created_at")) }; });
                try { Dictionary<string, object> status = await Call("status"); if (grid.IsDisposed) return; var state=ServerPresentation.Read(status); operationActive=state.Busy||state.Countdown||!state.OperationKnown; serverStopped=state.Known&&!state.Running&&!state.Starting; summary.Text = backups.Count + " 份备份\r\n" + (serverStopped?AdminOperationSummary(status):"请先在总览正常停服，确认完全停止后再创建或恢复备份。"); Ui.Role(summary, operationActive || !serverStopped ? "warning" : "muted"); }
                catch (Exception error) { if (grid.IsDisposed) return; operationActive = true; serverStopped = false; summary.Text = "操作状态读取失败 · " + error.Message; Ui.Role(summary, "warning"); }
                summary.Height = 65; selectionChanged();
            };
            pageRefresh = load;
            Func<string, Task> create = async delegate(string mode) {
                if(!serverStopped||operationActive)throw new InvalidOperationException("请先正常停服并等待后台操作完成，再创建备份。");
                if (!AdminConfirm(mode == "light" ? "创建停服轻量备份？将保存玩家和配置等数据，不包含区块地形。" : "创建停服完整备份？将包含地图文件，完成后保持停服。")) return;
                AdminMessage(await Call("backups.create", Ui.Obj("mode", mode)), "备份任务已提交，可在总览查看进度。"); await load();
            };
            light = Ui.Button("停服轻量备份", delegate { return create("light"); }); full = Ui.Button("停服完整备份", delegate { return create("full"); });
            restore = Ui.Button("恢复选中备份", async delegate { Dictionary<string, object> row = AdminSelected(grid); AdminRestoreBackup(Ui.Text(row, "filename", Ui.Text(row, "name"))); await load(); });
            remove = Ui.Button("永久删除选中备份", async delegate { Dictionary<string, object> row = AdminSelected(grid); string filename = Ui.Text(row, "filename", Ui.Text(row, "name")); if (!AdminConfirm("永久删除备份文件“" + filename + "”？")) return; await Call("backups.delete", Ui.Obj("filename", filename)); await load(); });
            Ui.Role(light, "primary"); Ui.Role(restore, "warning"); Ui.Role(remove, "danger");
            grid.SelectionChanged += delegate { selectionChanged(); }; selectionChanged();
            foreach (Button command in new Button[] { restore, remove, light, full }) { Button target = command; target.EnabledChanged += delegate { if (target.Enabled) selectionChanged(); }; }
            return AdminContainer("备份与恢复", "请先正常停止服务器。完整备份包含地图；Java 轻量备份保留玩家与配置但不含地形。后台会在执行前重新检查进程与端口。", body, light, full, restore, AdminMore(remove), Ui.Button("刷新状态", load));
        }
        private void AdminRestoreBackup(string filename) {
            TableLayoutPanel fields = Ui.Fields();
            TextBox confirm = AdminText("", false);
            Ui.Field(fields, "将恢复的文件", new Label { Text = filename, AutoSize = true, MaximumSize = new Size(440, 0) });
            Ui.Field(fields, "恢复说明", new Label { Text = "请先正常停服。面板会创建恢复前备份，恢复完成后保持停服，由你手动启动。请输入完整备份文件名以确认。", AutoSize = true, MaximumSize = new Size(440, 0) });
            Ui.Field(fields, "输入完整文件名", confirm);
            using (Form dialog = AdminDialog("恢复服务器备份", fields, async delegate {
                if (!String.Equals(filename, confirm.Text, StringComparison.Ordinal)) throw new InvalidOperationException("输入的文件名与选中备份不一致。");
                AdminMessage(await Call("backups.restore", Ui.Obj("filename", filename, "confirm", confirm.Text, "restart_after", false)), "恢复任务已提交。");
            })) dialog.ShowDialog(this);
        }

        private Control AdminAccount() {
            Func<Task> load;
            Control page = CreateAccountSettings(null, out load);
            pageRefresh = load;
            return page;
        }
        private async Task<Control> BuildAccountSettingsAsync(Action accountChanged) {
            Func<Task> load;
            Control page = CreateAccountSettings(accountChanged, out load);
            await load();
            return page;
        }
        private Control CreateAccountSettings(Action accountChanged, out Func<Task> load) {
            TableLayoutPanel fields = Ui.Fields();
            TextBox username = AdminText("", false), current = AdminText("", true), password = AdminText("", true), confirm = AdminText("", true);
            username.MaxLength = 64;
            Ui.Field(fields, "管理账号", username); Ui.Field(fields, "当前密码", current); Ui.Field(fields, "新密码（不修改请留空）", password); Ui.Field(fields, "再次输入新密码", confirm);
            Ui.Field(fields, "账号规则", new Label { Text = "账号 1～64 位，不含空格、冒号和斜线；密码 10～128 位。当前账号的服务器与配置独立保存。", AutoSize = true, MaximumSize = new Size(450, 0) });
            bool loaded = false;
            load = async delegate { if (loaded) return; Dictionary<string, object> result = await Call("account.get"); if (username.IsDisposed) return; username.Text = Ui.Text(result, "username"); loaded = true; };
            Button save = Ui.Button("保存账号与密码", async delegate {
                if (String.IsNullOrWhiteSpace(username.Text) || current.Text.Length == 0) throw new InvalidOperationException("请输入账号和当前密码。");
                if (password.Text != confirm.Text) throw new InvalidOperationException("两次输入的新密码不一致。");
                if (password.Text.Length > 0 && password.Text.Length < 10) throw new InvalidOperationException("新密码至少需要 10 位。");
                Dictionary<string, object> result = await Call("account.update", Ui.Obj("username", username.Text.Trim(), "current_password", current.Text, "password", password.Text.Length == 0 ? current.Text : password.Text));
                current.Clear(); password.Clear(); confirm.Clear(); AdminMessage(result, "账号已更新，请重新登录。");
                if (accountChanged != null) { accountChanged(); return; }
                Form settingsDialog = fields.FindForm();
                if (settingsDialog != null && settingsDialog != this) { settingsDialog.DialogResult = DialogResult.OK; settingsDialog.Close(); }
                await AuthenticateAsync();
            });
            return AdminContainer("账号与密码", "修改账号或密码需要验证当前密码。密码通过本机进程通信传递，不会写入日志。", AdminScroll(fields), save);
        }
        private Control AdminPathPicker(TextBox input, bool directory, string title, string filter) {
            TableLayoutPanel row = new TableLayoutPanel { ColumnCount = 2, AutoSize = true, Width = 450, Margin = new Padding(0) };
            row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            input.Dock = DockStyle.Fill; input.Margin = new Padding(0, 4, 6, 0);
            Button browse = Ui.Button("浏览…", delegate {
                if (directory) {
                    using (FolderBrowserDialog picker = new FolderBrowserDialog { Description = title, ShowNewFolderButton = false }) {
                        if (Directory.Exists(input.Text)) picker.SelectedPath = input.Text;
                        if (picker.ShowDialog(this) == DialogResult.OK) input.Text = picker.SelectedPath;
                    }
                } else {
                    using (OpenFileDialog picker = new OpenFileDialog { Title = title, Filter = filter, CheckFileExists = true }) {
                        if (File.Exists(input.Text)) picker.FileName = input.Text;
                        if (picker.ShowDialog(this) == DialogResult.OK) input.Text = picker.FileName;
                    }
                }
                return Task.FromResult(0);
            });
            browse.MinimumSize = new Size(72, 32); browse.Margin = new Padding(0); row.Controls.Add(input, 0, 0); row.Controls.Add(browse, 1, 0); return row;
        }


    }
}


