// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    // Presentation of backend facts only. No guessed progress or synthetic health score.
    internal sealed class ServerPresentation {
        internal bool Known,OperationKnown,Running,Ready,Starting,Busy,Countdown,CanCancel,CanStopStarting,StartupStopRequested,Failed,OperationFailed;
        internal string State="状态未知",Operation="操作状态不可用",Detail="等待后台状态",Stage="",Timing="",SampleTime="",ServerDetail="";
        internal double? Percent;
        internal Dictionary<string,object> Server=Ui.Obj();
        // Operation failures remain independent from the live server lamp.
        internal string Indicator {
            get {
                if(!Known)return "warning";
                if(Failed)return "failed";
                string state=Ui.Text(Server,"state");
                if(Starting||Countdown||state=="stopping"||state=="maintenance")return "warning";
                if(Ready)return "running";
                return Running?"warning":"stopped";
            }
        }
        internal static ServerPresentation Read(Dictionary<string,object> result){
            var value=new ServerPresentation();object raw;
            value.Server=result.TryGetValue("server",out raw)?Ui.Map(raw):result;
            var operation=result.TryGetValue("operation",out raw)?Ui.Map(raw):Ui.Obj();
            var countdown=result.TryGetValue("shutdown_countdown",out raw)?Ui.Map(raw):Ui.Obj();
            value.Known=value.Server.ContainsKey("running");value.OperationKnown=operation.ContainsKey("active");
            if(Ui.Text(result,"workspace_error").Length>0){value.Known=false;value.State="目录不可用";value.ServerDetail=Ui.Text(result,"workspace_error");}
            else if((value.Server.ContainsKey("status_known")&&!Ui.Bool(value.Server,"status_known"))||Ui.Bool(value.Server,"status_stale")||Ui.Text(value.Server,"state")=="unknown"){
                value.Known=false;value.ServerDetail=Ui.Text(value.Server,"monitor_error","后台尚未取得有效状态，请稍后刷新。");if(value.ServerDetail.Length==0)value.ServerDetail="后台状态已过期，请检查监控后刷新。";
            }
            value.Running=Ui.Bool(value.Server,"running");value.Ready=Ui.Bool(value.Server,"ready");value.Starting=Ui.Bool(value.Server,"starting");value.Busy=Ui.Bool(operation,"active");value.Countdown=Ui.Bool(countdown,"active");value.CanCancel=Ui.Bool(countdown,"can_cancel");
            string state=Ui.Text(value.Server,"state");bool authoritative=Array.IndexOf(new[]{"online","starting","stopping","maintenance","crashed","startup_failed","offline"},state)>=0;
            // A historical startup failure can remain cached after a later start/stop.
            // The backend state takes precedence; legacy snapshots use live flags first.
            bool startupFailed=value.Known&&(authoritative?state=="startup_failed":Ui.Bool(value.Server,"startup_failed")&&!value.Starting&&!value.Ready&&!value.Running);
            if(authoritative){value.Starting=state=="starting";value.Ready=state=="online";}
            value.CanStopStarting=value.Starting&&Ui.Bool(value.Server,"can_stop_starting");value.StartupStopRequested=value.Starting&&Ui.Bool(value.Server,"startup_stop_requested");
            if(value.Known)value.State=value.Starting?"正在启动":value.Ready?"正常运行":value.Running?"进程运行中":startupFailed?"启动失败":"已停止";
            if(value.Known)switch(state){case "online":value.State="正常运行";break;case "starting":value.State="正在启动";break;case "stopping":value.State="正在停服";break;case "maintenance":value.State="维护中";break;case "crashed":value.State="异常退出";break;case "startup_failed":value.State="启动失败";break;case "offline":value.State="已停止";break;}
            value.OperationFailed=!value.Busy&&operation.ContainsKey("ok")&&!Ui.Bool(operation,"ok")&&!Ui.Bool(operation,"cancelled");
            value.Failed=value.Known&&(startupFailed||state=="crashed");if(startupFailed)value.ServerDetail=Ui.Text(value.Server,"startup_error");
            value.Operation=value.Countdown?(Ui.Text(countdown,"phase")=="stopping"?"正在保存并停服":"停服倒计时 · "+Ui.Num(countdown,"remaining_seconds").ToString("0")+" 秒"):value.Busy?Ui.Text(operation,"name","正在执行"):value.OperationFailed?"上次操作失败":Ui.Bool(operation,"cancelled")?"操作已取消":value.OperationKnown?"空闲":"操作状态不可用";
            value.Detail=value.Countdown?Ui.Text(countdown,"message"):Ui.Text(operation,"message");if(string.IsNullOrWhiteSpace(value.Detail))value.Detail=value.Busy?"后台正在执行，请稍候。":value.OperationKnown?"当前没有正在执行的操作。":"后台未提供有效操作状态。";
            if(startupFailed&&!value.Busy&&!value.Countdown&&Ui.Text(operation,"message").Length==0)value.Detail=Ui.Text(value.Server,"startup_error",value.Detail);
            var progress=operation.TryGetValue("progress",out raw)?Ui.Map(raw):Ui.Obj();value.Stage=Ui.Text(progress,"stage_label");
            if(progress.ContainsKey("percent")&&!Ui.Bool(progress,"indeterminate")&&(value.Busy||value.OperationFailed))value.Percent=Math.Max(0,Math.Min(100,Ui.Num(progress,"percent")));
            if(value.Busy&&!value.Countdown&&value.Percent.HasValue)value.Operation+=" · "+value.Percent.Value.ToString("0.0")+"%";
            if(progress.ContainsKey("elapsed_seconds"))value.Timing="已用时 "+Duration(Ui.Num(progress,"elapsed_seconds"));
            else if(value.Busy&&operation.ContainsKey("started_at"))value.Timing="开始于 "+Ui.Text(operation,"started_at").Replace('T',' ');
            if(progress.TryGetValue("eta_seconds",out raw)&&raw!=null)value.Timing+=(value.Timing.Length>0?" · ":"")+"预计剩余 "+Duration(Ui.Num(progress,"eta_seconds"));
            value.SampleTime=Ui.Text(value.Server,"updated_at").Replace('T',' ');return value;
        }
        internal static string Duration(double seconds){var span=TimeSpan.FromSeconds(Math.Max(0,Math.Min(seconds,315360000)));return span.TotalHours>=1?((int)span.TotalHours)+" 小时 "+span.Minutes+" 分":span.TotalMinutes>=1?((int)span.TotalMinutes)+" 分 "+span.Seconds+" 秒":span.Seconds+" 秒";}
    }

    internal sealed partial class NativeMainForm {
        private Label serverStateLabel,operationStateLabel;
        private ServerStatusLamp serverStateLamp;
        private Panel serverStateStrip;
        private Button logoutButton;
        private ServerPresentation serverPresentation=new ServerPresentation();
        private long serverStatusRevision;
        private Action<ServerPresentation> dashboardStateChanged;
        private Control BuildNavigation(){
            var area=new Panel {Name="NavigationArea",Dock=DockStyle.Fill,AutoScroll=false};Ui.Role(area,"sidebar");
            var list=new NavigationViewport {Dock=DockStyle.Fill};
            AddNavigationGroup(list,"operations","日常操作","console");
            AddNavigationGroup(list,"maintenance","运维与数据","backups");
            AddNavigationGroup(list,"configuration","配置","settings");
            var overview=new Panel {Name="NavigationOverview",Dock=DockStyle.Top,Height=48,Padding=new Padding(0,0,0,10)};Ui.Role(overview,"sidebar");
            var first=NavigationButton("dashboard");first.Dock=DockStyle.Fill;overview.Controls.Add(first);
            var footer=new Panel {Name="NavigationFooter",Dock=DockStyle.Bottom,Height=48,Padding=new Padding(0,10,0,0)};Ui.Role(footer,"sidebar");
            var editions=Ui.Button("关于软件",ShowEditionInfoAsync);editions.Name="NavigationEdition";editions.AutoSize=false;editions.MinimumSize=Size.Empty;editions.Dock=DockStyle.Fill;editions.Margin=new Padding(0);Ui.Role(editions,"nav");footer.Controls.Add(editions);
            area.Controls.Add(list);area.Controls.Add(overview);area.Controls.Add(footer);
            overview.TabIndex=0;list.TabIndex=1;footer.TabIndex=2;return area;
        }
        private void AddNavigationGroup(NavigationViewport list,string id,string title,params string[] keys){
            NavigationSection group=null;
            foreach(string key in keys)if(ProductEdition.Has(key)){
                if(group==null)group=new NavigationSection(id,title);
                group.AddItem(NavigationButton(key));
            }
            if(group!=null)list.AddSection(group);
        }
        private Button NavigationButton(string key){
            var button=Ui.Button(titles[key],async delegate{if(inServerManagement&&currentPage!=key)await NavigateAsync(key);});
            button.Name="Navigate_"+key;button.AccessibleName=titles[key];button.AutoSize=false;button.MinimumSize=Size.Empty;
            button.Size=new Size(190,36);button.TextAlign=ContentAlignment.MiddleLeft;button.Padding=new Padding(12,0,6,0);button.Margin=new Padding(0);
            Ui.Role(button,"nav");navigation[key]=button;return button;
        }
        private void ResetServerState(string message){
            serverPresentation=new ServerPresentation {State=message,Detail="状态读取后自动更新。"};PublishServerState();
        }
        private void PublishServerState(){
            if(serverStateLabel==null)return;
            serverStateLabel.Text="服务器  ·  "+serverPresentation.State;operationStateLabel.Text="当前操作  ·  "+serverPresentation.Operation;
            serverStateLamp.SetState(serverPresentation.Indicator,serverPresentation.State);
            Ui.Role(serverStateLabel,"title");Ui.Role(operationStateLabel,serverPresentation.OperationFailed?"danger":serverPresentation.Busy||serverPresentation.Countdown?"warning":"muted");
            statusTip.SetToolTip(serverStateLabel,serverPresentation.State+(serverPresentation.ServerDetail.Length>0?"\r\n"+serverPresentation.ServerDetail:"")+(serverPresentation.SampleTime.Length>0?"\r\n后台采样："+serverPresentation.SampleTime:""));statusTip.SetToolTip(operationStateLabel,serverPresentation.Operation+"\r\n"+serverPresentation.Detail+"\r\n"+serverPresentation.Timing);
            if(dashboardStateChanged!=null)dashboardStateChanged(serverPresentation);
        }
        private void ReadServerState(Dictionary<string,object> result){RememberPlatform(result,selectedServerId);UpdatePlatformNavigation();serverPresentation=ServerPresentation.Read(result);serverStatusRevision++;PublishServerState();}
        private async Task RefreshPageAndStatusAsync(){
            long before=serverStatusRevision;
            if(inServerManagement&&currentPage!="dashboard")await Call("status");
            if(pageRefresh!=null)await pageRefresh();
            if(inServerManagement&&before==serverStatusRevision)await Call("status");
        }
        private static void SettingsSection(TableLayoutPanel fields,string title,string description){
            var panel=new Panel {Height=description.Length>0?65:38,Dock=DockStyle.Fill,Margin=new Padding(0,12,0,5)};Ui.Role(panel,"surface");
            var heading=new Label {Text=title,Dock=DockStyle.Top,Height=28,Font=new Font("Microsoft YaHei UI",11F,FontStyle.Bold)};Ui.Role(heading,"title");panel.Controls.Add(heading);
            if(description.Length>0){var hint=new Label {Text=description,Dock=DockStyle.Bottom,Height=33,AutoEllipsis=false};Ui.Role(hint,"muted");panel.Controls.Add(hint);}
            int row=fields.RowCount++;fields.RowStyles.Add(new RowStyle(SizeType.AutoSize));fields.Controls.Add(panel,0,row);fields.SetColumnSpan(panel,2);
        }
    }
}
