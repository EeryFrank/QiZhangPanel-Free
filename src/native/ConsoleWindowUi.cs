// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal sealed partial class NativeMainForm {
        private Form detachedConsoleWindow;
        private Control detachedConsolePage;
        private Func<Task> detachedConsoleRefresh;
        private string detachedConsoleServer="",detachedConsoleAccount="";
        private bool DetachedConsoleCurrent {get{return detachedConsoleWindow!=null&&!detachedConsoleWindow.IsDisposed&&detachedConsolePage!=null&&!detachedConsolePage.IsDisposed&&authenticated&&inServerManagement&&detachedConsoleServer==selectedServerId&&detachedConsoleAccount==StartupRecoveryAccount();}}
        private bool DetachedConsoleVisible {get{return DetachedConsoleCurrent&&detachedConsoleWindow.Visible&&detachedConsoleWindow.WindowState!=FormWindowState.Minimized;}}
        private bool MonitoringUiVisible {get{return Visible&&WindowState!=FormWindowState.Minimized||DetachedConsoleVisible;}}

        private Control BuildDetachedConsolePlaceholder(){
            var page=new Panel {Name="DetachedConsolePlaceholder",Dock=DockStyle.Fill,Padding=new Padding(24)};
            var message=new Label {Text="控制台已在独立窗口打开。日志与命令仍属于同一服务器；关闭独立窗口即可回到这里。",Dock=DockStyle.Top,Height=64};Ui.Role(message,"muted");
            var focus=Ui.Button("显示独立控制台",delegate{if(DetachedConsoleCurrent){detachedConsoleWindow.Show();detachedConsoleWindow.WindowState=FormWindowState.Normal;detachedConsoleWindow.Activate();}return Task.CompletedTask;});focus.Name="FocusDetachedConsole";
            var restore=Ui.Button("返回主面板",delegate{RestoreDetachedConsole(true);return Task.CompletedTask;});restore.Name="RestoreConsole";
            page.Controls.Add(Ui.Toolbar(focus,restore));page.Controls.Add(message);pageRefresh=detachedConsoleRefresh;Ui.ApplyTheme(page);return page;
        }
        private void DetachConsole(Control page,Func<Task> refresh,string id,string account){
            if(DetachedConsoleCurrent){detachedConsoleWindow.Activate();return;}
            if(page.IsDisposed||selectedServerId!=id||account!=StartupRecoveryAccount()||!authenticated||!inServerManagement)return;
            string name=id;foreach(object entry in serversCombo.Items){var server=entry as ServerChoice;if(server!=null&&server.Id==id){name=server.Name;break;}}
            var window=new Form {Name="DetachedConsoleWindow",Text="控制台 · "+name+" · "+("本机服务器"),ClientSize=new Size(1040,700),MinimumSize=new Size(780,560),StartPosition=FormStartPosition.CenterScreen,Font=Font,Icon=Icon};
            detachedConsoleWindow=window;detachedConsolePage=page;detachedConsoleRefresh=refresh;detachedConsoleServer=id;detachedConsoleAccount=account;
            page.Parent.Controls.Remove(page);window.Controls.Add(page);page.Dock=DockStyle.Fill;
            var identity=new Label {Name="DetachedConsoleIdentity",Text="服务器："+name+"    ·    关闭本窗口返回主面板，不会停服",Dock=DockStyle.Top,Height=36,Padding=new Padding(12,8,8,0),AutoEllipsis=true};Ui.Role(identity,"title");window.Controls.Add(identity);
            content.Controls.Add(BuildDetachedConsolePlaceholder());
            window.FormClosing+=delegate{if(detachedConsoleWindow==window)RestoreDetachedConsole(true,true);};
            window.Resize+=delegate{if(!exiting){ConfigureMonitoringPoll();if(MonitoringUiVisible)poll.Start();else poll.Stop();}};
            Ui.ApplyTheme(window);WindowChrome.SetSettingsAction(window,async delegate{await Safe(ShowSoftwareSettingsAsync);});window.Show();ConfigureMonitoringPoll();poll.Start();
        }
        private void RestoreDetachedConsole(bool showConsole,bool alreadyClosing=false){
            if(detachedConsoleWindow==null)return;
            var window=detachedConsoleWindow;var page=detachedConsolePage;var refresh=detachedConsoleRefresh;bool current=DetachedConsoleCurrent;
            detachedConsoleWindow=null;detachedConsolePage=null;detachedConsoleRefresh=null;detachedConsoleServer="";detachedConsoleAccount="";
            if(page!=null&&page.Parent!=null)page.Parent.Controls.Remove(page);
            if(!alreadyClosing&&!window.IsDisposed){window.Close();window.Dispose();}
            if(showConsole&&current&&!exiting&&!IsDisposed){
                CancelPageReads();while(content.Controls.Count>0)content.Controls[0].Dispose();content.Controls.Clear();currentPage="console";pageRefresh=refresh;dashboardStateChanged=null;pageTitle.Text=titles["console"];foreach(var pair in navigation)Ui.Role(pair.Value,pair.Key=="console"?"selected":"nav");page.Dock=DockStyle.Fill;content.Controls.Add(page);Show();if(WindowState==FormWindowState.Minimized)WindowState=lastNonMinimizedState;Activate();ConfigureMonitoringPoll();poll.Start();SetStatus("控制台已返回主面板；服务器继续运行。");
            }else if(page!=null&&!page.IsDisposed)page.Dispose();
        }
    }
}
