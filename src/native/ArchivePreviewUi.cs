// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Linq;

namespace QiZhang.NativePanel {
    internal sealed partial class NativeMainForm {
        private static string ArchiveRuntimeSource(string source) {
            switch(source) {
                case "bundled": return "压缩包内置运行环境";
                case "bundled-outer-pending": return "压缩包外层内置运行环境（待安装确认）";
                case "local-manual": return "本机手动选择";
                case "local-auto": return "本机自动匹配";
                case "local-auto-pending": return "确认安装时自动匹配本机版本";
                default: return "待确认";
            }
        }
        private static string ArchiveCommandChannel(string channel) {
            if(channel=="owned-stdin")return "面板托管标准输入";
            if(channel=="original-script-capture")return "原启动脚本；命令通道待开服后确认";
            return "待开服后确认";
        }
        private static string ArchivePreviewText(Dictionary<string,object> preview) {
            var selected=AdminPart(preview,"selected");var runtime=AdminPart(preview,"runtime");var launch=AdminPart(preview,"launch");var template=AdminPart(preview,"template");
            var lines=new List<string>{
                "服务端："+Ui.Text(selected,"platform","未确定")+" · Minecraft "+Ui.Text(preview,"minecraft_version","未知"),
                "加载器版本："+Ui.Text(preview,"loader_version","未确定"),
                "运行环境："+Ui.Text(runtime,"kind")+" · "+Ui.Text(AdminPart(runtime,"requirement"),"label"),
                "运行环境来源："+ArchiveRuntimeSource(Ui.Text(runtime,"source"))+" · "+Ui.Text(runtime,"reason"),
                "运行环境路径："+Ui.Text(runtime,"selected_path","安装时检查"),
                "启动入口："+Ui.Text(launch,"entry")+" · "+Ui.Text(launch,"kind"),
                "JVM 参数："+OpsJoin(OpsValue(launch,"jvm_args")),
                "服务端参数："+OpsJoin(OpsValue(launch,"server_args")),
                "命令通道："+ArchiveCommandChannel(Ui.Text(launch,"command_channel")),
                "适配规则："+Ui.Text(template,"template_id")+" / "+Ui.Text(template,"template_version")
            };
            foreach(var item in Ui.List(preview,"version_evidence"))lines.Add("版本依据："+Ui.Text(item,"source")+" → "+Ui.Text(item,"version"));
            if(Ui.Bool(launch,"arguments_pending"))lines.Add("启动参数：需由已识别的官方安装器在确认安装后生成，当前尚未确定。");
            var caps=AdminPart(preview,"capabilities");
            lines.Add("可用功能："+String.Join("、",new[]{new[]{"console","控制台"},new[]{"players","玩家管理"},new[]{"save_world","保存世界"},new[]{"online_backup","在线备份"}}.Where(pair=>Ui.Bool(caps,pair[0])).Select(pair=>pair[1])));
            foreach(var item in OpsValues(OpsValue(preview,"uncertainties")))lines.Add("待确认："+Convert.ToString(item));
            return String.Join(Environment.NewLine,lines);
        }
    }
}
