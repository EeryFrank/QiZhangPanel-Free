// Copyright (c) 2026 EeryFrank - https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal static class ProductEdition {
        internal const string Id = "free";
        internal const string Label = "免费版";
        internal static bool Has(string feature) {
            return Array.IndexOf(new[] {"dashboard", "console", "servers", "settings", "backups", "account", "install", "manual_backup"}, feature) >= 0;
        }
        internal static string Title { get { return "七章控制面板 · " + Label; } }
        internal static void Require(string feature) {
            if (!Has(feature)) throw new InvalidOperationException("此页面不在当前程序中。当前为" + Label + "，基础服务器管理可继续使用。");
        }
    }

    internal sealed partial class NativeMainForm {
        private bool freeSlotAvailable, freeCanAddServer;
        private void ReadEditionSlot(Dictionary<string, object> data) {
            object raw;
            Dictionary<string, object> edition = data.TryGetValue("edition", out raw) ? Ui.Map(raw) : Ui.Obj();
            freeCanAddServer = Ui.Bool(edition, "can_add_server");
            freeSlotAvailable = edition.ContainsKey("slot_assigned") && !Ui.Bool(edition, "slot_assigned") &&
                !Ui.Bool(edition, "slot_owned_by_another_account") && Ui.Text(edition, "slot_error").Length == 0;
        }
        private async Task EnsureEditionServerAsync(string serverId) {
            Dictionary<string, object> data = await Call("servers.list"); ReadEditionSlot(data);
            Dictionary<string, object> selected = null;
            foreach (Dictionary<string, object> row in Ui.List(data, "servers")) if (Ui.Text(row, "id") == serverId) {selected = row; break;}
            if (selected == null) throw new InvalidOperationException("服务器已不在当前账号的列表中，请刷新后重试。");
            if (!Ui.Bool(selected, "edition_locked")) return;
            if (!freeSlotAvailable) throw new InvalidOperationException(Ui.Text(selected, "edition_lock_reason", "免费版仅可管理已选定的一台服务器。其他服务器文件与记录仍保留。"));
            if (!Ui.Confirm(this, "免费版在整个安装中共支持 1 台服务器。\r\n\r\n将“" + Ui.Text(selected, "name") + "”设为免费版管理的服务器？\r\n其他记录及文件会保留；移除此绑定后才能重新选择。", "选择免费版服务器"))
                throw new OperationCanceledException("已取消服务器选择。");
            await Call("edition.select-server", Ui.Obj("id", serverId)); await RefreshServers();
        }

        private Task ShowEditionInfoAsync() {
            Ui.Message(this,"七章控制面板 · 免费版 2.5.7\r\n\r\n支持全安装共一台服务器，安装与导入、开停服、控制台、基础设置、手动备份与恢复。\r\n\r\n项目采用 GNU GPL v3 许可。版权归 EeryFrank 所有。", "关于七章控制面板", MessageBoxIcon.Information);
            return Task.FromResult(0);
        }

        private void AddEditionSettings(TableLayoutPanel fields) {
            SettingsSection(fields,"软件版本","免费版 · "+typeof(NativeMainForm).Assembly.GetName().Version.ToString(3));
            Ui.Field(fields,"软件说明",Ui.Button("关于七章控制面板",ShowEditionInfoAsync));
        }


    }
}
