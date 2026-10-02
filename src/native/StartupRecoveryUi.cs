// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Runtime.ExceptionServices;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal sealed partial class NativeMainForm {
        private readonly Dictionary<string,string> startupRecoveryShown=new Dictionary<string,string>(StringComparer.Ordinal);
        private bool startupRecoveryBusy;
        private string startupRecoveryPending="";
        private string StartupRecoveryAccount(){return Ui.Text(currentAccount,"id",Ui.Text(currentAccount,"username"));}
        private bool StartupRecoveryContext(string target,string account){return !IsDisposed&&!exiting&&authenticated&&Visible&&inServerManagement&&target==selectedServerId&&account==StartupRecoveryAccount();}
        private bool QueueStartupRecovery(Dictionary<string,object> result,string target,string previousOperation=null){
            var server=AdminPart(result,"server");string operation=Ui.Text(server,"startup_operation_id"),account=StartupRecoveryAccount(),key=account+"\n"+target;
            // Native/PHP entrypoints do not use the Java launcher alternatives.
            // Older Java backends omit this capability, retaining their behavior.
            if(server.ContainsKey("startup_recovery_supported")&&!Ui.Bool(server,"startup_recovery_supported"))return false;
            if(!StartupRecoveryContext(target,account)||operation.Length==0||operation==previousOperation||!Ui.Bool(server,"startup_failed")||!Ui.Bool(server,"startup_adaptation_enabled")||!Ui.Bool(server,"managed_startup"))return false;
            string shown;if(startupRecoveryShown.TryGetValue(key,out shown)&&shown==operation)return true;
            if(startupRecoveryBusy)return startupRecoveryPending==key+"\n"+operation;
            startupRecoveryBusy=true;startupRecoveryPending=key+"\n"+operation;
            try{BeginInvoke(new Action(async delegate {
                try{
                    if(!StartupRecoveryContext(target,account))return;
                    startupRecoveryShown[key]=operation;poll.Stop();
                    await OfferStartupAlternativesAsync(target,account,operation,Ui.Text(server,"startup_error"));
                }catch(Exception error){if(StartupRecoveryContext(target,account)){SetStatus(error.Message);Ui.Message(this,error.Message,"启动项检查未完成",MessageBoxIcon.Warning);}}
                finally{startupRecoveryBusy=false;startupRecoveryPending="";if(authenticated&&Visible&&!exiting)poll.Start();}
            }));}catch(InvalidOperationException){startupRecoveryBusy=false;startupRecoveryPending="";return false;}
            return true;
        }
        private async Task StartServerWithRecoveryAsync(){
            string target=selectedServerId,previousOperation=Ui.Text(serverPresentation.Server,"startup_operation_id");
            if(!await EnsureServerEulaAsync())return;
            Exception failure=null;
            try{await Call("server.action",Ui.Obj("action","start"),target);}catch(Exception error){failure=error;}
            if(failure!=null){
                // A rejected/busy request must not turn an older failure into a
                // new fallback prompt. Use the backend's startup operation ID.
                try{var state=await rpc.Call("status",null,target);if(target==selectedServerId){ReadServerState(state);if(QueueStartupRecovery(state,target,previousOperation))return;}}catch(Exception){/* Preserve the original startup error. */}
                ExceptionDispatchInfo.Capture(failure).Throw();
            }
            await RefreshCurrentPageAsync();
        }
        private async Task OfferStartupAlternativesAsync(string target,string account,string startupOperation,string startupError){
            var result=await Call("launch.alternatives",null,target);
            if(!StartupRecoveryContext(target,account))return;
            var items=Ui.List(result,"items");string message=Ui.Text(result,"message","专用启动入口未能完成启动。请检查原启动文件或选择其他启动项。");
            if(!Ui.Bool(result,"available")||items.Count==0){SetStatus(message);Ui.Message(this,message,"无法切换启动项",MessageBoxIcon.Warning);return;}
            using(var dialog=new Form {Text="选择其他启动项",Width=760,Height=600,MinimumSize=new Size(640,480),StartPosition=FormStartPosition.CenterParent,Font=Font,MinimizeBox=false,MaximizeBox=false}){
                var fields=Ui.Fields();var choice=new ComboBox {Name="StartupAlternativeChoice",DropDownStyle=ComboBoxStyle.DropDownList,Width=430};
                var detail=new TextBox {Name="StartupAlternativeDetails",Multiline=true,ReadOnly=true,WordWrap=true,ScrollBars=ScrollBars.Vertical,Height=130,Width=430};
                var candidates=new Dictionary<string,Dictionary<string,object>>(StringComparer.Ordinal);
                choice.Items.Add(new AdminOption("","请选择启动项（尚未选择）"));
                foreach(var item in items){string id=Ui.Text(item,"id");if(id.Length==0||candidates.ContainsKey(id))continue;candidates.Add(id,item);choice.Items.Add(new AdminOption(id,Ui.Text(item,"label",Ui.Text(item,"source",id))));}
                choice.SelectedIndex=0;
                Ui.Field(fields,"启动失败",new TextBox {Name="StartupRecoveryError",Text=startupError,Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,WordWrap=true,Height=90,Width=430});
                Ui.Field(fields,"其他启动项",choice);Ui.Field(fields,"入口说明",detail);
                Ui.Field(fields,"提示",new Label {Text="取消会保留当前启动配置。只有点击“使用所选启动项并启动”才会切换并开服；原启动文件保留。",AutoSize=true,MaximumSize=new Size(450,0)});
                bool submitting=false;Button submit=null;
                submit=Ui.Button("使用所选启动项并启动",async delegate {
                    if(submitting)return;Dictionary<string,object> selected;
                    if(!candidates.TryGetValue(AdminKey(choice),out selected))return;
                    if(!StartupRecoveryContext(target,account))throw new InvalidOperationException("当前账号或服务器已改变，请重新打开对应服务器。");
                    submitting=true;submit.Enabled=false;choice.Enabled=false;
                    try{
                        if(!await EnsureServerEulaAsync())return;
                        if(!StartupRecoveryContext(target,account))throw new InvalidOperationException("当前账号或服务器已改变，未切换启动项。");
                        await Call("launch.use_alternative",Ui.Obj("id",Ui.Text(selected,"id"),"confirmed",true,"startup_operation_id",startupOperation),target);
                        // This is one explicit user action. Never automatically
                        // retry a rejected switch or an uncertain start request.
                        await Call("server.action",Ui.Obj("action","start"),target);
                        SetStatus("已切换启动项并提交开服，请查看服务器状态和控制台。");submitting=false;dialog.DialogResult=DialogResult.OK;dialog.Close();
                    }finally{submitting=false;if(!dialog.IsDisposed){choice.Enabled=true;submit.Enabled=candidates.ContainsKey(AdminKey(choice));}}
                });submit.Name="StartupAlternativeSubmit";submit.Enabled=false;
                var cancel=Ui.Button("取消",delegate{dialog.Close();return Task.CompletedTask;});cancel.Name="StartupAlternativeCancel";
                choice.SelectedIndexChanged+=delegate{Dictionary<string,object> selected;bool valid=candidates.TryGetValue(AdminKey(choice),out selected);detail.Text=valid?"来源："+Ui.Text(selected,"source","未提供")+"\r\n\r\n"+Ui.Text(selected,"reason"):"请选择一个启动项；不会自动选择第一个入口。";submit.Enabled=!submitting&&valid;};
                dialog.FormClosing+=delegate(object sender,FormClosingEventArgs e){if(submitting)e.Cancel=true;};
                dialog.Controls.Add(AdminContainer("专用启动入口启动失败",message,AdminScroll(fields),submit,cancel));dialog.CancelButton=cancel;Ui.ApplyTheme(dialog);dialog.ShowDialog(this);
            }
        }
    }
}
