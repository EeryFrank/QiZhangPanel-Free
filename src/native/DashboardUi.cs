// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Collections;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Net;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    // Displays only facts supplied by the selected server backend.
    internal sealed class ServerConnectionAddressPanel : TableLayoutPanel {
        private sealed class AddressChoice {
            internal string Value,Scope;
            public override string ToString(){return Scope+" · "+Value;}
        }
        private readonly Label serverIp,configuration,stateNote;
        private readonly ComboBox addresses;
        private readonly Button copy;
        private string renderedAddressKey;
        internal ServerConnectionAddressPanel(){
            Name="ServerConnectionAddresses";Dock=DockStyle.Top;AutoSize=true;AutoSizeMode=AutoSizeMode.GrowAndShrink;ColumnCount=3;RowCount=4;Padding=new Padding(16,12,16,12);Margin=Padding.Empty;
            ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));for(int i=0;i<4;i++)RowStyles.Add(new RowStyle(SizeType.AutoSize));Ui.Role(this,"surface");
            var ipCaption=new Label {Text="服务器 IP",AutoSize=true,Anchor=AnchorStyles.Left,Margin=new Padding(0,4,14,7)};Ui.Role(ipCaption,"muted");
            serverIp=new Label {Name="ServerIpAddresses",Text="等待后台提供服务器地址…",AutoSize=true,Dock=DockStyle.Fill,Margin=new Padding(0,4,0,7),UseMnemonic=false};
            var addressCaption=new Label {Text="连接地址",AutoSize=true,Anchor=AnchorStyles.Left,Margin=new Padding(0,4,14,7)};Ui.Role(addressCaption,"muted");
            addresses=new ComboBox {Name="ServerConnectionAddress",DropDownStyle=ComboBoxStyle.DropDownList,Dock=DockStyle.Fill,Margin=new Padding(0,3,10,7)};
            addresses.SizeChanged+=delegate{renderedAddressKey=null;};addresses.FontChanged+=delegate{renderedAddressKey=null;};
            copy=Ui.Button("复制地址",delegate{var selected=addresses.SelectedItem as AddressChoice;if(selected!=null){Clipboard.SetText(selected.Value);copy.Text="已复制";}return Task.CompletedTask;});copy.Name="CopyServerConnectionAddress";copy.Anchor=AnchorStyles.Right;copy.Margin=new Padding(0,0,0,5);copy.Enabled=false;
            addresses.SelectedIndexChanged+=delegate{copy.Text="复制地址";copy.Enabled=addresses.SelectedItem is AddressChoice;};
            configuration=new Label {Name="ServerAddressConfiguration",AutoSize=true,Dock=DockStyle.Fill,Margin=new Padding(0,3,0,3),UseMnemonic=false};Ui.Role(configuration,"muted");
            stateNote=new Label {Name="ServerAddressStatus",AutoSize=true,Dock=DockStyle.Fill,Margin=new Padding(0,2,0,0),UseMnemonic=false};Ui.Role(stateNote,"muted");
            Controls.Add(ipCaption,0,0);Controls.Add(serverIp,1,0);SetColumnSpan(serverIp,2);Controls.Add(addressCaption,0,1);Controls.Add(addresses,1,1);Controls.Add(copy,2,1);Controls.Add(configuration,0,2);SetColumnSpan(configuration,3);Controls.Add(stateNote,0,3);SetColumnSpan(stateNote,3);
        }
        private static List<string> Strings(Dictionary<string,object> data,string key){
            object raw;var result=new List<string>();if(!data.TryGetValue(key,out raw)||raw is string)return result;var values=raw as IEnumerable;if(values==null)return result;
            foreach(object value in values){string text=Convert.ToString(value).Trim();if(text.Length>0&&!result.Contains(text))result.Add(text);}return result;
        }
        private static bool UsableIp(string text,out IPAddress ip){return IPAddress.TryParse(text,out ip)&&!ip.Equals(IPAddress.Any)&&!ip.Equals(IPAddress.IPv6Any);}
        private static void KeyPart(StringBuilder key,string value){key.Append(value.Length).Append(':').Append(value);}
        private static string AddressKey(Dictionary<string,object> data,bool known,bool ready){
            var key=new StringBuilder(256);key.Append(known?'1':'0').Append(ready?'1':'0').Append(data.Count>0?'1':'0');
            foreach(string field in new[]{data.ContainsKey("ips")?"ips":"ipv4","endpoints","public_endpoints"}){
                object raw;var values=data.TryGetValue(field,out raw)&&!(raw is string)?raw as IEnumerable:null;
                key.Append('[');if(values!=null)foreach(object value in values)KeyPart(key,Convert.ToString(value).Trim());key.Append(']');
            }
            foreach(string field in new[]{"bind_ip","port","note","public_note"})KeyPart(key,Ui.Text(data,field));
            return key.ToString();
        }
        private static string Scope(IPAddress ip){
            if(IPAddress.IsLoopback(ip))return "仅服务器本机";
            byte[] bytes=ip.GetAddressBytes();if(bytes.Length==4&&(bytes[0]==10||(bytes[0]==172&&bytes[1]>=16&&bytes[1]<=31)||(bytes[0]==192&&bytes[1]==168)||(bytes[0]==169&&bytes[1]==254)))return "局域网";
            if(bytes.Length==16&&(ip.IsIPv6LinkLocal||(bytes[0]&0xfe)==0xfc))return "局域网";
            return "服务器直连";
        }
        internal void SetAddresses(Dictionary<string,object> server,bool known,bool ready){
            object raw;var data=server!=null&&server.TryGetValue("connection_addresses",out raw)?Ui.Map(raw):Ui.Obj();
            // Frequent CPU/memory samples reuse these addresses. Retain one small
            // content key, not pages or server snapshots, and leave the user's
            // selected endpoint intact when no displayed address facts changed.
            string addressKey=AddressKey(data,known,ready);if(addressKey==renderedAddressKey)return;
            var ips=Strings(data,data.ContainsKey("ips")?"ips":"ipv4");var displayIps=new List<string>();
            foreach(string value in ips){IPAddress ip;if(UsableIp(value,out ip))displayIps.Add(value+(IPAddress.IsLoopback(ip)?"（仅服务器本机）":""));}
            serverIp.Text=displayIps.Count>0?String.Join("  ·  ",displayIps):"后台尚未提供可用 IP 地址";
            var choices=new List<AddressChoice>();var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(string endpoint in Strings(data,"endpoints")){
                int colon=endpoint.LastIndexOf(':');if(colon<1)continue;string host=endpoint.Substring(0,colon).Trim('[',']');IPAddress ip;int port;
                if(!UsableIp(host,out ip)||!Int32.TryParse(endpoint.Substring(colon+1),out port)||port<1||port>65535||!seen.Add(endpoint))continue;
                choices.Add(new AddressChoice {Value=endpoint,Scope=Scope(ip)});
            }
            foreach(string endpoint in Strings(data,"public_endpoints"))if(seen.Add(endpoint))choices.Add(new AddressChoice {Value=endpoint,Scope="已配置公网 / 穿透"});
            var previous=addresses.SelectedItem as AddressChoice;string selectedValue=previous==null?"":previous.Value;
            bool changed=choices.Count==0?addresses.Items.Count!=1||!(addresses.Items[0] is string):addresses.Items.Count!=choices.Count;for(int i=0;!changed&&i<choices.Count;i++){var old=addresses.Items[i] as AddressChoice;changed=old==null||old.Value!=choices[i].Value||old.Scope!=choices[i].Scope;}
            if(changed){addresses.BeginUpdate();try{addresses.Items.Clear();foreach(var choice in choices)addresses.Items.Add(choice);if(choices.Count==0)addresses.Items.Add("暂无可用连接地址");int selected=choices.FindIndex(delegate(AddressChoice choice){return choice.Value==selectedValue;});addresses.SelectedIndex=selected>=0?selected:0;}finally{addresses.EndUpdate();}}
            addresses.Enabled=choices.Count>0;copy.Enabled=choices.Count>0;
            int preferredWidth=addresses.Width;foreach(var choice in choices)preferredWidth=Math.Max(preferredWidth,TextRenderer.MeasureText(choice.ToString(),addresses.Font).Width+32);addresses.DropDownWidth=Math.Min(Math.Max(1,preferredWidth),Screen.FromControl(this).WorkingArea.Width-40);
            string bind=Ui.Text(data,"bind_ip");string portText=Ui.Text(data,"port");
            string binding=bind.Length==0||bind=="0.0.0.0"||bind=="::"?"监听：所有本机地址":("监听："+bind);
            var notes=new List<string>();if(data.Count>0)notes.Add(binding+(portText.Length>0?" · 端口 "+portText:""));string note=Ui.Text(data,"note"),publicNote=Ui.Text(data,"public_note");if(note.Length>0)notes.Add(note);if(publicNote.Length>0)notes.Add(publicNote);else if(Strings(data,"public_endpoints").Count==0)notes.Add("未配置公网或穿透地址。");configuration.Text=String.Join("  ",notes);
            stateNote.Text=!known?"服务器状态未知；地址来自后台配置，尚未验证能否连接。":ready?"地址来自后台配置；能否连接还取决于网络、防火墙和隧道状态。":"服务器尚未就绪；当前显示配置地址，开服后再连接。";
            renderedAddressKey=addressKey;
        }
    }
    internal sealed class StatusProgress : Control {
        internal double? Value;
        internal StatusProgress(){Height=7;SetStyle(ControlStyles.OptimizedDoubleBuffer|ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint,true);}
        protected override void OnPaint(PaintEventArgs e){using(var background=new SolidBrush(Ui.Line))e.Graphics.FillRectangle(background,ClientRectangle);if(Value.HasValue)using(var fill=new SolidBrush(Ui.Primary))e.Graphics.FillRectangle(fill,0,0,(int)(Width*Math.Max(0,Math.Min(100,Value.Value))/100),Height);}
    }
    internal sealed partial class NativeMainForm {
        private readonly List<ResourceSample> dashboardCpuSamples=new List<ResourceSample>(),dashboardMemorySamples=new List<ResourceSample>();
        private string dashboardSampleServer="",dashboardLastSample="";
        private Control BuildDashboardPage(){
            var page=new Panel {Name="ServerOverview",Dock=DockStyle.Fill,AutoScroll=true};
            var summary=new TableLayoutPanel {Name="ServerStateSummary",Dock=DockStyle.Top,Height=178,ColumnCount=2,Padding=new Padding(18,12,18,12),Margin=new Padding(0)};summary.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,35));summary.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,65));Ui.Role(summary,"surface");
            var stateColumn=new Panel {Dock=DockStyle.Fill,Padding=new Padding(0,0,16,0)};
            var stateCaption=DashboardText("服务器现在",27,9F,false,"muted");var stateValue=DashboardText("正在读取",42,18F,true,"title");stateValue.Name="DashboardServerState";stateValue.Dock=DockStyle.Fill;var stateLamp=new ServerStatusLamp {Name="DashboardServerLamp",Dock=DockStyle.Left,Width=28};var liveState=new Panel {Dock=DockStyle.Top,Height=42};liveState.Controls.Add(stateValue);liveState.Controls.Add(stateLamp);var stateDetail=DashboardText("",64,9F,false,"muted");stateDetail.AutoEllipsis=true;stateColumn.Controls.Add(stateDetail);stateColumn.Controls.Add(liveState);stateColumn.Controls.Add(stateCaption);
            var taskColumn=new Panel {Dock=DockStyle.Fill,Padding=new Padding(8,0,0,0)};
            var taskCaption=DashboardText("当前正在执行",25,9F,false,"muted");var taskValue=DashboardText("等待状态",30,13F,true,"title");taskValue.Name="DashboardOperationState";var taskDetail=DashboardText("正在与后台同步…",40,9F,false,"muted");var taskTiming=DashboardText("",22,8F,false,"muted");var progress=new StatusProgress {Name="RealOperationProgress",Dock=DockStyle.Bottom};taskColumn.Controls.Add(progress);taskColumn.Controls.Add(taskTiming);taskColumn.Controls.Add(taskDetail);taskColumn.Controls.Add(taskValue);taskColumn.Controls.Add(taskCaption);summary.Controls.Add(stateColumn,0,0);summary.Controls.Add(taskColumn,1,0);
            var connectionAddresses=new ServerConnectionAddressPanel();
            var metrics=new TableLayoutPanel {Dock=DockStyle.Top,Height=140,ColumnCount=3,Padding=new Padding(0,12,0,0)};var metricValues=new Label[3];string[] captions={"在线玩家","服务器内存","CPU 使用率"},hints={"在线人数 / 最大人数","Minecraft 进程实际占用","Minecraft 进程采样"};for(int i=0;i<3;i++){metrics.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,33.333F));metrics.Controls.Add(DashboardMetric(captions[i],hints[i],out metricValues[i]),i,0);}Ui.Role(metrics,"canvas");
            var delay=new NumericUpDown {Name="RestartNoticeSeconds",Minimum=10,Maximum=3600,Value=60,Width=82,Margin=new Padding(0,4,9,4)};
            Func<string,Task> action=async delegate(string name){if(name=="start"){await StartServerWithRecoveryAsync();return;}if(name=="save"&&!CurrentPlatform.Allows("save_world"))throw new InvalidOperationException("当前平台没有世界保存操作。");if(name=="restart"&&!await EnsureServerEulaAsync())return;await Call("server.action",Ui.Obj("action",name));await RefreshCurrentPageAsync();};
            var start=Ui.Button("启动服务器",delegate{return action("start");});var restart=Ui.Button("通知后重启",async delegate{if(!await EnsureServerEulaAsync())return;await Call("countdown.start",Ui.Obj("seconds",(int)delay.Value,"restart_after",true));await RefreshCurrentPageAsync();SetStatus("已通知玩家；后台倒计时结束后重启。");});var cancel=Ui.Button("取消倒计时",async delegate{await Call("countdown.cancel");await RefreshCurrentPageAsync();});var stop=Ui.Button("正常停服…",async delegate{bool starting=serverPresentation.Starting;if(Ui.Confirm(this,starting?"确定停止当前服务器的启动过程？":"确定正常关闭当前服务器？在线玩家会断开连接。",starting?"停止启动":"正常停服"))await action("stop");});Ui.Role(stop,"danger");var save=Ui.Button("保存世界",delegate{return action("save");});var refresh=Ui.Button("刷新状态",RefreshCurrentPageAsync);Ui.Role(restart,"primary");
            foreach(var guarded in new[]{start,restart,cancel,stop,save}){Button button=guarded;button.EnabledChanged+=delegate{if(!button.Enabled)return;var state=serverPresentation;bool available=state.Known&&state.OperationKnown&&!state.Busy&&!state.Countdown;bool allowed=button==start?available&&!state.Running&&!state.Starting:button==cancel?state.Known&&state.Countdown&&state.CanCancel:button==stop?(available&&state.Running)||(state.Known&&state.CanStopStarting&&!state.StartupStopRequested):available&&state.Ready;if(!allowed)button.Enabled=false;};}
            var primaryActions=Ui.Toolbar(start,restart,new Label {Text="提前通知（秒）",AutoSize=true,Margin=new Padding(4,10,5,0)},delay,cancel);primaryActions.Padding=new Padding(0,10,0,0);
            var details=Ui.Button("查看完整详情",delegate{ShowServerOperationDetails();return Task.CompletedTask;});details.Name="ServerOperationDetails";
            var secondaryActions=Ui.Toolbar(save,stop,refresh,details,DiagnosticsButton());secondaryActions.Padding=new Padding(0,0,0,6);
            var actionArea=new OpsStackPanel {Name="OverviewActionGroups",Dock=DockStyle.Top,Margin=new Padding(0),Padding=new Padding(0,0,0,6)};primaryActions.Dock=DockStyle.None;secondaryActions.Dock=DockStyle.None;actionArea.Controls.Add(primaryActions);actionArea.Controls.Add(secondaryActions);
            var trends=new TableLayoutPanel {Dock=DockStyle.Top,Height=194,ColumnCount=2,Padding=new Padding(0,0,0,12)};trends.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,50));trends.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,50));var cpu=new ResourceTrend("CPU 使用趋势"," %") {Name="DashboardCpuTrend",Dock=DockStyle.Fill,Margin=new Padding(0,0,8,0)};var memory=new ResourceTrend("内存使用趋势"," MB") {Name="DashboardMemoryTrend",Dock=DockStyle.Fill,Margin=new Padding(4,0,0,0)};trends.Controls.Add(cpu,0,0);trends.Controls.Add(memory,1,0);
            var routes=new TableLayoutPanel {Dock=DockStyle.Top,Height=90,ColumnCount=3};routes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,33.333F));routes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,33.333F));routes.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,33.333F));routes.Controls.Add(DashboardRoute("控制台与日志","查看输出，发送服务器命令","console"),0,0);routes.Controls.Add(DashboardRoute("备份与恢复","创建备份，管理历史存档","backups"),1,0);routes.Controls.Add(DashboardRoute("服务器设置","调整地址、端口与运行参数","settings"),2,0);
            var note=DashboardText("状态与趋势来自后台实际采样。收起到托盘会暂停界面刷新；服务器继续运行。",36,8F,false,"muted");note.Padding=new Padding(0,9,0,0);
            page.Controls.Add(note);page.Controls.Add(routes);page.Controls.Add(trends);page.Controls.Add(actionArea);page.Controls.Add(metrics);page.Controls.Add(connectionAddresses);page.Controls.Add(summary);
            dashboardStateChanged=delegate(ServerPresentation state){
                if(page.IsDisposed)return;stateValue.Text=state.State;stateLamp.SetState(state.Indicator,state.State);Ui.Role(stateValue,"title");taskValue.Text=state.Operation;Ui.Role(taskValue,state.OperationFailed?"danger":state.Busy||state.Countdown?"warning":"title");taskDetail.Text=state.Detail;taskTiming.Text=(state.Stage.Length>0?state.Stage+" · ":"")+(state.Percent.HasValue?state.Percent.Value.ToString("0.0")+"% · ":"")+state.Timing;progress.Value=state.Percent;progress.Invalidate();
                connectionAddresses.SetAddresses(state.Server,state.Known,state.Ready);
                stateDetail.Text=!state.Known?(state.ServerDetail.Length>0?state.ServerDetail:state.Detail):"运行时长："+ServerPresentation.Duration(Ui.Num(state.Server,"uptime_seconds"));statusTip.SetToolTip(stateValue,(state.ServerDetail.Length>0?state.ServerDetail+"\r\n":"")+(state.SampleTime.Length>0?"后台采样："+state.SampleTime:state.Detail));statusTip.SetToolTip(taskDetail,state.Detail);statusTip.SetToolTip(taskTiming,taskTiming.Text);
                bool validMetrics=!state.Server.ContainsKey("metrics_valid")||Ui.Bool(state.Server,"metrics_valid");metricValues[0].Text=state.Known?Ui.Text(state.Server,"online_count","—")+" / "+Ui.Text(state.Server,"max_players","—"):"—";metricValues[1].Text=state.Known&&validMetrics&&state.Server.ContainsKey("memory_mb")?Ui.Num(state.Server,"memory_mb").ToString("0.0")+" MB":"—";metricValues[2].Text=state.Known&&validMetrics&&state.Server.ContainsKey("cpu_percent")?Ui.Num(state.Server,"cpu_percent").ToString("0.0")+" %":"—";
                bool available=state.Known&&state.OperationKnown&&!state.Busy&&!state.Countdown;start.Enabled=available&&!state.Running&&!state.Starting;restart.Enabled=available&&state.Ready;stop.Text=state.Starting?state.StartupStopRequested?"正在停止启动…":"停止启动…":"正常停服…";stop.Enabled=(available&&state.Running)||(state.Known&&state.CanStopStarting&&!state.StartupStopRequested);save.Enabled=available&&state.Ready&&CurrentPlatform.Allows("save_world");statusTip.SetToolTip(save,CurrentPlatform.Allows("save_world")?"保存当前世界":"当前平台没有世界保存操作。");cancel.Enabled=state.Known&&state.Countdown&&state.CanCancel;delay.Enabled=available&&state.Ready;
                if(dashboardSampleServer!=selectedServerId){dashboardSampleServer=selectedServerId;dashboardCpuSamples.Clear();dashboardMemorySamples.Clear();dashboardLastSample="";}
                string stamp=Ui.Text(state.Server,"metrics_updated_at",Ui.Text(state.Server,"updated_at"));
                if(state.Known&&validMetrics&&state.Server.ContainsKey("cpu_percent")&&state.Server.ContainsKey("memory_mb")&&(stamp.Length==0||stamp!=dashboardLastSample)){
                    double cpuValue,memoryValue;
                    if(ResourceSample.TryValue(state.Server["cpu_percent"],out cpuValue)&&ResourceSample.TryValue(state.Server["memory_mb"],out memoryValue)){
                        dashboardLastSample=stamp;DateTimeOffset received=DateTimeOffset.Now;
                        ResourceSample.Append(dashboardCpuSamples,new ResourceSample(cpuValue,stamp,received));ResourceSample.Append(dashboardMemorySamples,new ResourceSample(memoryValue,stamp,received));
                    }
                }
                cpu.SetSamples(dashboardCpuSamples);memory.SetSamples(dashboardMemorySamples);
            };
            dashboardStateChanged(serverPresentation);pageRefresh=async delegate{await Call("status");if(!page.IsDisposed)SetStatus("状态已同步 · "+DateTime.Now.ToString("HH:mm:ss")+" · "+("本机连接"));};return page;
        }
        private void ShowServerOperationDetails(){
            var state=serverPresentation;
            string text="服务器："+state.State+"\r\n当前操作："+state.Operation+"\r\n"+state.Detail;
            if(state.ServerDetail.Length>0&&state.ServerDetail!=state.Detail)text+="\r\n\r\n"+state.ServerDetail;
            if(state.Timing.Length>0)text+="\r\n\r\n"+state.Timing;
            if(state.SampleTime.Length>0)text+="\r\n后台采样："+state.SampleTime;
            using(var dialog=new Form {Text="服务器与操作详情",ClientSize=new Size(720,400),MinimumSize=new Size(480,280),StartPosition=FormStartPosition.CenterParent,ShowInTaskbar=false,Font=Ui.BodyFont}){
                var output=new RichTextBox {Name="ServerOperationDetailsText",Text=text,Dock=DockStyle.Fill,ReadOnly=true,WordWrap=true,DetectUrls=false,BorderStyle=BorderStyle.None,ScrollBars=RichTextBoxScrollBars.Vertical,Font=Ui.BodyFont};Ui.Role(output,"console");
                var body=new Panel {Dock=DockStyle.Fill,Padding=new Padding(16)};body.Controls.Add(output);
                var close=Ui.Button("关闭",delegate{dialog.Close();return Task.CompletedTask;});
                var footer=Ui.Toolbar(new Label {Text="可选择文字并按 Ctrl+C 复制；完整启动输出见控制台。",AutoSize=true,Margin=new Padding(10,10,12,0)},close);footer.Dock=DockStyle.Bottom;
                dialog.Controls.Add(body);dialog.Controls.Add(footer);dialog.CancelButton=close;Ui.ApplyTheme(dialog);dialog.ShowDialog(this);
            }
        }
        private static Label DashboardText(string text,int height,float size,bool bold,string role){var label=new Label {Text=text,Dock=DockStyle.Top,AutoEllipsis=true,Font=new Font("Microsoft YaHei UI",size,bold?FontStyle.Bold:FontStyle.Regular),UseMnemonic=false};label.Height=Math.Max(height,label.Font.Height+8);Ui.Role(label,role);return label;}
        private Control DashboardMetric(string caption,string hint,out Label value){var card=new Panel {Dock=DockStyle.Fill,Padding=new Padding(16,9,12,8),Margin=new Padding(0,0,10,10)};Ui.Role(card,"surface");var label=DashboardText(caption,24,9F,false,"muted");var help=DashboardText(hint,22,8F,false,"muted");help.Dock=DockStyle.Bottom;value=DashboardText("—",42,17F,true,"title");value.Dock=DockStyle.Fill;card.Controls.Add(value);card.Controls.Add(help);card.Controls.Add(label);return card;}

        private Control DashboardRoute(string title,string description,string key) {
            bool supported=CurrentPlatform.PageAllowed(key);var button=Ui.Button(title+"\r\n"+description,async delegate{if(supported)await NavigateAsync(key);});button.Enabled=supported;button.Dock=DockStyle.Fill;button.TextAlign=ContentAlignment.MiddleLeft;button.AutoSize=false;button.Margin=new Padding(0,0,10,8);button.Padding=new Padding(13,6,8,6);Ui.Role(button,"secondary");return button;
        }


    }
}
