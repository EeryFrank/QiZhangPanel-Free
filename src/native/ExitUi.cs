// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal sealed partial class NativeMainForm {
        private bool exitInProgress;
        private async Task<bool> PrepareLocalExitAsync(){
            var state=await Call("panel.exit.status");
            if(Ui.Bool(state,"busy")&&!Ui.Bool(state,"active"))throw new InvalidOperationException(Ui.Text(state,"message","后台还有任务正在执行，请完成后再退出。"));
            if(!Ui.Bool(state,"active")&&Ui.Num(state,"running_count")==0)return true;
            if(!Ui.Bool(state,"active")){
                if(!Visible)RestoreWindow();poll.Stop();
                string prompt="是否一并安全关闭正在运行的服务器并退出面板？\r\n\r\n当前共有 "+Ui.Num(state,"running_count").ToString("0")+" 台托管服务器正在运行。\r\n确认后会等待保存世界并正常停服；取消则保留面板与服务器。";
                if(!Ui.Confirm(this,prompt,"安全关服并退出"))return false;
                // One explicit prepare request. Failed or uncertain stops are never
                // automatically submitted again by this UI.
                state=await Call("panel.exit.prepare",Ui.Obj("confirmed",true));
            }
            using(var dialog=new Form {Text="正在安全关服",ClientSize=new Size(620,250),StartPosition=FormStartPosition.CenterParent,ControlBox=false,MinimizeBox=false,MaximizeBox=false,Font=Font}){
                var detail=new Label {Name="ExitShutdownProgress",Dock=DockStyle.Fill,Padding=new Padding(24),AutoEllipsis=false,Text="正在请求服务器保存世界…"};
                var hint=new Label {Dock=DockStyle.Bottom,Height=65,Padding=new Padding(24,8,24,12),Text="完成安全停服后才退出。若停服失败，面板会保留并显示原因。"};Ui.Role(hint,"muted");dialog.Controls.Add(detail);dialog.Controls.Add(hint);Ui.ApplyTheme(dialog);
                bool allowClose=false;dialog.FormClosing+=delegate(object sender,FormClosingEventArgs e){if(!allowClose)e.Cancel=true;};dialog.Show(this);
                try{
                    while(true){
                        detail.Text="已完成 "+Ui.Num(state,"completed_count").ToString("0")+" / "+Ui.Num(state,"total_count").ToString("0")+" 台\r\n\r\n"+Ui.Text(state,"message","等待服务器完成保存并退出…");
                        SetStatus(detail.Text.Replace("\r\n"," "));
                        if(!Ui.Bool(state,"active")){
                            if(Ui.Text(state,"phase")=="failed"||Ui.Text(state,"error").Length>0)throw new InvalidOperationException(Ui.Text(state,"error",Ui.Text(state,"message","服务器未能安全关闭，面板已保留。")));
                            if(Ui.Bool(state,"all_stopped")&&!Ui.Bool(state,"busy"))return true;
                            throw new InvalidOperationException(Ui.Text(state,"message","仍有服务器或后台任务未结束，面板已保留。"));
                        }
                        await Task.Delay(300);state=await Call("panel.exit.status");
                    }
                }finally{allowClose=true;dialog.Close();}
            }
        }
    }
}
