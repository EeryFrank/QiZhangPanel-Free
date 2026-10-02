// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using QiZhang.Shared;

namespace QiZhang.NativePanel {
    internal static class NativeProgram {
        internal static string DataRoot,BundleRoot;
        internal static readonly JavaScriptSerializer Json=new JavaScriptSerializer {MaxJsonLength=64*1024*1024};
        private static Dictionary<string,string> arguments;
        internal static EventWaitHandle ShowEvent;
        [DllImport("user32.dll")]private static extern bool SetProcessDPIAware();
        [STAThread]private static int Main(string[] args) {
            arguments=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
            for(int i=0;i<args.Length;i++)if(args[i].StartsWith("--")){string key=args[i].Substring(2);arguments[key]=i+1<args.Length&&!args[i+1].StartsWith("--")?args[++i]:"true";}
            BundleRoot=Path.GetFullPath(Get("bundle-root",AppDomain.CurrentDomain.BaseDirectory));
            string defaultData=File.Exists(Path.Combine(BundleRoot,"portable.flag"))?Path.Combine(BundleRoot,"data"):Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"QiZhangPanelFree");
            DataRoot=Path.GetFullPath(Get("data-root",defaultData));
            try {
                Directory.CreateDirectory(DataRoot);string identity;
                using(var hash=SHA256.Create())identity=BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(DataRoot.ToUpperInvariant()))).Replace("-","").Substring(0,24);
                bool first;
                using(var mutex=new Mutex(true,"Local\\QiZhangNativePanel-"+identity,out first))
                using(ShowEvent=new EventWaitHandle(false,EventResetMode.AutoReset,"Local\\QiZhangNativeShow-"+identity)) {
                    if(!first){ShowEvent.Set();return 0;}
                    if(!Has("smoke-test-dir")&&!Has("bundle-root"))QiZhang.Shared.InstallationLocation.Remember(BundleRoot,System.Reflection.Assembly.GetExecutingAssembly().GetName().Version.ToString());
                    SetProcessDPIAware();Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
                    var appearance=NativeLoginPreferences.Load();AppTheme.Initialize(Get("smoke-theme",appearance.ThemeMode),Get("smoke-accent",appearance.ThemeAccent));VisualEffects.Configure(appearance.PerformanceMode,appearance.AnimationsEnabled,appearance.HardwareAcceleration);
                    Application.ThreadException+=delegate(object sender,ThreadExceptionEventArgs e){Log(e.Exception);Ui.Message(null,e.Exception.Message,"七章控制面板",MessageBoxIcon.Warning);};
                    try{Application.Run(new NativeMainForm());}finally{AppTheme.Shutdown();}mutex.ReleaseMutex();
                }
                return 0;
            }catch(Exception ex){Log(ex);Ui.Message(null,"面板启动失败：\r\n"+ex.Message,"七章控制面板",MessageBoxIcon.Error);return 1;}
        }
        internal static bool Has(string key){return arguments.ContainsKey(key);}
        internal static void Set(string key,string value){arguments[key]=value;}
        internal static string Get(string key,string fallback=""){string value;return arguments.TryGetValue(key,out value)?value:fallback;}


        internal static string Quote(string value){var result=new StringBuilder("\"");int slashes=0;foreach(char c in value){if(c=='\\'){slashes++;continue;}if(c=='"'){result.Append('\\',slashes*2+1);result.Append(c);slashes=0;continue;}result.Append('\\',slashes);slashes=0;result.Append(c);}result.Append('\\',slashes*2);result.Append('"');return result.ToString();}
        internal static void Log(Exception ex){try{File.AppendAllText(Path.Combine(DataRoot,"native-ui.log"),DateTime.Now.ToString("s")+" "+ex.Message+Environment.NewLine,Encoding.UTF8);}catch{}}
    }

    internal sealed class NativeLoginPreferences {
        internal bool RememberUsernames,AutomaticLogin,CloseToTray=true,MinimizeToTray=true,RememberWindow=true,WindowMaximized,AnimationsEnabled=true,HardwareAcceleration=true;
        internal int RefreshSeconds=3,WindowX,WindowY,WindowWidth,WindowHeight;
        internal bool HighPerformanceMonitoring;
        internal int ConsoleRefreshMilliseconds=1000,PerformanceRefreshMilliseconds=1000;
        internal List<string> Usernames=new List<string>();
        internal string LastUsername="",ProtectedCredential="",ThemeMode="system",ThemeAccent="green",PerformanceMode="economy";
        private static readonly byte[] Entropy=Encoding.UTF8.GetBytes("QiZhangControlPanel-AutoLogin-v1");
        internal static NativeLoginPreferences Load(){
            var prefs=new NativeLoginPreferences();try{string file=Path.Combine(NativeProgram.DataRoot,"native-ui-settings.json");if(!File.Exists(file))return prefs;var data=NativeProgram.Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(file,Encoding.UTF8));prefs.ThemeMode=ValidTheme(Ui.Text(data,"theme_mode","system"));prefs.ThemeAccent=ValidAccent(Ui.Text(data,"theme_accent","green"));prefs.PerformanceMode=ValidPerformanceMode(Ui.Text(data,"performance_mode","economy"));prefs.AnimationsEnabled=!data.ContainsKey("animations_enabled")||Ui.Bool(data,"animations_enabled");prefs.HardwareAcceleration=!data.ContainsKey("hardware_acceleration")||Ui.Bool(data,"hardware_acceleration");prefs.RememberUsernames=Ui.Bool(data,"remember_usernames");prefs.AutomaticLogin=prefs.RememberUsernames&&Ui.Bool(data,"automatic_login");prefs.CloseToTray=!data.ContainsKey("close_to_tray")||Ui.Bool(data,"close_to_tray");prefs.MinimizeToTray=!data.ContainsKey("minimize_to_tray")||Ui.Bool(data,"minimize_to_tray");prefs.RememberWindow=!data.ContainsKey("remember_window")||Ui.Bool(data,"remember_window");prefs.HighPerformanceMonitoring=Ui.Bool(data,"high_performance_monitoring");prefs.ConsoleRefreshMilliseconds=data.ContainsKey("console_refresh_ms")?Math.Max(1,Math.Min(60000,(int)Ui.Num(data,"console_refresh_ms"))):1000;prefs.PerformanceRefreshMilliseconds=data.ContainsKey("performance_refresh_ms")?Math.Max(1,Math.Min(60000,(int)Ui.Num(data,"performance_refresh_ms"))):1000;prefs.RefreshSeconds=data.ContainsKey("refresh_seconds")?Math.Max(1,Math.Min(30,(int)Ui.Num(data,"refresh_seconds"))):3;prefs.WindowX=(int)Ui.Num(data,"window_x");prefs.WindowY=(int)Ui.Num(data,"window_y");prefs.WindowWidth=(int)Ui.Num(data,"window_width");prefs.WindowHeight=(int)Ui.Num(data,"window_height");prefs.WindowMaximized=Ui.Bool(data,"window_maximized");prefs.LastUsername=Ui.Text(data,"last_username");prefs.ProtectedCredential=Ui.Text(data,"protected_credential");object names;if(data.TryGetValue("usernames",out names)){var list=names as System.Collections.IEnumerable;if(list!=null)foreach(object value in list){string name=Convert.ToString(value);if(!string.IsNullOrWhiteSpace(name)&&!prefs.Usernames.Contains(name))prefs.Usernames.Add(name);}}if(!prefs.RememberUsernames){prefs.Usernames.Clear();prefs.LastUsername="";prefs.ProtectedCredential="";}}catch{}return prefs;
        }
        internal void Save(){
            string file=Path.Combine(NativeProgram.DataRoot,"native-ui-settings.json"),temp=file+".tmp";
            var data=Ui.Obj("high_performance_monitoring",HighPerformanceMonitoring,"console_refresh_ms",Math.Max(1,Math.Min(60000,ConsoleRefreshMilliseconds)),"performance_refresh_ms",Math.Max(1,Math.Min(60000,PerformanceRefreshMilliseconds)),"performance_mode",ValidPerformanceMode(PerformanceMode),"animations_enabled",AnimationsEnabled,"hardware_acceleration",HardwareAcceleration,"theme_mode",ValidTheme(ThemeMode),"theme_accent",ValidAccent(ThemeAccent),"remember_usernames",RememberUsernames,"automatic_login",RememberUsernames&&AutomaticLogin,"close_to_tray",CloseToTray,"minimize_to_tray",MinimizeToTray,"remember_window",RememberWindow,"refresh_seconds",RefreshSeconds,"window_x",WindowX,"window_y",WindowY,"window_width",WindowWidth,"window_height",WindowHeight,"window_maximized",WindowMaximized,"last_username",RememberUsernames?LastUsername:"","usernames",RememberUsernames?Usernames:new List<string>(),"protected_credential",RememberUsernames&&AutomaticLogin?ProtectedCredential:"");
            File.WriteAllText(temp,NativeProgram.Json.Serialize(data),new UTF8Encoding(false));if(File.Exists(file))File.Replace(temp,file,null);else File.Move(temp,file);
        }
        internal void Remember(string username,string password,bool remember,bool automatic){
            
            RememberUsernames=remember;AutomaticLogin=remember&&automatic;
            if(remember){LastUsername=username;Usernames.Remove(username);Usernames.Insert(0,username);if(Usernames.Count>20)Usernames.RemoveRange(20,Usernames.Count-20);}else{LastUsername="";Usernames.Clear();}
            ProtectedCredential=AutomaticLogin?Convert.ToBase64String(ProtectedData.Protect(Encoding.UTF8.GetBytes(NativeProgram.Json.Serialize(Ui.Obj("username",username,"password",password,"scope","local"))),Entropy,DataProtectionScope.CurrentUser)):"";Save();
        }
        internal void ClearAutomatic(){AutomaticLogin=false;ProtectedCredential="";Save();}
        internal static string ValidTheme(string value){return value=="light"||value=="dark"?value:"system";}
        internal static string ValidAccent(string value){return Array.IndexOf(new[]{"green","blue","violet","rose","amber","teal","slate"},value)>=0?value:"green";}
        internal static string ValidPerformanceMode(string value){return value=="fancy"?"fancy":"economy";}
        internal int EffectiveRefreshMilliseconds {get{return Math.Max(ValidPerformanceMode(PerformanceMode)=="economy"?10:1,Math.Max(1,Math.Min(30,RefreshSeconds)))*1000;}}
        internal Dictionary<string,string> ReadAutomatic(){if(!RememberUsernames||!AutomaticLogin||ProtectedCredential.Length==0)return null;try{var result=NativeProgram.Json.Deserialize<Dictionary<string,string>>(Encoding.UTF8.GetString(ProtectedData.Unprotect(Convert.FromBase64String(ProtectedCredential),Entropy,DataProtectionScope.CurrentUser)));string storedScope;if(!result.TryGetValue("scope",out storedScope))storedScope="local";if(storedScope!="local"){result.Clear();return null;}return result;}catch{return null;}}
    }

    internal sealed class RpcClient : IDisposable {
        private readonly SemaphoreSlim gate=new SemaphoreSlim(1,1);
        private readonly Process process;
        private readonly StreamWriter input;

        private long sequence;
        private bool disposed;
        internal int ProcessId {get{return process.Id;}}
        
        internal RpcClient() {
            string python=Path.Combine(NativeProgram.BundleRoot,"runtime","python.exe");
            string host=Path.Combine(NativeProgram.BundleRoot,"native-host.py");
            if(!File.Exists(python)||!File.Exists(host))throw new FileNotFoundException("程序文件不完整，请解压完整压缩包后打开 EXE。");
            string args=NativeProgram.Quote(host)+" --data-root "+NativeProgram.Quote(NativeProgram.DataRoot);
            if(NativeProgram.Has("autostart"))args+=" --autostart";
            var start=new ProcessStartInfo(python,args){UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,WorkingDirectory=NativeProgram.BundleRoot,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
            start.EnvironmentVariables["PYTHONUTF8"]="1";start.EnvironmentVariables["PYTHONUNBUFFERED"]="1";
            process=Process.Start(start);input=new StreamWriter(process.StandardInput.BaseStream,new UTF8Encoding(false)){AutoFlush=true};
            process.ErrorDataReceived+=delegate(object sender,DataReceivedEventArgs e){if(e.Data!=null)try{File.AppendAllText(Path.Combine(NativeProgram.DataRoot,"native-host.stderr.log"),e.Data+Environment.NewLine,Encoding.UTF8);}catch{}};
            process.BeginErrorReadLine();
        }
        internal Task<Dictionary<string,object>> Call(string action,Dictionary<string,object> payload,string serverId) {
            return CallRead(action,payload,serverId,CancellationToken.None);
        }
        internal async Task<Dictionary<string,object>> CallRead(string action,Dictionary<string,object> payload,string serverId,CancellationToken cancellation) {
            await gate.WaitAsync(cancellation);
            try {
                cancellation.ThrowIfCancellationRequested();
                if(disposed||process.HasExited)throw new IOException("管理后台已关闭，请退出后重新打开面板。");
                long id=++sequence;var request=Ui.Obj("id",id,"action",action,"server_id",serverId,"payload",payload??Ui.Obj());
                await input.WriteLineAsync(NativeProgram.Json.Serialize(request));
                string line=await process.StandardOutput.ReadLineAsync();
                if(line==null)throw new IOException("管理后台连接已结束，请查看运行目录中的日志。");
                var response=NativeProgram.Json.Deserialize<Dictionary<string,object>>(line);
                if(Ui.Num(response,"id")!=id)throw new IOException("后台响应顺序异常，请重新打开面板。");
                // A request already written must be drained to preserve framing.
                // Page cancellation discards its result and cancels queued reads.
                cancellation.ThrowIfCancellationRequested();
                if(!Ui.Bool(response,"ok"))throw new InvalidOperationException(Ui.Text(response,"error","操作未完成。"));
                object data;return response.TryGetValue("data",out data)?Ui.Map(data):Ui.Obj();
            }finally{gate.Release();}
        }
        internal bool HasExited {get{try{return process.HasExited;}catch{return true;}}}
        internal async Task<bool> WaitForCleanExitAsync(int milliseconds) {
            if (disposed) return false;
            try {
                input.Close();
                return await Task.Run(delegate { return process.WaitForExit(milliseconds) && process.ExitCode == 0; });
            } catch { return false; }
        }
        public void Dispose(){if(disposed)return;disposed=true;try{input.Close();if(!process.HasExited)process.WaitForExit(3000);}catch{}process.Dispose();}
    }

    internal sealed class NativeWindowButton : Button {
        private readonly string kind;
        internal NativeWindowButton(string glyph){kind=glyph;Text="";FlatStyle=FlatStyle.Flat;FlatAppearance.BorderSize=1;FlatAppearance.BorderColor=Ui.Line;BackColor=Ui.Surface;ForeColor=Ui.Ink;SetStyle(ControlStyles.OptimizedDoubleBuffer,true);}
        protected override void OnPaint(PaintEventArgs e){base.OnPaint(e);e.Graphics.SmoothingMode=System.Drawing.Drawing2D.SmoothingMode.AntiAlias;float x=Width/2f,y=Height/2f;using(var pen=new Pen(Enabled?ForeColor:Ui.Muted,1.5f)){
            if(kind=="×"){e.Graphics.DrawLine(pen,x-5,y-5,x+5,y+5);e.Graphics.DrawLine(pen,x+5,y-5,x-5,y+5);}
            else if(kind=="—")e.Graphics.DrawLine(pen,x-6,y,x+6,y);
            else if(kind=="□")e.Graphics.DrawRectangle(pen,x-5,y-5,10,10);
            else if(kind=="⛶"){for(int i=0;i<4;i++){float dx=i%2==0?-1:1,dy=i<2?-1:1;e.Graphics.DrawLine(pen,x+dx*3,y+dy*6,x+dx*6,y+dy*6);e.Graphics.DrawLine(pen,x+dx*6,y+dy*6,x+dx*6,y+dy*3);}}
            else {e.Graphics.DrawEllipse(pen,x-5,y-5,10,10);e.Graphics.DrawEllipse(pen,x-1.6f,y-1.6f,3.2f,3.2f);for(int i=0;i<8;i++){double a=i*Math.PI/4;e.Graphics.DrawLine(pen,x+(float)Math.Cos(a)*5,y+(float)Math.Sin(a)*5,x+(float)Math.Cos(a)*8,y+(float)Math.Sin(a)*8);}}
        }}
    }

    internal sealed partial class NativeMainForm : Form {
        private RpcClient rpc;
        private string selectedServerId="";
        private readonly Panel content;
        private readonly Panel sidebar;
        private readonly Button backToSelection;
        private readonly NativeLoginPreferences loginPreferences;
        private Func<Task> pageRefresh;
        private readonly Label statusLabel,pageTitle,accountLabel;
        private readonly ToolTip statusTip=new ToolTip {AutoPopDelay=20000};
        
        private Dictionary<string,object> currentAccount=Ui.Obj();
        private readonly ComboBox serversCombo;
        private readonly NotifyIcon tray;
        private readonly System.Windows.Forms.Timer poll;
        private RegisteredWaitHandle showRegistration;
        private bool authenticated,exiting,refreshing,changingServer,smokeRunning,forceLoginOnce;
        private bool inServerManagement,lastLoginWasAutomatic,archiveDropBusy,fullScreen,settingsFlowVerified;
        private long workspaceNavigationVersion;
        private Rectangle normalWindowBounds;
        private FormWindowState previousWindowState,lastNonMinimizedState=FormWindowState.Normal;
        private FormBorderStyle previousBorderStyle;
        private Task activePageRefresh;
        private string currentPage="dashboard";
        private readonly Dictionary<string,Button> navigation=new Dictionary<string,Button>();
        private readonly Dictionary<string,string> titles=new Dictionary<string,string> {
            {"dashboard","服务器总览"},{"console","控制台"},{"settings","服务器设置"},{"backups","备份管理"},{"servers","服务器实例"},{"account","账号与密码"}
        };
        internal NativeMainForm() {
            loginPreferences=NativeLoginPreferences.Load();
            Text=ProductEdition.Title;Width=1380;Height=900;MinimumSize=new Size(1040,700);StartPosition=FormStartPosition.CenterScreen;Font=new Font("Microsoft YaHei UI",9F);AutoScaleMode=AutoScaleMode.Dpi;BackColor=Ui.Canvas;Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath)??SystemIcons.Application;
            RestoreWindowPlacement();lastNonMinimizedState=WindowState;
            sidebar=new Panel {Name="WorkspaceNavigation",Dock=DockStyle.Left,Width=240,BackColor=Ui.Sidebar,Padding=new Padding(12),Visible=false};
            Ui.Role(sidebar,"sidebar");
            var brand=new Panel {Dock=DockStyle.Top,Height=66,Padding=new Padding(9,4,0,0)};
            brand.Controls.Add(new Label {Name="NavigationSubtitle",Text=ProductEdition.Label+" · 服务器管理",Dock=DockStyle.Bottom,Height=26,Font=new Font("Microsoft YaHei UI",9F)});
            brand.Controls.Add(new Label {Text="七章控制面板",Dock=DockStyle.Top,Height=32,Font=new Font("Microsoft YaHei UI",12F,FontStyle.Bold)});
            Ui.Role(brand,"sidebar");foreach(Control label in brand.Controls)Ui.Role(label,"brand");
            var navList=BuildNavigation();sidebar.Controls.Add(navList);sidebar.Controls.Add(brand);
            var header=new TableLayoutPanel {Name="WorkspaceHeader",Dock=DockStyle.Top,Height=98,ColumnCount=3,RowCount=2,Padding=new Padding(22,8,20,8),BackColor=Ui.Surface};header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,220));header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,186));header.RowStyles.Add(new RowStyle(SizeType.Absolute,40));header.RowStyles.Add(new RowStyle(SizeType.Percent,100));
            pageTitle=new Label {Text="请登录",Dock=DockStyle.Fill,Font=new Font("Microsoft YaHei UI",17F,FontStyle.Bold),TextAlign=ContentAlignment.MiddleLeft,ForeColor=Ui.Ink,AutoEllipsis=true};
            serversCombo=new ComboBox {Name="CurrentServer",DropDownStyle=ComboBoxStyle.DropDownList,Dock=DockStyle.Fill,Margin=new Padding(10,7,12,0)};
            serversCombo.SelectedIndexChanged+=async delegate{if(changingServer||!authenticated||!inServerManagement)return;var selected=serversCombo.SelectedItem as ServerChoice;if(selected!=null){long version=++workspaceNavigationVersion;RestoreDetachedConsole(false);selectedServerId=selected.Id;ResetServerState("正在连接");await Safe(async delegate{await Call("servers.switch",Ui.Obj("server_id",selected.Id));if(WorkspaceNavigationCurrent(version)&&inServerManagement)await NavigateAsync(currentPage);});}};
            accountLabel=new Label {Text="尚未登录",Dock=DockStyle.Fill,AutoEllipsis=true,UseMnemonic=false,TextAlign=ContentAlignment.MiddleRight,ForeColor=Ui.Muted,Margin=new Padding(0,0,0,0)};
            backToSelection=Ui.Button("← 返回列表",ShowServerSelectionAsync);backToSelection.Visible=false;backToSelection.AutoSize=false;backToSelection.Size=new Size(180,34);backToSelection.Margin=new Padding(0);backToSelection.MinimumSize=new Size(0,34);
            logoutButton=Ui.Button("退出账号",SwitchAccountAsync);logoutButton.Visible=false;logoutButton.AutoSize=false;logoutButton.Size=new Size(180,34);logoutButton.MinimumSize=new Size(0,34);logoutButton.Margin=new Padding(0);
            var accountActions=new Panel {Dock=DockStyle.Fill};backToSelection.Dock=DockStyle.Fill;logoutButton.Dock=DockStyle.Fill;accountActions.Controls.Add(backToSelection);accountActions.Controls.Add(logoutButton);
            serverStateStrip=new Panel {Name="ServerStatusStrip",Dock=DockStyle.Fill,Visible=false,Margin=new Padding(0,4,12,0)};serverStateLabel=new Label {Name="PersistentServerState",Dock=DockStyle.Fill,Text="服务器  ·  正在连接",TextAlign=ContentAlignment.MiddleLeft,AutoEllipsis=true};serverStateLamp=new ServerStatusLamp {Name="PersistentServerLamp",Dock=DockStyle.Left,Width=26};var liveState=new Panel {Name="PersistentServerStateGroup",Dock=DockStyle.Left,Width=220};liveState.Controls.Add(serverStateLabel);liveState.Controls.Add(serverStateLamp);operationStateLabel=new Label {Name="PersistentOperationState",Dock=DockStyle.Fill,Text="当前操作  ·  等待状态",TextAlign=ContentAlignment.MiddleLeft,AutoEllipsis=true};serverStateStrip.Controls.Add(operationStateLabel);serverStateStrip.Controls.Add(liveState);
            header.Controls.Add(pageTitle,0,0);header.Controls.Add(serversCombo,1,0);header.Controls.Add(accountLabel,2,0);header.Controls.Add(serverStateStrip,0,1);header.SetColumnSpan(serverStateStrip,2);header.Controls.Add(accountActions,2,1);Ui.Role(header,"surface");Ui.Role(accountActions,"surface");Ui.Role(serverStateStrip,"surface");Ui.Role(pageTitle,"title");Ui.Role(accountLabel,"muted");Ui.ApplyTheme(header);
            statusLabel=new Label {Dock=DockStyle.Fill,Padding=new Padding(18,6,0,0),ForeColor=Ui.Muted,BackColor=Ui.Surface,AutoEllipsis=true,Text="正在启动本机管理后台…"};
            var footer=new Panel {Dock=DockStyle.Bottom,Height=31,BackColor=Ui.Surface};var ownership=OwnershipLink();ownership.Dock=DockStyle.Right;ownership.Width=225;footer.Controls.Add(statusLabel);footer.Controls.Add(ownership);footer.Layout+=delegate{int needed=TextRenderer.MeasureText(ownership.Text,ownership.Font).Width+ownership.Padding.Horizontal+6;if(ownership.Width!=needed)ownership.Width=needed;};
            Ui.Role(footer,"surface");Ui.Role(statusLabel,"muted");
            content=new Panel {Dock=DockStyle.Fill,Padding=new Padding(22,18,22,18),AutoScroll=true};
            AttachArchiveDrop(this);AttachArchiveDrop(content);
            var body=new Panel {Dock=DockStyle.Fill};body.Controls.Add(content);body.Controls.Add(header);body.Controls.Add(footer);Controls.Add(body);Controls.Add(sidebar);
            var menu=new ContextMenuStrip();menu.Items.Add("打开面板",null,delegate{RestoreWindow();});menu.Items.Add("© 2026 EeryFrank 所有",null,delegate{Process.Start(new ProcessStartInfo("https://github.com/EeryFrank"){UseShellExecute=true});});menu.Items.Add("退出面板（安全关服）",null,async delegate{await Safe(ExitAsync);});
            tray=new NotifyIcon {Visible=true,Icon=Icon,Text="七章控制面板",ContextMenuStrip=menu};tray.DoubleClick+=delegate{RestoreWindow();};
            Ui.ApplyTheme(menu);
            poll=new System.Windows.Forms.Timer {Interval=loginPreferences.EffectiveRefreshMilliseconds};poll.Tick+=async delegate{if(!MonitoringUiVisible||!authenticated||refreshing||(!inServerManagement&&pageRefresh==null))return;await PollUiAsync();};
            FormClosing+=async delegate(object sender,FormClosingEventArgs e){if(!exiting&&e.CloseReason==CloseReason.UserClosing){e.Cancel=true;if(loginPreferences.CloseToTray)HideToTray();else await Safe(ExitAsync);}};
            Resize+=delegate{if(WindowState==FormWindowState.Minimized&&!exiting){if(!DetachedConsoleVisible)poll.Stop();VisualEffects.Suspend(this);if(loginPreferences.MinimizeToTray)HideToTray();}else if(WindowState!=FormWindowState.Minimized){lastNonMinimizedState=WindowState;if(authenticated&&MonitoringUiVisible&&!exiting)poll.Start();}};
            KeyPreview=true;KeyDown+=delegate(object sender,KeyEventArgs e){if(e.KeyCode==Keys.F11||(e.KeyCode==Keys.Escape&&fullScreen)){ToggleFullScreen();e.Handled=true;e.SuppressKeyPress=true;}};
            FormClosed+=delegate{RestoreDetachedConsole(false);AppTheme.Changed-=ThemeChanged;poll.Stop();poll.Dispose();pageGeneration++;pageReads.Cancel();pageReads.Dispose();tray.Visible=false;tray.Dispose();statusTip.Dispose();if(showRegistration!=null)showRegistration.Unregister(null);if(rpc!=null)rpc.Dispose();};
            Shown+=async delegate{showRegistration=ThreadPool.RegisterWaitForSingleObject(NativeProgram.ShowEvent,delegate{if(IsHandleCreated&&!IsDisposed)BeginInvoke((Action)RestoreWindow);},null,Timeout.Infinite,false);await StartAsync();};
            AppTheme.Changed+=ThemeChanged;Ui.ApplyTheme(this);WindowChrome.SetSettingsAction(this,async delegate{await Safe(ShowSoftwareSettingsAsync);});

        }
        private void ThemeChanged(object sender,EventArgs e){if(IsDisposed||!IsHandleCreated)return;if(InvokeRequired){try{BeginInvoke((Action)ApplyOpenThemes);}catch(InvalidOperationException){}return;}ApplyOpenThemes();}
        protected override void Dispose(bool disposing){if(disposing)AppTheme.Changed-=ThemeChanged;base.Dispose(disposing);}
        private void ApplyOpenThemes(){var forms=new List<Form>();foreach(Form form in Application.OpenForms)forms.Add(form);foreach(Form form in forms)if(!form.IsDisposed)Ui.ApplyTheme(form);Ui.ApplyTheme(this);if(tray!=null&&tray.ContextMenuStrip!=null)Ui.ApplyTheme(tray.ContextMenuStrip);}
        internal static ComboBox ThemePicker(NativeLoginPreferences preferences){var selector=new ComboBox {Name="ThemeMode",DropDownStyle=ComboBoxStyle.DropDownList,Width=170};selector.Items.AddRange(new object[]{"跟随系统","浅色","深色"});selector.SelectedIndex=AppTheme.Mode=="light"?1:AppTheme.Mode=="dark"?2:0;selector.SelectedIndexChanged+=delegate{try{string mode=new[]{"system","light","dark"}[selector.SelectedIndex];preferences.ThemeMode=mode;preferences.Save();AppTheme.SetMode(mode);var owner=selector.FindForm();if(owner!=null)Ui.ApplyTheme(owner);}catch(Exception ex){Ui.Message(selector.FindForm(),ex.Message,"主题设置未保存",MessageBoxIcon.Warning);}};return selector;}
        internal static ComboBox AccentPicker(NativeLoginPreferences preferences){var selector=new ComboBox {Name="ThemeAccent",DropDownStyle=ComboBoxStyle.DropDownList,Width=170};var keys=new[]{"green","blue","violet","rose","amber","teal","slate"};selector.Items.AddRange(new object[]{"森林绿","海洋蓝","紫罗兰","玫瑰红","琥珀橙","青瓷青","石墨灰"});selector.SelectedIndex=Math.Max(0,Array.IndexOf(keys,AppTheme.Accent));selector.SelectedIndexChanged+=delegate{try{preferences.ThemeAccent=keys[selector.SelectedIndex];preferences.Save();AppTheme.SetAccent(preferences.ThemeAccent);var owner=selector.FindForm();if(owner!=null)Ui.ApplyTheme(owner);}catch(Exception ex){Ui.Message(selector.FindForm(),ex.Message,"主题色未保存",MessageBoxIcon.Warning);}};return selector;}
        internal static ComboBox PerformancePicker(NativeLoginPreferences preferences,Action changed){
            var selector=new ComboBox {Name="PerformanceMode",DropDownStyle=ComboBoxStyle.DropDownList,Width=260};selector.Items.AddRange(new object[]{"节省模式（默认）","华丽模式（较高资源占用）"});selector.SelectedIndex=preferences.PerformanceMode=="fancy"?1:0;bool reverting=false;
            selector.SelectedIndexChanged+=delegate{if(reverting||selector.SelectedIndex<0)return;string previous=NativeLoginPreferences.ValidPerformanceMode(preferences.PerformanceMode),next=selector.SelectedIndex==1?"fancy":"economy";if(next==previous)return;
                if(next=="fancy"&&!Ui.Confirm(selector.FindForm(),"开启华丽模式会增加内存 / CPU / 显卡占用，可能占用大量系统资源，请谨慎开启。\r\n\r\n该模式仅改变面板界面，不会提高 Minecraft 服务器性能。\r\n已加载的动效组件需要退出并重新打开面板后，才能完全释放内存。\r\n\r\n仍要开启华丽模式吗？","华丽模式 · 资源占用警告")){reverting=true;selector.SelectedIndex=previous=="fancy"?1:0;reverting=false;return;}
                try{preferences.PerformanceMode=next;preferences.Save();VisualEffects.Configure(next,preferences.AnimationsEnabled,preferences.HardwareAcceleration);if(changed!=null)changed();}catch(Exception ex){preferences.PerformanceMode=previous;reverting=true;selector.SelectedIndex=previous=="fancy"?1:0;reverting=false;Ui.Message(selector.FindForm(),ex.Message,"资源模式未保存",MessageBoxIcon.Warning);}
            };return selector;
        }
        internal static LinkLabel OwnershipLink(){var link=new LinkLabel {Name="OwnershipFooter",Text="© 2026 EeryFrank 所有",TextAlign=ContentAlignment.MiddleRight,Padding=new Padding(6,0,18,0),LinkColor=Ui.Muted,ActiveLinkColor=Ui.Primary,VisitedLinkColor=Ui.Muted,BackColor=Ui.Surface,Height=29,UseMnemonic=false};link.Links.Clear();link.Links.Add(0,link.Text.Length,"https://github.com/EeryFrank");link.LinkClicked+=delegate(object sender,LinkLabelLinkClickedEventArgs e){Process.Start(new ProcessStartInfo(Convert.ToString(e.Link.LinkData)){UseShellExecute=true});};return link;}
        private void RestoreWindowPlacement(){if(!loginPreferences.RememberWindow||loginPreferences.WindowWidth<=0||loginPreferences.WindowHeight<=0)return;var saved=new Rectangle(loginPreferences.WindowX,loginPreferences.WindowY,loginPreferences.WindowWidth,loginPreferences.WindowHeight);var area=Screen.FromRectangle(saved).WorkingArea;int width=Math.Min(area.Width,Math.Max(MinimumSize.Width,saved.Width)),height=Math.Min(area.Height,Math.Max(MinimumSize.Height,saved.Height));StartPosition=FormStartPosition.Manual;Bounds=new Rectangle(Math.Max(area.Left,Math.Min(saved.X,area.Right-width)),Math.Max(area.Top,Math.Min(saved.Y,area.Bottom-height)),width,height);if(loginPreferences.WindowMaximized)WindowState=FormWindowState.Maximized;}
        private void SaveWindowPlacement(){if((false)||!loginPreferences.RememberWindow||fullScreen)return;var saved=WindowState==FormWindowState.Normal?Bounds:RestoreBounds;if(saved.Width<=0||saved.Height<=0)return;loginPreferences.WindowX=saved.X;loginPreferences.WindowY=saved.Y;loginPreferences.WindowWidth=saved.Width;loginPreferences.WindowHeight=saved.Height;loginPreferences.WindowMaximized=(WindowState==FormWindowState.Minimized?lastNonMinimizedState:WindowState)==FormWindowState.Maximized;try{loginPreferences.Save();}catch(Exception ex){NativeProgram.Log(ex);}}
        private Button WindowButton(string text,string help,Func<Task> action){var button=new NativeWindowButton(text);button.Click+=async delegate{await Safe(action);};button.AutoSize=false;button.MinimumSize=new Size(44,34);button.Size=new Size(44,34);button.Margin=new Padding(0,0,8,6);button.AccessibleName=help;var tip=new ToolTip();tip.SetToolTip(button,help);button.Disposed+=delegate{tip.Dispose();};return button;}
        private void ToggleFullScreen(){if(!fullScreen){normalWindowBounds=WindowState==FormWindowState.Normal?Bounds:RestoreBounds;previousWindowState=WindowState;previousBorderStyle=FormBorderStyle;WindowState=FormWindowState.Normal;FormBorderStyle=FormBorderStyle.None;WindowChrome.SetFullScreen(this,true);WindowState=FormWindowState.Maximized;fullScreen=true;}else{fullScreen=false;WindowState=FormWindowState.Normal;FormBorderStyle=previousBorderStyle;WindowChrome.SetFullScreen(this,false);Bounds=normalWindowBounds;WindowState=previousWindowState;}}
        private sealed class ServerChoice {internal string Id,Name;public override string ToString(){return Name;}}
        private async Task StartAsync(){RestoreDetachedConsole(false);try{if(rpc!=null){if(!rpc.HasExited)await rpc.Call("panel.exit",null,null);rpc.Dispose();}rpc=new RpcClient();Text=ProductEdition.Title;bool automatic=!forceLoginOnce;forceLoginOnce=false;await AuthenticateAsync(automatic,!automatic);if(!authenticated)return;poll.Start();if(NativeProgram.Has("autostart")&&!NativeProgram.Has("smoke-test-dir"))HideToTray();if(NativeProgram.Has("smoke-test-dir")&&!smokeRunning){smokeRunning=true;await SmokeAsync();}}catch(Exception ex){NativeProgram.Log(ex);SetStatus(ex.Message);if(NativeProgram.Has("smoke-test-dir")){WriteSmoke(Ui.Obj("ok",false,"error",ex.Message));exiting=true;Close();}else{
            authenticated=false;poll.Stop();pageRefresh=null;selectedServerId="";currentAccount=Ui.Obj();sidebar.Visible=false;serverStateStrip.Visible=false;backToSelection.Visible=false;logoutButton.Visible=false;serversCombo.Visible=false;accountLabel.Text="尚未连接";foreach(Control old in content.Controls)old.Dispose();content.Controls.Clear();var help=new Label{Dock=DockStyle.Top,Height=115,Text="面板暂未启动："+ex.Message+"\r\n\r\n"+"可以重试启动，或导入本机已有服务器。",Padding=new Padding(12),ForeColor=Ui.Warning};
            Ui.Role(help,"warning");
            var actions=Ui.Toolbar(Ui.Button("重试启动",StartAsync),Ui.Button("版本说明…",ShowEditionInfoAsync));
            content.Controls.Add(actions);content.Controls.Add(help);
        }}}
        private async Task<Dictionary<string,object>> Call(string action,Dictionary<string,object> payload=null,string serverId=null){
            string target=serverId??selectedServerId;try{var result=IsPageRead(action)?await rpc.CallRead(action,payload,target,pageReadToken.Value):await rpc.Call(action,payload,target);if(target==selectedServerId&&(action=="status"||action=="settings.get"||action=="settings.capabilities"||action=="launch.settings"))RememberPlatform(result,target);if(action=="status"&&target==selectedServerId){ReadServerState(result);QueueStartupRecovery(result,target);}return result;}
            catch(OperationCanceledException){throw;}catch{if(target==selectedServerId&&(action=="status"||rpc.HasExited)){serverPresentation=new ServerPresentation {State="状态未知",Operation="操作状态不可用",Detail="无法读取后台状态，请检查连接后刷新。"};PublishServerState();}throw;}
        }
        private async Task Safe(Func<Task> work){try{await work();}catch(OperationCanceledException){}catch(Exception ex){NativeProgram.Log(ex);Ui.Message(this,ex.Message,"操作未完成",MessageBoxIcon.Warning);}}
        private void SetStatus(string message){if(!statusLabel.IsDisposed){statusLabel.Text=message;statusTip.SetToolTip(statusLabel,message);}}

        private async Task SwitchAccountAsync() {
            RestoreDetachedConsole(false); poll.Stop();
            try {loginPreferences.ClearAutomatic();await Call("logout");await AuthenticateAsync();}
            finally {if(authenticated&&MonitoringUiVisible&&!exiting)poll.Start();}
        }

        private async Task AuthenticateAsync(bool allowAutomatic=false,bool preserveAutomatic=false) {
            workspaceNavigationVersion++;
            if(!allowAutomatic&&!preserveAutomatic)loginPreferences.ClearAutomatic();
            RestoreDetachedConsole(false);authenticated=false;poll.Stop();CancelPageReads();if(activePageRefresh!=null)try{await activePageRefresh;}catch{}
            dashboardCpuSamples.Clear();dashboardMemorySamples.Clear();dashboardSampleServer="";dashboardLastSample="";SetStatus("请登录后选择服务器。");
            pageRefresh=null;dashboardStateChanged=null;inServerManagement=false;sidebar.Visible=false;serverStateStrip.Visible=false;backToSelection.Visible=false;logoutButton.Visible=false;serversCombo.Visible=false;currentAccount=Ui.Obj();platformProfiles.Clear();selectedServerId="";accountLabel.Text="尚未登录";pageTitle.Text="请登录";lastLoginWasAutomatic=false;changingServer=true;try{serversCombo.Items.Clear();serversCombo.Enabled=false;}finally{changingServer=false;}
            foreach(Control old in content.Controls)old.Dispose();content.Controls.Clear();
            var hello=await Call("hello");bool setup=Ui.Bool(hello,"setup_required");
            if(allowAutomatic&&!setup&&!NativeProgram.Has("smoke-credentials-file")&&loginPreferences.AutomaticLogin){
                var saved=loginPreferences.ReadAutomatic();
                if(saved!=null){try{var result=await Call("login",Ui.Obj("username",saved["username"],"password",saved["password"]));AcceptAccount(result,saved["username"]);lastLoginWasAutomatic=authenticated;}catch{loginPreferences.ClearAutomatic();}finally{saved.Clear();}}
                else loginPreferences.ClearAutomatic();
            }
            while(!authenticated){
                using(var login=new NativeLoginDialog(setup&&!preserveAutomatic,loginPreferences)){
                    Ui.ApplyTheme(login);if(NativeProgram.Has("smoke-credentials-file"))login.Automate(NativeProgram.Get("smoke-credentials-file"));
                    var response=login.ShowDialog(this);if(response!=DialogResult.OK){login.ClearPassword();await ExitAsync();return;}
                    try{var result=await Call(login.RegisterMode?"register":"login",Ui.Obj("username",login.Username,"password",login.Password));AcceptAccount(result,login.Username);if(!authenticated)throw new InvalidOperationException("登录未成功，请重试。");loginPreferences.Remember(login.Username,login.Password,login.RememberUsername,login.AutomaticLogin);}
                    catch(Exception error){if(NativeProgram.Has("smoke-test-dir"))throw;Ui.Message(this,error.Message,"登录失败",MessageBoxIcon.Warning);}
                    finally{login.ClearPassword();}
                }
            }
            accountLabel.Text="当前账号："+Ui.Text(currentAccount,"username");await RefreshServers();await ShowServerSelectionAsync();poll.Start();
        }


        private void AcceptAccount(Dictionary<string,object> result,string username){authenticated=Ui.Bool(result,"authenticated");object account;currentAccount=result.TryGetValue("account",out account)?Ui.Map(account):Ui.Obj("username",username);}


        private void SetWorkspaceManagementMode(bool managing){
            inServerManagement=managing&&authenticated&&selectedServerId.Length>0;
            sidebar.Visible=inServerManagement;serverStateStrip.Visible=inServerManagement;backToSelection.Visible=inServerManagement;
            serversCombo.Visible=inServerManagement;logoutButton.Visible=authenticated&&!inServerManagement;
        }
        private bool WorkspaceNavigationCurrent(long version){return version==workspaceNavigationVersion&&authenticated&&!exiting&&!IsDisposed;}
        private async Task ShowServerSelectionAsync(){
            if(!authenticated)return;
            long version=++workspaceNavigationVersion;
            RestoreDetachedConsole(false);SetWorkspaceManagementMode(false);poll.Stop();CancelPageReads();
            try{
                await RefreshServers();if(!WorkspaceNavigationCurrent(version))return;
                Task opening=NavigateAsync("servers");version=workspaceNavigationVersion;await opening;
                if(WorkspaceNavigationCurrent(version))SetStatus("选择服务器进入管理，也可以拖入服务器 ZIP 压缩包。");
            }catch{if(WorkspaceNavigationCurrent(version))throw;}
        }
        private async Task EnterServerAsync(string serverId){
            if(!authenticated||string.IsNullOrWhiteSpace(serverId))throw new InvalidOperationException("请先选择要管理的服务器。");
            long version=++workspaceNavigationVersion;RestoreDetachedConsole(false);
            try{
                await EnsureEditionServerAsync(serverId);if(!WorkspaceNavigationCurrent(version))return;
                await Call("servers.switch",Ui.Obj("server_id",serverId));if(!WorkspaceNavigationCurrent(version))return;
                selectedServerId=serverId;await RefreshServers();if(!WorkspaceNavigationCurrent(version))return;
                SetWorkspaceManagementMode(true);ResetServerState("正在连接");await NavigateAsync("dashboard");
            }catch{if(WorkspaceNavigationCurrent(version))throw;}
        }
        private void AttachArchiveDrop(Control control){
            control.AllowDrop=true;control.DragEnter+=delegate(object sender,DragEventArgs e){e.Effect=CanAcceptArchive(e)?DragDropEffects.Copy:DragDropEffects.None;};
            control.DragDrop+=async delegate(object sender,DragEventArgs e){if(!CanAcceptArchive(e)||archiveDropBusy)return;var files=(string[])e.Data.GetData(DataFormats.FileDrop);archiveDropBusy=true;try{await Safe(async delegate{await ImportServerArchiveAsync(files[0]);await ShowServerSelectionAsync();});}finally{archiveDropBusy=false;}};
        }
        private void AttachSelectionDrop(Control control){AttachArchiveDrop(control);foreach(Control child in control.Controls)AttachSelectionDrop(child);}
        private bool CanAcceptArchive(DragEventArgs e){if(!freeCanAddServer)return false;if(!authenticated||inServerManagement||archiveDropBusy||currentPage!="servers"||!e.Data.GetDataPresent(DataFormats.FileDrop))return false;var files=e.Data.GetData(DataFormats.FileDrop) as string[];return files!=null&&files.Length==1&&File.Exists(files[0])&&string.Equals(Path.GetExtension(files[0]),".zip",StringComparison.OrdinalIgnoreCase);}

        private async Task ShowSoftwareSettingsAsync() {
            if(!authenticated)throw new InvalidOperationException("请先登录，再设置软件选项。");
            poll.Stop();if(activePageRefresh!=null)try{await activePageRefresh;}catch{}
            bool accountChanged=false;
            try {
                var data=await Call("software.get");
                using(var dialog=new Form {Text="基础设置 · 七章控制面板",ClientSize=new Size(760,650),MinimumSize=new Size(640,500),StartPosition=FormStartPosition.CenterParent,MinimizeBox=false,Font=Font}){
                    var fields=Ui.Fields();AddEditionSettings(fields);
                    var remember=new CheckBox {Text="记住登录过的账号名称",Checked=loginPreferences.RememberUsernames,AutoSize=true};
                    var automatic=new CheckBox {Text="启动面板时自动登录",Checked=loginPreferences.AutomaticLogin,Enabled=remember.Checked,AutoSize=true};
                    var trayClose=new CheckBox {Text="关闭窗口时收起到托盘",Checked=loginPreferences.CloseToTray,AutoSize=true};
                    var trayMinimize=new CheckBox {Text="最小化时收起到托盘",Checked=loginPreferences.MinimizeToTray,AutoSize=true};
                    var rememberWindow=new CheckBox {Text="记住窗口大小和位置",Checked=loginPreferences.RememberWindow,AutoSize=true};
                    var startup=new CheckBox {Text="登录 Windows 后启动七章控制面板",Checked=Ui.Bool(data,"auto_start_panel"),AutoSize=true};
                    var hideLauncher=new CheckBox {Name="HideServerLauncherWindows",Text="隐藏服务器自带启动器窗口",Checked=!data.ContainsKey("hide_server_launcher_windows")||Ui.Bool(data,"hide_server_launcher_windows"),AutoSize=true};
                    remember.CheckedChanged+=delegate{automatic.Enabled=remember.Checked;if(!remember.Checked)automatic.Checked=false;};
                    SettingsSection(fields,"外观与资源", "主题立即生效；节省模式减少动效与刷新开销。");
                    Ui.Field(fields,"资源模式",PerformancePicker(loginPreferences,ConfigureMonitoringPoll));Ui.Field(fields,"外观主题",ThemePicker(loginPreferences));Ui.Field(fields,"主题色",AccentPicker(loginPreferences));
                    SettingsSection(fields,"登录与窗口", "自动登录需要先记住账号。");Ui.Field(fields,"账号记忆",remember);Ui.Field(fields,"自动登录",automatic);Ui.Field(fields,"窗口关闭",trayClose);Ui.Field(fields,"窗口最小化",trayMinimize);Ui.Field(fields,"窗口布局",rememberWindow);Ui.Field(fields,"开机启动",startup);
                    string permission=Ui.Text(data,"startup_permission","normal");
                    int general=loginPreferences.RefreshSeconds,console=loginPreferences.ConsoleRefreshMilliseconds,performance=loginPreferences.PerformanceRefreshMilliseconds;
                    bool high=loginPreferences.HighPerformanceMonitoring,animations=loginPreferences.AnimationsEnabled,hardware=loginPreferences.HardwareAcceleration;
                    Func<Task> advanced=async delegate {
                        using(var child=new Form {Text="高级设置",ClientSize=new Size(780,620),MinimumSize=new Size(640,500),StartPosition=FormStartPosition.CenterParent,Font=Font}){
                            var tabs=new TabControl {Dock=DockStyle.Fill};var runtime=new TabPage("运行与权限");var account=new TabPage("账号与密码");tabs.TabPages.Add(runtime);tabs.TabPages.Add(account);
                            var advancedFields=Ui.Fields();var permissionChoice=AdminCombo("normal","普通权限","administrator","管理员权限（保存时需要 Windows 授权）");AdminChoose(permissionChoice,permission);
                            var interval=AdminNumber(1,30,general);var consoleInterval=AdminNumber(1,60000,console);var performanceInterval=AdminNumber(1,60000,performance);
                            var highChoice=new CheckBox {Text="启用高性能实时监测",Checked=high,AutoSize=true};var animationChoice=new CheckBox {Text="启用界面动画",Checked=animations,AutoSize=true};var hardwareChoice=new CheckBox {Text="允许动效硬件加速",Checked=hardware,AutoSize=true};
                            Ui.Field(advancedFields,"开机启动权限",permissionChoice);Ui.Field(advancedFields,"启动器窗口",hideLauncher);Ui.Field(advancedFields,"常规刷新（秒）",interval);Ui.Field(advancedFields,"实时监测",highChoice);Ui.Field(advancedFields,"控制台刷新（毫秒）",consoleInterval);Ui.Field(advancedFields,"性能刷新（毫秒）",performanceInterval);Ui.Field(advancedFields,"界面动画",animationChoice);Ui.Field(advancedFields,"硬件加速",hardwareChoice);
                            Ui.Field(advancedFields,"说明",new Label {Text="刷新范围 1–60000 毫秒，默认 1000。实际频率受系统和后台速度限制；收起到托盘暂停界面刷新。动画只在华丽模式生效。",AutoSize=true,MaximumSize=new Size(510,0)});
                            runtime.Controls.Add(AdminScroll(advancedFields));var accountPage=await BuildAccountSettingsAsync(delegate{accountChanged=true;child.Close();dialog.Close();});accountPage.Dock=DockStyle.Fill;account.Controls.Add(accountPage);
                            var saveAdvanced=Ui.Button("保存并返回",delegate{permission=AdminKey(permissionChoice);general=(int)interval.Value;console=(int)consoleInterval.Value;performance=(int)performanceInterval.Value;high=highChoice.Checked;animations=animationChoice.Checked;hardware=hardwareChoice.Checked;hideLauncher.Parent=null;child.Close();return Task.FromResult(0);});var action=Ui.Toolbar(saveAdvanced);action.Dock=DockStyle.Bottom;child.Controls.Add(tabs);child.Controls.Add(action);Ui.ApplyTheme(child);
                            if(smokeRunning)child.Shown+=async delegate{await Task.Delay(100);CaptureSettingsSmoke(child,"native-software-advanced-runtime.png");tabs.SelectedTab=account;CaptureSettingsSmoke(child,"native-software-account.png");hideLauncher.Parent=null;child.Close();};
                            child.FormClosing+=delegate{hideLauncher.Parent=null;};child.ShowDialog(dialog);
                        }
                    };
                    var save=Ui.Button("保存基础设置",async delegate{
                        if(automatic.Checked&&loginPreferences.ProtectedCredential.Length==0)throw new InvalidOperationException("请在登录页面勾选记住账号和自动登录，并输入密码验证。");
                        await Call("software.update",Ui.Obj("auto_start_panel",startup.Checked,"startup_permission",permission,"hide_server_launcher_windows",hideLauncher.Checked));
                        loginPreferences.RememberUsernames=remember.Checked;loginPreferences.AutomaticLogin=remember.Checked&&automatic.Checked;loginPreferences.CloseToTray=trayClose.Checked;loginPreferences.MinimizeToTray=trayMinimize.Checked;loginPreferences.RememberWindow=rememberWindow.Checked;loginPreferences.RefreshSeconds=general;loginPreferences.ConsoleRefreshMilliseconds=console;loginPreferences.PerformanceRefreshMilliseconds=performance;loginPreferences.HighPerformanceMonitoring=high;loginPreferences.AnimationsEnabled=animations;loginPreferences.HardwareAcceleration=hardware;
                        if(!remember.Checked){loginPreferences.Usernames.Clear();loginPreferences.LastUsername="";}if(!loginPreferences.AutomaticLogin)loginPreferences.ProtectedCredential="";
                        loginPreferences.Save();VisualEffects.Configure(loginPreferences.PerformanceMode,animations,hardware);ConfigureMonitoringPoll();SetStatus("软件设置已保存");dialog.Close();
                    });
                    var advancedButton=Ui.Button("高级设置…",advanced);advancedButton.Name="AdvancedSettingsButton";var actions=Ui.Toolbar(save,advancedButton);actions.Dock=DockStyle.Bottom;dialog.Controls.Add(AdminScroll(fields));dialog.Controls.Add(actions);Ui.ApplyTheme(dialog);
                    if(smokeRunning)dialog.Shown+=async delegate{CaptureSettingsSmoke(dialog,"native-software-basic.png");await advanced();settingsFlowVerified=true;dialog.Close();};
                    dialog.ShowDialog(this);hideLauncher.Dispose();
                }
                if(accountChanged){loginPreferences.ClearAutomatic();await AuthenticateAsync();}
            }finally{if(authenticated&&MonitoringUiVisible&&!exiting)poll.Start();}
        }


        private async Task RefreshServers(){long version=workspaceNavigationVersion;RpcClient original=rpc;string accountId=Ui.Text(currentAccount,"id");var data=await Call("servers.list");if(version!=workspaceNavigationVersion||rpc!=original||accountId!=Ui.Text(currentAccount,"id")||!authenticated||exiting)return;platformProfiles.Clear();foreach(var row in Ui.List(data,"servers"))RememberPlatform(row,Ui.Text(row,"id"));ReadEditionSlot(data);string preferred=selectedServerId;if(preferred.Length==0)preferred=Ui.Text(data,"active_server_id");changingServer=true;try{serversCombo.Items.Clear();foreach(var item in Ui.List(data,"servers")){if(Ui.Bool(item,"edition_locked"))continue;var choice=new ServerChoice{Id=Ui.Text(item,"id"),Name=Ui.Text(item,"name")};serversCombo.Items.Add(choice);if(choice.Id==preferred)serversCombo.SelectedItem=choice;}if(serversCombo.SelectedIndex<0&&serversCombo.Items.Count>0)serversCombo.SelectedIndex=0;var selected=serversCombo.SelectedItem as ServerChoice;selectedServerId=selected==null?"":selected.Id;serversCombo.Enabled=serversCombo.Items.Count>0;}finally{changingServer=false;}}
        private async Task RefreshCurrentPageAsync(){
            if(refreshing||(!inServerManagement&&pageRefresh==null))return;refreshing=true;
            long generation=pageGeneration;var prior=pageReadToken.Value;pageReadToken.Value=pageReads.Token;
            try{activePageRefresh=RefreshPageAndStatusAsync();await activePageRefresh;if(DetachedConsoleVisible&&currentPage!="console")await detachedConsoleRefresh();}
            catch(OperationCanceledException){}catch(Exception ex){if(generation==pageGeneration)SetStatus(ex.Message);}
            finally{pageReadToken.Value=prior;activePageRefresh=null;refreshing=false;}
        }
        private async Task NavigateAsync(string key){
            if(!authenticated)return;ProductEdition.Require(key);
            if(key=="servers"){workspaceNavigationVersion++;SetWorkspaceManagementMode(false);RestoreDetachedConsole(false);}
            poll.Stop();CancelPageReads();
            long generation=pageGeneration;var token=pageReads.Token;var prior=pageReadToken.Value;pageReadToken.Value=token;pageLoading=true;
            try{
                currentPage=key;pageRefresh=null;dashboardStateChanged=null;
                content.SuspendLayout();try{while(content.Controls.Count>0)content.Controls[0].Dispose();content.Controls.Clear();}finally{content.ResumeLayout(false);}
                pageTitle.Text=key=="servers"?"服务器安装与选择":titles[key];foreach(var pair in navigation)Ui.Role(pair.Value,pair.Key==key?"selected":"nav");
                var loading=new Label {Name="PageLoading",Text="正在打开"+titles[key]+"…",Dock=DockStyle.Fill,Padding=new Padding(28)};content.Controls.Add(loading);content.PerformLayout();await Task.Yield();token.ThrowIfCancellationRequested();loading.Dispose();
                bool platformAllowed=CurrentPlatform.PageAllowed(key);
                bool needsServer=selectedServerId.Length==0&&key!="servers"&&key!="account";
                Control page=!platformAllowed&&!needsServer?PlatformUnsupportedPage(key):null;
                if(page==null)page=needsServer?BuildEmptyWorkspacePage():(key=="dashboard"?BuildDashboardPage():((key=="console")?BuildOperationsPage(key):BuildAdministrationPage(key)));
                page.Dock=DockStyle.Fill;if(page.Name=="AdminPage")AdminEmbedPage(page);Ui.ApplyTheme(page);if(!inServerManagement&&key=="servers")AttachSelectionDrop(page);content.Controls.Add(page);page.PerformLayout();VisualEffects.Reveal(page);
                // Commit the new controls before waiting for any server I/O.
                SetStatus("正在读取"+titles[key]+"…");await Task.Yield();token.ThrowIfCancellationRequested();await RefreshPageAndStatusAsync();
            }catch(OperationCanceledException){}catch(Exception error){if(generation==pageGeneration)SetStatus("读取失败："+error.Message);}
            finally{pageReadToken.Value=prior;if(generation==pageGeneration){pageLoading=false;ConfigureMonitoringPoll();nextGeneralRefresh=monitoringClock.ElapsedMilliseconds+loginPreferences.EffectiveRefreshMilliseconds;if(Visible&&authenticated&&!exiting)poll.Start();}}
        }
        private static TabControl FindTabs(Control root){if(root is TabControl)return (TabControl)root;foreach(Control child in root.Controls){var found=FindTabs(child);if(found!=null)return found;}return null;}
        private void CaptureSettingsSmoke(Form dialog,string name){using(var snapshot=new Bitmap(dialog.Width,dialog.Height)){dialog.DrawToBitmap(snapshot,new Rectangle(0,0,dialog.Width,dialog.Height));snapshot.Save(Path.Combine(NativeProgram.Get("smoke-test-dir"),name));}}
        private Control BuildEmptyWorkspacePage(){
            var page=new Panel {Dock=DockStyle.Fill,Padding=new Padding(26),BackColor=Ui.Surface};
            var heading=new Label {Dock=DockStyle.Top,Height=52,Text="开始管理你的服务器",Font=new Font("Microsoft YaHei UI",17F,FontStyle.Bold),ForeColor=Ui.Ink};
            var description=new Label {Dock=DockStyle.Top,Height=92,Text="当前账号还没有添加服务器。\r\n添加后即可使用控制台、基础设置与手动备份。\r\n每个账号单独保存自己的服务器列表与设置。",Font=new Font("Microsoft YaHei UI",10F),ForeColor=Ui.Muted};
            Ui.Role(page,"surface");Ui.Role(heading,"title");Ui.Role(description,"muted");
            var actions=Ui.Toolbar(Ui.Button("添加服务器",async delegate{await NavigateAsync("servers");}));page.Controls.Add(actions);page.Controls.Add(description);page.Controls.Add(heading);return page;
        }


        private void HideToTray(){CancelPageReads();SaveWindowPlacement();VisualEffects.Suspend(this);Hide();if(DetachedConsoleVisible)poll.Start();else poll.Stop();SetStatus(DetachedConsoleVisible?"主面板已收起；独立控制台继续刷新。":"面板在托盘运行，界面轮询已暂停");}
        private void RestoreWindow(){Show();WindowState=fullScreen||lastNonMinimizedState==FormWindowState.Maximized?FormWindowState.Maximized:FormWindowState.Normal;Activate();if(authenticated){poll.Start();RefreshCurrentPageAsync().ContinueWith(delegate{});}}
        private async Task ExitAsync(){
            if(exiting||exitInProgress)return;RestoreDetachedConsole(true);exitInProgress=true;poll.Stop();CancelPageReads();
            try{
                if(rpc!=null){if(rpc.HasExited&&authenticated)throw new InvalidOperationException("管理后台已断开，无法确认服务器是否安全关闭。面板已保留，请先恢复后台连接。");if(!rpc.HasExited){if(!await PrepareLocalExitAsync())return;await Call("panel.exit");}}
                SaveWindowPlacement();currentAccount.Clear();selectedServerId="";exiting=true;poll.Stop();Close();
            }catch(Exception error){SetStatus("暂时无法退出："+error.Message);throw new InvalidOperationException("暂时无法退出："+error.Message,error);}
            finally{exitInProgress=false;if(!exiting&&authenticated&&Visible){ConfigureMonitoringPoll();poll.Start();}}
        }
        private static DataGridView SmokeFindGrid(Control root){if(root is DataGridView)return (DataGridView)root;foreach(Control child in root.Controls){DataGridView grid=SmokeFindGrid(child);if(grid!=null)return grid;}return null;}
        private async Task CaptureCompactSmokeAsync(string directory,string page){
            if(!NativeProgram.Has("smoke-layout-checks"))return;
            Size original=Size;Point position=Location;
            try{Size=MinimumSize;PerformLayout();await Task.Delay(100);
                if(inServerManagement){foreach(Control status in new Control[]{serverStateLabel,operationStateLabel}){Rectangle bounds=new Rectangle(serverStateStrip.PointToClient(status.PointToScreen(Point.Empty)),status.Size);if(!status.Visible||status.Width<120||!serverStateStrip.ClientRectangle.Contains(bounds))throw new InvalidOperationException("小窗口状态栏不可见："+status.Name);}}
                if(page=="servers"){DataGridView grid=SmokeFindGrid(content);if(grid==null||grid.ClientSize.Height<grid.ColumnHeadersHeight+2*grid.RowTemplate.Height+SystemInformation.HorizontalScrollBarHeight+2)throw new InvalidOperationException("小窗口列表不能完整显示两行："+page);}
                using(var bitmap=new Bitmap(Width,Height)){DrawToBitmap(bitmap,new Rectangle(Point.Empty,Size));bitmap.Save(Path.Combine(directory,"native-"+page+"-compact.png"));}
            }finally{Size=original;Location=position;PerformLayout();}
        }
        private void WriteSmoke(object data){string dir=NativeProgram.Get("smoke-test-dir");Directory.CreateDirectory(dir);File.WriteAllText(Path.Combine(dir,"native-smoke.json"),NativeProgram.Json.Serialize(data),Encoding.UTF8);}
        private async Task SmokeAsync(){
            string initialAccountId=Ui.Text(currentAccount,"id"),initialUsername=Ui.Text(currentAccount,"username");int initialServerCount=serversCombo.Items.Count;bool accountSwitchVerified=false;string switchedAccountId="";int switchedServerCount=-1;
            string dir=NativeProgram.Get("smoke-test-dir");Directory.CreateDirectory(dir);Show();WindowState=FormWindowState.Normal;var screen=Screen.FromControl(this).WorkingArea;Size=new Size(Math.Min(Width,screen.Width-24),Math.Min(Height,screen.Height-24));Location=new Point(screen.Left+(screen.Width-Width)/2,screen.Top+(screen.Height-Height)/2);Activate();await Task.Delay(700);
            bool loginOpenedSelection=!inServerManagement&&currentPage=="servers";
            if(!loginOpenedSelection)throw new InvalidOperationException("登录后必须先进入服务器选择页。");
            bool oldMinimize=loginPreferences.MinimizeToTray;loginPreferences.MinimizeToTray=false;WindowState=FormWindowState.Minimized;await Task.Delay(100);bool taskbarMinimized=Visible&&WindowState==FormWindowState.Minimized&&!poll.Enabled;RestoreWindow();loginPreferences.MinimizeToTray=true;WindowState=FormWindowState.Minimized;await Task.Delay(100);bool trayMinimized=!Visible&&!poll.Enabled;RestoreWindow();loginPreferences.MinimizeToTray=oldMinimize;bool windowBehaviorVerified=taskbarMinimized&&trayMinimized;if(!windowBehaviorVerified)throw new InvalidOperationException("独立最小化到托盘设置验证失败。");
            var ownership=(LinkLabel)Controls.Find("OwnershipFooter",true)[0];bool ownershipVerified=ownership.ClientSize.Width-ownership.Padding.Horizontal>=TextRenderer.MeasureText(ownership.Text,ownership.Font).Width&&ownership.Links.Count==1&&Convert.ToString(ownership.Links[0].LinkData)=="https://github.com/EeryFrank";if(!ownershipVerified)throw new InvalidOperationException("版权角标的可见宽度或链接不正确。");
            FormBorderStyle savedBorder=FormBorderStyle;ToggleFullScreen();await Task.Delay(150);bool fullScreenEntered=fullScreen&&FormBorderStyle==FormBorderStyle.None&&WindowState==FormWindowState.Maximized;OnKeyDown(new KeyEventArgs(Keys.Escape));await Task.Delay(150);bool fullScreenVerified=fullScreenEntered&&!fullScreen&&FormBorderStyle==savedBorder&&WindowState==FormWindowState.Normal;if(!fullScreenVerified)throw new InvalidOperationException("全屏 / Esc 恢复验证失败。");
            string dropFixture=Path.Combine(NativeProgram.DataRoot,"native-smoke-drop.zip");File.WriteAllBytes(dropFixture,new byte[0]);var fileDrop=new DataObject(DataFormats.FileDrop,new string[]{dropFixture});var dropEvent=new DragEventArgs(fileDrop,0,0,0,DragDropEffects.Copy,DragDropEffects.None);bool archiveDropSelection=CanAcceptArchive(dropEvent)==(freeCanAddServer);authenticated=false;bool archiveDropLoggedOut=!CanAcceptArchive(dropEvent);authenticated=true;
            using(var image=new Bitmap(Width,Height)){DrawToBitmap(image,new Rectangle(0,0,Width,Height));image.Save(Path.Combine(dir,"native-selection.png"));}
            await ShowSoftwareSettingsAsync();
            if(initialServerCount>0)await EnterServerAsync(selectedServerId);
            bool archiveDropManagement=initialServerCount==0||!CanAcceptArchive(dropEvent);File.Delete(dropFixture);if(!archiveDropSelection||!archiveDropLoggedOut||!archiveDropManagement)throw new InvalidOperationException("服务器 ZIP 拖放页面限制验证失败。");
            using(var image=new Bitmap(Width,Height)){DrawToBitmap(image,new Rectangle(0,0,Width,Height));image.Save(Path.Combine(dir,"native-dashboard.png"));}await CaptureCompactSmokeAsync(dir,"dashboard");
            TopMost=true;await Task.Delay(200);var ownedClient=RectangleToScreen(ClientRectangle);using(var image=new Bitmap(ownedClient.Width,ownedClient.Height)){using(var graphics=Graphics.FromImage(image))graphics.CopyFromScreen(ownedClient.Location,Point.Empty,ownedClient.Size);image.Save(Path.Combine(dir,"native-dashboard-screen.png"));}TopMost=false;
            var pages=new List<string>();foreach(string key in (initialServerCount>0?new[]{"console","settings","backups","servers","account"}:new[]{"servers","account"})){if(!ProductEdition.Has(key))continue;if(key=="servers")await ShowServerSelectionAsync();else await NavigateAsync(key);await Task.Delay(150);pages.Add(key);using(var image=new Bitmap(Width,Height)){DrawToBitmap(image,new Rectangle(0,0,Width,Height));image.Save(Path.Combine(dir,"native-"+key+".png"));}await CaptureCompactSmokeAsync(dir,key);if(key=="servers"&&initialServerCount>0)await EnterServerAsync(selectedServerId);}
            if(NativeProgram.Has("smoke-switch-credentials-file")){
                NativeProgram.Set("smoke-credentials-file",NativeProgram.Get("smoke-switch-credentials-file"));await SwitchAccountAsync();switchedAccountId=Ui.Text(currentAccount,"id");switchedServerCount=serversCombo.Items.Count;
                if(switchedAccountId==initialAccountId||switchedServerCount!=0)throw new InvalidOperationException("切换新账号后没有获得独立空白空间。");
                await Task.Delay(200);using(var image=new Bitmap(Width,Height)){DrawToBitmap(image,new Rectangle(0,0,Width,Height));image.Save(Path.Combine(dir,"native-switched-account.png"));}
                if(!NativeProgram.Has("smoke-return-credentials-file"))throw new InvalidOperationException("多账号界面测试缺少返回账号凭据文件。");
                NativeProgram.Set("smoke-credentials-file",NativeProgram.Get("smoke-return-credentials-file"));await SwitchAccountAsync();
                accountSwitchVerified=Ui.Text(currentAccount,"id")==initialAccountId&&serversCombo.Items.Count==initialServerCount&&!inServerManagement&&currentPage=="servers";
                if(!accountSwitchVerified)throw new InvalidOperationException("切回原账号后，服务器列表没有恢复。");
            }
            if(initialServerCount>0)await EnterServerAsync(selectedServerId);else await ShowServerSelectionAsync();HideToTray();await Task.Delay(700);var process=Process.GetCurrentProcess();var hostProcess=Process.GetProcessById(rpc.ProcessId);double cpuBefore=process.TotalProcessorTime.TotalMilliseconds,hostCpuBefore=hostProcess==null?0:hostProcess.TotalProcessorTime.TotalMilliseconds;var clock=Stopwatch.StartNew();await Task.Delay(10000);clock.Stop();process.Refresh();if(hostProcess!=null)hostProcess.Refresh();double idleCpu=100*(process.TotalProcessorTime.TotalMilliseconds-cpuBefore)/clock.Elapsed.TotalMilliseconds,hostIdleCpu=hostProcess==null?0:100*(hostProcess.TotalProcessorTime.TotalMilliseconds-hostCpuBefore)/clock.Elapsed.TotalMilliseconds;long memory=process.WorkingSet64,hostMemory=hostProcess==null?0:hostProcess.WorkingSet64;
            RestoreWindow();await Task.Delay(500);using(var image=new Bitmap(Width,Height)){DrawToBitmap(image,new Rectangle(0,0,Width,Height));image.Save(Path.Combine(dir,"native-reopened.png"));}
            await ShowServerSelectionAsync();bool returnedToSelection=!inServerManagement&&currentPage=="servers";using(var image=new Bitmap(Width,Height)){DrawToBitmap(image,new Rectangle(0,0,Width,Height));image.Save(Path.Combine(dir,"native-selection-return.png"));}
            WriteSmoke(Ui.Obj("ok",true,"pages",pages,"authenticated",authenticated,"login_opened_selection",loginOpenedSelection,"returned_to_selection",returnedToSelection,"software_settings_flow_verified",settingsFlowVerified,"theme_mode",AppTheme.Mode,"theme_dark",AppTheme.IsDark,"theme_accent",AppTheme.Accent,"performance_mode",loginPreferences.PerformanceMode,"poll_milliseconds",poll.Interval,"animations_enabled",loginPreferences.AnimationsEnabled,"hardware_acceleration",loginPreferences.HardwareAcceleration,"window_behavior_verified",windowBehaviorVerified,"ownership_footer_verified",ownershipVerified,"full_screen_escape_verified",fullScreenVerified,"archive_drop_gate_verified",archiveDropSelection&&archiveDropLoggedOut&&archiveDropManagement,"automatic_login",lastLoginWasAutomatic,"account_username",Ui.Text(currentAccount,"username"),"account_id",Ui.Text(currentAccount,"id"),"server_count",serversCombo.Items.Count,"account_switch_tested",NativeProgram.Has("smoke-switch-credentials-file"),"account_switch_verified",accountSwitchVerified,"initial_account_id",initialAccountId,"initial_server_count",initialServerCount,"switched_account_id",switchedAccountId,"switched_server_count",switchedServerCount,"tray_cpu_percent_one_core",idleCpu,"tray_memory_bytes",memory,"host_tray_cpu_percent_one_core",hostIdleCpu,"host_tray_memory_bytes",hostMemory,"host_pid",rpc.ProcessId,"native_pid",process.Id,"utc",DateTime.UtcNow.ToString("o")));await ExitAsync();
        }
    }

    internal sealed class NativeLoginDialog : Form {
        private readonly ComboBox loginUsername;
        private readonly TextBox loginPassword,registerUsername,registerPassword,confirmation;
        private readonly CheckBox rememberUsername,automaticLogin;
        private readonly Button submit;
        private readonly TabControl modes;
        internal bool RegisterMode {get{return modes.SelectedIndex==1;}}
        internal string Username{get{return RegisterMode?registerUsername.Text.Trim():loginUsername.Text.Trim();}}
        internal string Password{get{return (RegisterMode?registerPassword:loginPassword).Text;}}
        internal bool RememberUsername {get{return rememberUsername.Checked;}}
        internal bool AutomaticLogin {get{return rememberUsername.Checked&&automaticLogin.Checked;}}
        internal NativeLoginDialog(bool firstRun,NativeLoginPreferences preferences){
            Text="七章控制面板 · 登录与注册";ClientSize=new Size(620,640);FormBorderStyle=FormBorderStyle.FixedDialog;StartPosition=FormStartPosition.CenterParent;MinimizeBox=false;MaximizeBox=false;Font=new Font("Microsoft YaHei UI",10F);BackColor=Ui.Canvas;Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath)??SystemIcons.Application;
            var heading=new Panel {Dock=DockStyle.Top,Height=102,Padding=new Padding(28,17,20,12),BackColor=Ui.Sidebar};
            heading.Controls.Add(new Label{Text="登录后进入你的服务器工作区。",Dock=DockStyle.Bottom,Height=26,ForeColor=Ui.SidebarInk});
            heading.Controls.Add(new Label{Text="七章面板 · "+ProductEdition.Label,Dock=DockStyle.Top,Height=42,ForeColor=Ui.Surface,Font=new Font("Microsoft YaHei UI",20F,FontStyle.Bold)});
            Ui.Role(heading,"sidebar");foreach(Control label in heading.Controls)Ui.Role(label,"brand");
            modes=new TabControl {Name="ConnectionMode",Dock=DockStyle.Fill,Padding=new Point(26,12)};
            var login=new TabPage("本机登录") {Padding=new Padding(20)};var register=new TabPage("创建本机账号") {Padding=new Padding(20)};
            modes.TabPages.Add(login);modes.TabPages.Add(register);
            loginUsername=new ComboBox {MaxLength=64,DropDownStyle=ComboBoxStyle.DropDown};foreach(string name in preferences.Usernames)loginUsername.Items.Add(name);loginUsername.Text=preferences.RememberUsernames?preferences.LastUsername:"";loginPassword=new TextBox {MaxLength=128,UseSystemPasswordChar=true};registerUsername=new TextBox {MaxLength=64};registerPassword=new TextBox {MaxLength=128,UseSystemPasswordChar=true};confirmation=new TextBox {MaxLength=128,UseSystemPasswordChar=true};
            var loginFields=Ui.Fields();Ui.Field(loginFields,"账号",loginUsername);Ui.Field(loginFields,"密码",loginPassword);
            var registerFields=Ui.Fields();Ui.Field(registerFields,"账号",registerUsername);Ui.Field(registerFields,"密码",registerPassword);Ui.Field(registerFields,"确认密码",confirmation);
            var loginHelp=new Label {Text="本机管理\r\n登录后选择或安装服务器，再进入管理面板。\r\n账号配置独立；整个安装共管理一台服务器。",AutoEllipsis=true,Dock=DockStyle.Top,Height=96,Padding=new Padding(6,16,0,0),ForeColor=Ui.Muted};
            var registerHelp=new Label {Text="建立独立的管理空间\r\n密码至少 10 位。新账号的服务器列表从空白开始。",Dock=DockStyle.Top,Height=70,Padding=new Padding(6,12,0,0),ForeColor=Ui.Muted};
            Ui.Role(loginHelp,"muted");Ui.Role(registerHelp,"muted");
            login.Controls.Add(loginHelp);login.Controls.Add(loginFields);register.Controls.Add(registerHelp);register.Controls.Add(registerFields);
            var footer=new Panel {Dock=DockStyle.Bottom,Height=66,Padding=new Padding(25,9,25,15)};
            rememberUsername=new CheckBox {Text="记住账号",Checked=preferences.RememberUsernames,AutoSize=true,Margin=new Padding(0,9,20,0)};automaticLogin=new CheckBox {Text="自动登录",Checked=preferences.AutomaticLogin,Enabled=preferences.RememberUsernames,AutoSize=true,Margin=new Padding(0,9,0,0)};rememberUsername.CheckedChanged+=delegate{automaticLogin.Enabled=rememberUsername.Checked;if(!rememberUsername.Checked)automaticLogin.Checked=false;};var choices=Ui.Toolbar(rememberUsername,automaticLogin);choices.Dock=DockStyle.Bottom;choices.Padding=new Padding(26,0,0,0);choices.Height=40;
            submit=Ui.Button("登录",delegate{{if(Username.Length==0)throw new InvalidOperationException("请输入账号。");if(Password.Length==0||(RegisterMode&&Password.Length<10))throw new InvalidOperationException(RegisterMode?"密码至少需要 10 位。":"请输入密码。");if(RegisterMode&&Password!=confirmation.Text)throw new InvalidOperationException("两次输入的密码不一致。");}DialogResult=DialogResult.OK;return Task.FromResult(0);});submit.Dock=DockStyle.Right;submit.Width=180;
            var cancel=Ui.Button("关闭",delegate{DialogResult=DialogResult.Cancel;return Task.FromResult(0);});cancel.Dock=DockStyle.Left;cancel.Width=100;cancel.DialogResult=DialogResult.Cancel;footer.Controls.Add(submit);footer.Controls.Add(cancel);
            Action updateLoginMode=delegate{submit.Text=RegisterMode?"注册并进入":"登录";automaticLogin.Enabled=rememberUsername.Checked;};modes.SelectedIndexChanged+=delegate{updateLoginMode();};Shown+=delegate{updateLoginMode();};modes.SelectedIndex=firstRun?1:0;submit.Text=RegisterMode?"注册并进入":"登录";
            var themeRow=new TableLayoutPanel {Dock=DockStyle.Bottom,Height=44,Padding=new Padding(26,0,26,0),ColumnCount=2};themeRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,110));themeRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));var themeLabel=new Label {Text="外观主题",Dock=DockStyle.Fill,TextAlign=ContentAlignment.MiddleLeft};Ui.Role(themeLabel,"muted");var theme=NativeMainForm.ThemePicker(preferences);theme.Dock=DockStyle.Fill;theme.Margin=new Padding(0,6,0,4);themeRow.Controls.Add(themeLabel,0,0);themeRow.Controls.Add(theme,1,0);
            var ownership=NativeMainForm.OwnershipLink();ownership.Dock=DockStyle.Bottom;ownership.Height=26;ClientSize=new Size(620,650);
            Controls.Add(modes);Controls.Add(choices);Controls.Add(themeRow);Controls.Add(footer);Controls.Add(ownership);Controls.Add(heading);AcceptButton=submit;CancelButton=cancel;
        }
        internal void ClearPassword(){loginPassword.Clear();registerPassword.Clear();confirmation.Clear();}
        internal void Automate(string path){
            var credentials=NativeProgram.Json.Deserialize<Dictionary<string,string>>(File.ReadAllText(path,Encoding.UTF8));string mode;credentials.TryGetValue("mode",out mode);
            {modes.SelectedIndex=mode=="register"?1:0;loginUsername.Text=registerUsername.Text=credentials["username"];loginPassword.Text=registerPassword.Text=confirmation.Text=credentials["password"];string flag;if(credentials.TryGetValue("remember",out flag))rememberUsername.Checked=flag.Equals("true",StringComparison.OrdinalIgnoreCase);if(credentials.TryGetValue("automatic",out flag))automaticLogin.Checked=rememberUsername.Checked&&flag.Equals("true",StringComparison.OrdinalIgnoreCase);}
            submit.Text=RegisterMode?"注册并进入":"登录";credentials.Clear();
            Shown+=delegate{if(NativeProgram.Has("smoke-test-dir")){string dir=NativeProgram.Get("smoke-test-dir");Directory.CreateDirectory(dir);using(var image=new Bitmap(Width,Height)){DrawToBitmap(image,new Rectangle(0,0,Width,Height));image.Save(Path.Combine(dir,RegisterMode?"native-register.png":"native-login.png"));}}BeginInvoke((Action)(delegate{submit.PerformClick();}));};
        }
    }
}
