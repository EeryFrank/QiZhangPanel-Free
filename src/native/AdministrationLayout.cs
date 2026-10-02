// QiZhang Control Panel - original panel code belongs to EeryFrank.
// https://github.com/EeryFrank - third-party rights and licenses remain unchanged.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal sealed partial class NativeMainForm {
        private static void AdminFitHeading(Panel heading) {
            Label description = heading.Controls["AdminPageDescription"] as Label;
            if (description == null) return;
            int width = Math.Max(200, heading.ClientSize.Width);
            int titleHeight = Convert.ToString(heading.Tag) == "embedded" ? 0 : 34;
            int height = titleHeight + 14 + TextRenderer.MeasureText(description.Text, description.Font, new Size(width, 0), TextFormatFlags.WordBreak).Height;
            if (heading.Height != height) heading.Height = height;
        }
        private static void AdminEmbedPage(Control page) {
            if (page == null || page.Name != "AdminPage") return;
            page.Padding = new Padding(4);
            Panel heading = page.Controls["AdminPageHeadingPanel"] as Panel;
            if (heading == null) return;
            heading.Tag = "embedded";
            Control title = heading.Controls["AdminPageHeading"];
            if (title != null) title.Hide();
            AdminFitHeading(heading);
        }
        private static void AdminSection(TableLayoutPanel fields, string title, string description) {
            int row = fields.RowCount++;
            fields.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            TableLayoutPanel heading = new TableLayoutPanel { AutoSize = true, ColumnCount = 1, Dock = DockStyle.Top, Margin = new Padding(0, row == 0 ? 0 : 12, 0, 6) };
            heading.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            Label name = new Label { Text = title, AutoSize = true, Dock = DockStyle.Top, Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold), Padding = new Padding(4, 5, 0, 0) };
            Label hint = new Label { Text = description, AutoSize = true, Dock = DockStyle.Top, Padding = new Padding(4, 2, 0, 0), MaximumSize = new Size(600, 0) };
            Ui.Role(heading, "surface"); Ui.Role(name, "title"); Ui.Role(hint, "muted");
            heading.Controls.Add(name, 0, 0); heading.Controls.Add(hint, 0, 1); fields.Controls.Add(heading, 0, row); fields.SetColumnSpan(heading, 2);
            heading.SizeChanged += delegate { Size maximum = new Size(Math.Max(180, heading.ClientSize.Width - 12), 0); if (hint.MaximumSize != maximum) hint.MaximumSize = maximum; };
        }
        private static Button AdminMore(params Button[] commands) {
            Button more = new Button { Text = "更多操作 ▾", AutoSize = true, MinimumSize = new Size(108, 36), Padding = new Padding(12, 4, 12, 4), Margin = new Padding(0, 0, 8, 6) };
            ContextMenuStrip menu = new ContextMenuStrip();
            foreach (Button command in commands) {
                Button target = command;
                ToolStripMenuItem item = new ToolStripMenuItem(target.Text);
                item.Click += delegate { if (target.Enabled) target.PerformClick(); };
                target.EnabledChanged += delegate { if (!item.IsDisposed) item.Enabled = target.Enabled; };
                target.TextChanged += delegate { if (!item.IsDisposed) item.Text = target.Text; };
                item.Enabled = target.Enabled; menu.Items.Add(item);
            }
            more.Click += delegate { Ui.ApplyTheme(menu); menu.Show(more, new Point(0, more.Height)); };
            more.Disposed += delegate { menu.Dispose(); foreach (Button command in commands) command.Dispose(); };
            Ui.Role(more, "secondary"); return more;
        }
        private static Label AdminSummary(string text) {
            Label label = new Label { Text = text, Dock = DockStyle.Top, Height = 50, Padding = new Padding(12, 10, 12, 8), AutoEllipsis = true };
            Ui.Role(label, "muted"); return label;
        }
        private static string AdminServerState(Dictionary<string, object> row, string workspaceError) {
            if (!String.IsNullOrEmpty(workspaceError)) return "工作区待修复";
            if (Ui.Bool(row, "status_stale")) return "状态已过期 · 待刷新";
            if (row.ContainsKey("status_known") && !Ui.Bool(row, "status_known")) return "状态未知";
            string lifecycle = Ui.Text(row, "lifecycle_state", Ui.Text(row, "state"));
            switch (lifecycle) {
                case "online": return "运行中";
                case "starting": return "启动中";
                case "running": return "运行中";
                case "stopping": return "停服中";
                case "restarting": return "重启中";
                case "maintenance": return "维护中";
                case "offline": case "stopped": return "已停止";
                case "startup_failed": return "启动失败";
                case "unknown": return "状态未知";
                case "failed": case "crashed": return "异常退出";
            }
            if (Ui.Bool(row, "starting")) return "启动中";
            if (Ui.Bool(row, "running")) return "运行中";
            return row.ContainsKey("running") ? "已停止" : "尚未读取";
        }
        private static string AdminServerActivity(Dictionary<string, object> row) {
            Dictionary<string, object> countdown = AdminPart(row, "shutdown_countdown"), operation = AdminPart(row, "operation");
            if (Ui.Bool(countdown, "active")) return Ui.Text(countdown, "phase") == "stopping" ? "正在停服 · " + Ui.Text(countdown, "message", "正在安全关闭服务器") : "停服倒计时 · " + Ui.Text(countdown, "remaining_seconds", "—") + " 秒";
            if (!operation.ContainsKey("active")) return "操作状态尚未读取";
            if (!Ui.Bool(operation, "active")) return operation.ContainsKey("ok") && !Ui.Bool(operation, "ok") ? "上次操作失败 · " + Ui.Text(operation, "message") : "无正在执行的操作";
            Dictionary<string, object> progress = AdminPart(operation, "progress");
            string phase = Ui.Text(progress, "stage_label", Ui.Text(operation, "message"));
            return Ui.Text(operation, "name", "处理中") + (phase.Length == 0 ? "" : " · " + phase);
        }
        private static string AdminInstallPhase(Dictionary<string, object> status) {
            switch (Ui.Text(status, "phase")) {
                case "installing": return "正在安装";
                case "awaiting_selection": return "等待选择启动目标";
                case "complete": return "安装完成";
                case "failed": return "安装失败";
                case "idle": return "等待安装";
                default: return Ui.Bool(status, "active") ? "正在处理" : "暂无安装任务";
            }
        }
        private static string AdminOperationSummary(Dictionary<string, object> status) {
            Dictionary<string, object> operation = AdminPart(status, "operation"), countdown = AdminPart(status, "shutdown_countdown");
            if (Ui.Bool(countdown, "active")) return "停服通知进行中 · " + Ui.Text(countdown, "message", "剩余 " + Ui.Text(countdown, "remaining_seconds", "—") + " 秒");
            if (Ui.Bool(operation, "active")) return "正在执行 · " + Ui.Text(operation, "name", "服务器操作") + "  " + Ui.Text(operation, "message");
            string error = Ui.Text(operation, "error");
            if (error.Length > 0) return "上次操作未完成 · " + error;
            string message = Ui.Text(operation, "message");
            if (operation.ContainsKey("ok") && !Ui.Bool(operation, "ok")) return "上次操作未完成 · " + message;
            return message.Length == 0 ? "当前没有备份、恢复或停服操作。" : "最近操作 · " + message;
        }
        private async Task AdminShowInstallStatusAsync() {
            using (Form dialog = new Form { Text = "安装任务状态", Width = 720, Height = 455, MinimumSize = new Size(590, 370), StartPosition = FormStartPosition.CenterParent, Font = Font, MinimizeBox = false, MaximizeBox = false }) {
                TableLayoutPanel fields = Ui.Fields();
                Label phase = new Label { AutoSize = true, MaximumSize = new Size(420, 0), Font = new Font(Font, FontStyle.Bold) };
                Label detail = new Label { AutoSize = true, MaximumSize = new Size(420, 0) };
                Label error = new Label { AutoSize = true, MaximumSize = new Size(420, 0) };
                ProgressBar progress = new ProgressBar { Minimum = 0, Maximum = 100, Width = 410, Height = 20 };
                Ui.Role(error, "danger");
                Ui.Field(fields, "当前阶段", phase); Ui.Field(fields, "后台报告进度", progress); Ui.Field(fields, "执行内容", detail); Ui.Field(fields, "错误信息", error);
                Func<Task> load = async delegate {
                    Dictionary<string, object> result = await Call("server.install.status");
                    if (dialog.IsDisposed) return;
                    phase.Text = AdminInstallPhase(result) + (Ui.Bool(result, "active") ? " · 执行中" : " · 未在执行");
                    progress.Value = (int)Math.Max(0, Math.Min(100, Ui.Num(result, "progress")));
                    detail.Text = Ui.Text(result, "message", "尚无详情。") + "\r\n后台报告 " + progress.Value + "%（手动刷新）";
                    error.Text = Ui.Text(result, "error", "无"); if (error.Text.Length == 0) error.Text = "无";
                };
                dialog.Controls.Add(AdminContainer("安装任务", "关闭此查看窗口不会终止后台安装。状态属于当前账号，可重新进入查看。", AdminScroll(fields), Ui.Button("刷新状态", load), Ui.Button("关闭", delegate { dialog.Close(); return Task.FromResult(0); })));
                await load(); Ui.ApplyTheme(dialog); dialog.ShowDialog(this);
            }
        }
    }
}
