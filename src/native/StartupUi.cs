// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal sealed partial class NativeMainForm {
        private static string StartupLines(Dictionary<string,object> value,string key){object raw;if(!value.TryGetValue(key,out raw)||!(raw is IEnumerable)||raw is string)return "";var lines=new List<string>();foreach(object item in (IEnumerable)raw)lines.Add(Convert.ToString(item));return String.Join("\r\n",lines.ToArray());}
        private async Task ShowStartupSettingsAsync() {
            string target=selectedServerId;poll.Stop();
            try {
                var data=await Call("launch.settings",null,target);var capabilities=await Call("settings.capabilities",null,target);
                bool supported=Ui.Bool(data,"supported"), editable=Ui.Bool(AdminPart(capabilities,"capabilities"),"server_endpoint_editable");
                var profile=PlatformUiProfile.Read(data);if(profile.Id.Length==0)profile=CurrentPlatform;
                bool isJava=profile.Runtime=="java",isPhp=profile.Runtime=="php";
                var fields=Ui.Fields();var java=AdminText(Ui.Text(data,isJava?"java_path":"runtime_path",Ui.Text(data,"executable_path")),false);java.Name=isJava?"StartupJava":"StartupRuntime";
                var jvm=new TextBox {Name=isJava?"StartupJvm":"StartupRuntimeArgs",Multiline=true,ScrollBars=ScrollBars.Vertical,Height=160,Text=StartupLines(data,isJava?"jvm_args":"runtime_args"),WordWrap=false};
                var game=new TextBox {Name="StartupServerArgs",Multiline=true,ScrollBars=ScrollBars.Vertical,Height=85,Text=StartupLines(data,"server_args"),WordWrap=false};
                Ui.Field(fields,"服务端平台",new Label {Text=profile.Label+" · "+Ui.Text(data,"minecraft_version"),AutoSize=true});
                Ui.Field(fields,"运行环境",new Label {Text=isJava?Ui.Text(AdminPart(data,"java_requirement"),"label","版本尚未识别；请按核心要求选择 Java，保存时会验证。"):isPhp?"此平台使用匹配版本的专用 PHP 及扩展，不使用 Java。" :profile.Runtime=="native"?"此平台直接运行原生程序，不使用 Java。":"后台尚未识别此启动入口的运行时，请先检查核心与启动配置。",AutoSize=true,MaximumSize=new Size(470,0)});
                if(!isJava)Ui.Field(fields,"启动核心",new TextBox {Name="StartupEntry",ReadOnly=true,Text=Ui.Text(data,"entry"),Width=430});
                Ui.Field(fields,profile.RuntimeLabel+" 路径",java);
                var browse=Ui.Button("选择 "+profile.RuntimeLabel+"…",delegate{using(var picker=new OpenFileDialog {Filter=isJava?"Java (java.exe)|java.exe":isPhp?"PHP (php.exe)|php.exe":"可执行文件 (*.exe)|*.exe",CheckFileExists=true})if(picker.ShowDialog(this)==DialogResult.OK)java.Text=picker.FileName;return Task.CompletedTask;});browse.Visible=true;Ui.Field(fields,"",browse);
                Ui.Field(fields,isJava?"JVM 参数（每行一个）":"运行时参数（每行一个）",jvm);Ui.Field(fields,"服务端参数（每行一个）",game);
                Ui.Field(fields,"说明",new Label {Text=Ui.Text(data,"message")+"\r\n参数逐行填写，不加外层双引号。"+(isJava?"内存可用 -Xms1G / -Xmx4G 修改。":"不接受 JVM 内存参数。")+"监听地址和端口请在服务器设置中调整。",AutoSize=true,MaximumSize=new Size(470,0)});
                {
                    var state=await Call("status",null,target);
                    if(Ui.Bool(AdminPart(state,"server"),"starting")&&!Ui.Bool(AdminPart(state,"operation"),"active")){
                        var reset=Ui.Button("结束已关闭启动器的旧任务记录…",async delegate{await ClearClosedLauncherRecordAsync(target);});reset.Name="ClearClosedLauncherRecord";
                        Ui.Field(fields,"旧版状态恢复",reset);
                    }
                }
                if(!editable)Ui.Field(fields,"暂不可修改",new Label {Text="请完全停止服务器后重新打开启动配置。",AutoSize=true});
                java.Enabled=jvm.Enabled=game.Enabled=browse.Enabled=supported&&editable;
                using(var dialog=AdminDialog("服务器启动配置",fields,async delegate {
                    if(!supported||!editable)throw new InvalidOperationException("请先完全停服，并确认面板识别了唯一启动核心。");
                    var result=await Call("launch.save",Ui.Obj(isJava?"java_path":"runtime_path",java.Text.Trim(),isJava?"jvm_args":"runtime_args",jvm.Text,"server_args",game.Text),target);
                    SetStatus(Ui.Text(result,"message"));
                })){foreach(Control button in dialog.Controls.Find("AdminDialogSave",true))button.Enabled=supported&&editable;dialog.ShowDialog(this);}
            } finally {if(authenticated&&Visible&&!exiting)poll.Start();}
        }
        private Task ClearClosedLauncherRecordAsync(string target){
            string account=StartupRecoveryAccount();RpcClient origin=rpc;
            var fields=Ui.Fields();
            Ui.Field(fields,"适用情况",new Label {Text="仅用于已手动关闭原管理器与服务器，旧版仍卡在“启动中”的情况。它只结束旧任务记录，不会关闭进程、删除服务器或自动开服；后续操作仍会重新检查进程。",AutoSize=true,MaximumSize=new Size(470,0)});
            Ui.Field(fields,"请核对",new Label {Text="请确认该服务器及所有自带启动器都已退出，再输入下面的完整文字。若仍有进程或后台任务，后台会拒绝恢复。",AutoSize=true,MaximumSize=new Size(470,0)});
            Ui.Field(fields,"确认文字",new Label {Text="已关闭所有原启动器和服务器",AutoSize=true});
            var input=AdminText("",false);input.Name="ClosedLauncherAcknowledgement";Ui.Field(fields,"输入确认",input);
            using(var dialog=AdminDialog("结束旧启动任务记录",fields,async delegate{
                if(!StartupRecoveryContext(target,account)||rpc!=origin)throw new InvalidOperationException("当前连接、账号或服务器已变化，请重新核对。");
                const string acknowledgement="已关闭所有原启动器和服务器";
                if(input.Text!=acknowledgement)throw new InvalidOperationException("请先核对全部原启动器已关闭，再输入完整确认文字。");
                var result=await Call("server.startup.clear_record",Ui.Obj("confirmed",true,"acknowledgement",acknowledgement),target);
                SetStatus(Ui.Text(result,"message")+" 关闭配置窗口后即可刷新状态。");
            })){
                foreach(Control control in dialog.Controls.Find("AdminDialogSave",true))control.Text="核对并结束旧记录";
                dialog.ShowDialog(this);
            }
            return Task.CompletedTask;
        }
    }
}
