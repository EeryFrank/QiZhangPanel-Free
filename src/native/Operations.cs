// QiZhang Control Panel - original panel code belongs to EeryFrank.
// https://github.com/EeryFrank - third-party rights and licenses remain unchanged.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace QiZhang.NativePanel
{
    internal sealed partial class NativeMainForm
    {
        private string opsPendingConsoleCommand = "";

        Control BuildOperationsPage(string key) { return key == "console" ? BuildOpsConsole() : null; }

        static Panel OpsRoot() { var page = new Panel { Dock = DockStyle.Fill, Padding = new Padding(4) }; Ui.Role(page, "canvas"); return page; }
        static Label OpsLabel(string text) { return new Label { Text = text, AutoSize = true, Margin = new Padding(4, 9, 5, 3) }; }
        static TextBox OpsText(int width = 160) { return new TextBox { Width = width, Margin = new Padding(4, 5, 4, 4) }; }
        static ComboBox OpsChoice(params string[] choices)
        {
            var c = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 130, Margin = new Padding(4, 5, 4, 4) };
            c.Items.AddRange(choices); if (choices.Length > 0) c.SelectedIndex = 0; return c;
        }
        bool OpsCurrent(Control page, string id) { return !IsDisposed && !page.IsDisposed && selectedServerId == id; }
        static object OpsValue(Dictionary<string, object> d, string key) { object value; return d != null && d.TryGetValue(key, out value) ? value : null; }
        static IEnumerable<object> OpsValues(object value)
        {
            var list = value as IEnumerable; if (list == null || value is string) yield break;
            foreach (var item in list) yield return item;
        }
        static void OpsRow(DataGridView grid, Dictionary<string, object> source, params object[] cells)
        {
            grid.Rows[grid.Rows.Add(cells)].Tag = source;
            if (grid.CurrentCell == null && grid.Rows.Count > 0) grid.CurrentCell = grid.Rows[0].Cells[0];
        }
        static string OpsTime(string text)
        {
            DateTimeOffset parsed;
            return DateTimeOffset.TryParse(text, out parsed) ? parsed.LocalDateTime.ToString("yyyy-MM-dd HH:mm:ss") : (String.IsNullOrEmpty(text) ? "—" : text);
        }
        static string OpsJoin(object values) { return String.Join("、", OpsValues(values).Select(v => Convert.ToString(v))); }


        bool OpsConfirm(string title, string message)
        { return Ui.Confirm(this, message, title); }
        void OpsMessage(Dictionary<string, object> result, string fallback)
        { SetStatus(Ui.Text(result, "message", fallback)); }
        static void OpsDock(Panel page, Control content, Control toolbar, Control bottom = null)
        {
            content.Dock = DockStyle.Fill; page.Controls.Add(content);
            if (bottom != null) { bottom.Dock = DockStyle.Bottom; page.Controls.Add(bottom); }
            toolbar.Dock = DockStyle.Top; page.Controls.Add(toolbar);
        }

        Control BuildOpsConsole()
        {
            if(DetachedConsoleCurrent)return BuildDetachedConsolePlaceholder();
            var page = OpsRoot(); string id = selectedServerId,account=StartupRecoveryAccount();
            Func<bool> current=()=>OpsCurrent(page,id)&&authenticated&&inServerManagement&&account==StartupRecoveryAccount();
            var search = OpsText(190); search.Name = "ConsoleSearch";
            var level = OpsChoice("全部级别", "INFO", "WARN", "ERROR");
            var limit = new NumericUpDown { Minimum = 20, Maximum = 1000, Value = 350, Width = 75, Margin = new Padding(4, 5, 4, 4) };
            var automatic = new CheckBox { Text = "自动刷新", Checked = true, AutoSize = true, Margin = new Padding(5, 8, 4, 4) };
            var activity = OpsNote("正在读取服务器日志…"); activity.Name = "ConsoleActivity";
            var output = new RichTextBox { Name = "ConsoleOutput", ReadOnly = true, WordWrap = false, Font = new Font("Consolas", 10), BorderStyle = BorderStyle.None, DetectUrls = false };
            Ui.Role(output, "console");
            var command = OpsText(); command.Name = "ConsoleCommand"; command.Dock = DockStyle.Fill; command.MaxLength = 2000;
            command.Text = opsPendingConsoleCommand; opsPendingConsoleCommand = "";
            var history = new List<string>(); int historyIndex = -1; bool sending = false, reading = false;
            string logCursor=null;var logLines=new List<string>();
            Func<bool,Task> readLogs = async reset => {
                if (!current() || reading) return;
                reading = true;
                try {
                    var r = await Call("logs.poll", Ui.Obj("cursor",reset?null:logCursor,"lines", (int)limit.Value, "q", search.Text.Trim(), "level", level.SelectedIndex == 0 ? "" : Convert.ToString(level.SelectedItem)), id);
                    if (!current()) return;
                    var added=OpsValues(OpsValue(r,"lines")).Select(v=>Convert.ToString(v)).ToList();
                    bool replace=reset||Ui.Bool(r,"reset")||logCursor==null;logCursor=Ui.Text(r,"cursor");
                    if(replace)logLines.Clear();logLines.AddRange(added);
                    bool trimmed=false;while(logLines.Count>(int)limit.Value){logLines.RemoveAt(0);trimmed=true;}
                    int characters=logLines.Sum(line=>line.Length+Environment.NewLine.Length);
                    while(characters>400000&&logLines.Count>1){characters-=logLines[0].Length+Environment.NewLine.Length;logLines.RemoveAt(0);trimmed=true;}
                    if(logLines.Count==1&&logLines[0].Length>400000){logLines[0]=logLines[0].Substring(logLines[0].Length-400000);trimmed=true;}
                    if (replace||trimmed||added.Count>0) {
                        bool atEnd = output.SelectionStart + output.SelectionLength >= output.TextLength - 2;
                        int selection = output.SelectionStart, length = output.SelectionLength;
                        if(replace||trimmed)output.Text=String.Join(Environment.NewLine,logLines);
                        else output.AppendText((output.TextLength>0?Environment.NewLine:"")+String.Join(Environment.NewLine,added));
                        if (atEnd || selection == 0) { output.SelectionStart = output.TextLength; output.ScrollToCaret(); }
                        else output.Select(Math.Min(selection, output.TextLength), Math.Min(length, Math.Max(0, output.TextLength - selection)));
                    }
                    if (!sending) OpsActivity(activity, (automatic.Checked ? "自动刷新已开启" : "自动刷新已暂停") + " · 当前显示 " + logLines.Count + " 行 · 更新于 " + DateTime.Now.ToString("HH:mm:ss"));
                } catch (OperationCanceledException) { throw; } catch (Exception error) { if(OpsCurrent(page,id))OpsActivity(activity, "日志读取失败：" + error.Message, true); throw; }
                finally { reading = false; }
            };
            Func<Task> refresh=()=>readLogs(true);
            Func<Task> send = async () => {
                if (!current() || sending) return;
                string text = command.Text.Trim().TrimStart('/'); if (text.Length == 0) return;
                sending = true;
                try {
                    await OpsWorking(activity, "正在发送命令…", "命令已提交；执行结果请查看日志", async () => {
                        var r = await Call("command", Ui.Obj("command", text), id);
                        if (!current()) return;
                        history.Remove(text); history.Insert(0, text); if (history.Count > 30) history.RemoveAt(30);
                        historyIndex = -1; command.Clear(); OpsMessage(r, "命令已提交，结果请查看日志"); await refresh();
                    });
                } finally { sending = false; }
            };
            command.KeyDown += async (s, e) => {
                if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; await Safe(send); }
                else if (e.KeyCode == Keys.Up && history.Count > 0) { e.SuppressKeyPress = true; historyIndex = Math.Min(history.Count - 1, historyIndex + 1); command.Text = history[historyIndex]; command.SelectionStart = command.TextLength; }
                else if (e.KeyCode == Keys.Down) { e.SuppressKeyPress = true; historyIndex = Math.Max(-1, historyIndex - 1); command.Text = historyIndex < 0 ? "" : history[historyIndex]; command.SelectionStart = command.TextLength; }
            };
            automatic.CheckedChanged += delegate { OpsActivity(activity, automatic.Checked ? "自动刷新已开启；按高级设置中的日志刷新规则更新。" : "自动刷新已暂停；服务器日志仍正常记录。"); };
            search.KeyDown += async (s, e) => { if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; await Safe(refresh); } };
            var more = new ContextMenuStrip(); var clear = more.Items.Add("清空当前显示并暂停刷新");
            clear.Click += delegate { output.Clear();logLines.Clear();logCursor=null; automatic.Checked = false; OpsActivity(activity, "当前显示已清空；服务器原始日志保留。自动刷新已暂停。"); };
            page.Disposed += delegate { more.Dispose(); };
            Button extra = null; extra = Ui.Button("显示选项 ▾", () => { more.Show(extra, new Point(0, extra.Height)); return Task.CompletedTask; }); Ui.Role(extra, "secondary");
            Func<Task> automaticRefresh=async () => { if (automatic.Checked) await readLogs(false); };
            Button detach=null;detach=Ui.Button("独立窗口",delegate{if(DetachedConsoleCurrent&&page.FindForm()==detachedConsoleWindow)RestoreDetachedConsole(true);else DetachConsole(page,automaticRefresh,id,account);detach.Text=DetachedConsoleCurrent&&page.FindForm()==detachedConsoleWindow?"返回主面板":"独立窗口";return Task.CompletedTask;});detach.Name="DetachConsole";
            page.ParentChanged+=delegate{detach.Text=DetachedConsoleCurrent&&page.FindForm()==detachedConsoleWindow?"返回主面板":"独立窗口";};
            var filters = Ui.Toolbar(OpsLabel("日志筛选"), search, level, OpsLabel("行数"), limit, automatic, Ui.Button("查询 / 刷新", refresh), extra,detach);
            var sendButton = Ui.Button("发送命令", send); sendButton.Name = "ConsoleSend"; sendButton.Anchor = AnchorStyles.Right; sendButton.Margin = Padding.Empty;
            var commandLabel = OpsLabel("服务器命令 /"); commandLabel.Anchor = AnchorStyles.Left; commandLabel.Margin = new Padding(0, 0, 8, 0);
            command.Dock = DockStyle.None; command.Anchor = AnchorStyles.Left | AnchorStyles.Right; command.Margin = new Padding(0, 5, 8, 5);
            // Let the native table measure the actual text/button height, including
            // DPI and font changes. A fixed-height row inside OpsStack can collapse
            // to zero during its parent's AutoSize pass and hide every command control.
            var commandRow = new TableLayoutPanel { Name = "ConsoleCommandRow", Dock = DockStyle.Fill, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, ColumnCount = 3, RowCount = 1, Margin = Padding.Empty, Padding = new Padding(0, 7, 0, 2) };
            commandRow.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            commandRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize)); commandRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); commandRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            commandRow.Controls.Add(commandLabel, 0, 0); commandRow.Controls.Add(command, 1, 0); commandRow.Controls.Add(sendButton, 2, 0);
            var help = new Label { Name = "ConsoleCommandHelp", Text = "Enter 发送命令 · ↑ / ↓ 选择本次页面的最近命令 · 命令直接发送给当前服务器", AutoSize = true, Dock = DockStyle.Fill, Margin = new Padding(0, 3, 0, 7), Padding = new Padding(0, 2, 0, 2) }; Ui.Role(help, "muted");
            dashboardStateChanged=delegate(ServerPresentation state){if(!help.IsDisposed){var channel=AdminPart(state.Server,"command_channel");help.Text="Enter 发送 · ↑ / ↓ 历史命令 · "+Ui.Text(channel,"label","命令通道等待状态")+"\r\n提交后请查看本次日志，确认服务器执行结果。";}};
            dashboardStateChanged(serverPresentation);
            // Reserve the footer first; only the log card consumes remaining space.
            // The command field must never depend on scrolling the console page.
            var bottom = new TableLayoutPanel { Name = "ConsoleFooter", Dock = DockStyle.Bottom, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, ColumnCount = 1, RowCount = 2, Margin = Padding.Empty, Padding = Padding.Empty };
            bottom.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); bottom.RowStyles.Add(new RowStyle(SizeType.AutoSize)); bottom.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            bottom.Controls.Add(commandRow, 0, 0); bottom.Controls.Add(help, 0, 1); Ui.Role(bottom, "canvas");
            OpsCompose(page, "查看当前服务器日志，按级别与关键字定位问题；在底部发送服务器命令。", filters, OpsCard(output, "实时日志"), bottom, activity);
            pageRefresh = automaticRefresh;
            return page;
        }

    }
}
