// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal sealed class ServerSelectionMenuRenderer : ToolStripRenderer {
        internal static readonly Color PermanentDeleteRed=Color.FromArgb(229,57,53);
        private readonly ToolStripRenderer themed;
        internal ServerSelectionMenuRenderer(ToolStripRenderer renderer) { themed=renderer; }
        protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e){themed.DrawToolStripBackground(e);}
        protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e){themed.DrawToolStripBorder(e);}
        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e){themed.DrawMenuItemBackground(e);}
        protected override void OnRenderImageMargin(ToolStripRenderEventArgs e){themed.DrawImageMargin(e);}
        protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e){themed.DrawSeparator(e);}
        protected override void OnRenderArrow(ToolStripArrowRenderEventArgs e){themed.DrawArrow(e);}
        protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e){themed.DrawItemCheck(e);}
        protected override void OnRenderItemImage(ToolStripItemImageRenderEventArgs e){themed.DrawItemImage(e);}
        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e){
            if(e.Item.Name=="ServerMenuDelete")TextRenderer.DrawText(e.Graphics,e.Text,e.TextFont,e.TextRectangle,PermanentDeleteRed,e.TextFormat);
            else themed.DrawItemText(e);
        }
    }
    internal sealed class ServerSelectionContextMenu : ContextMenuStrip {
        internal ServerSelectionContextMenu(){
            Name="ServerSelectionContextMenu";ShowItemToolTips=true;
            RendererChanged+=delegate{if(!(Renderer is ServerSelectionMenuRenderer))Renderer=new ServerSelectionMenuRenderer(Renderer);};
            Renderer=new ServerSelectionMenuRenderer(Renderer);
        }
    }
    internal sealed class ServerSelectionAvailability {
        internal bool Known, Idle, Unlocked, CanEnter, CanStart, CanStop, CanSave, CanDelete;
        internal string Reason;
        internal static ServerSelectionAvailability Read(Dictionary<string,object> row,string workspaceError,bool pending) {
            object raw; var operation=row.TryGetValue("operation",out raw)?Ui.Map(raw):Ui.Obj(); var countdown=row.TryGetValue("shutdown_countdown",out raw)?Ui.Map(raw):Ui.Obj();
            string state=Ui.Text(row,"lifecycle_state",Ui.Text(row,"state"));
            var value=new ServerSelectionAvailability(); value.Unlocked=!Ui.Bool(row,"edition_locked");
            value.Known=row.ContainsKey("running")&&(!row.ContainsKey("status_known")||Ui.Bool(row,"status_known"))&&!Ui.Bool(row,"status_stale")&&state!="unknown";
            value.Idle=operation.ContainsKey("active")&&!Ui.Bool(operation,"active")&&!Ui.Bool(countdown,"active")&&Array.IndexOf(new[]{"starting","stopping","restarting","maintenance"},state)<0&&!Ui.Bool(row,"starting");
            value.CanEnter=Ui.Text(row,"id").Length>0&&value.Unlocked&&String.IsNullOrEmpty(workspaceError)&&!pending;
            value.Reason=pending?"另一项服务器操作尚未完成。":!value.Unlocked?Ui.Text(row,"edition_lock_reason","当前版本不能管理这条服务器记录。"):!String.IsNullOrEmpty(workspaceError)?"请先修复工作区目录。":!value.Known?"服务器状态未知或已过期，请先刷新状态。":!value.Idle?"服务器正执行操作或状态尚未读完，请完成后再操作。":"";
            bool available=value.CanEnter&&value.Known&&value.Idle;
            value.CanStart=available&&!Ui.Bool(row,"running"); value.CanStop=available&&Ui.Bool(row,"running");
            value.CanSave=available&&(Ui.Bool(row,"ready")||state=="online")&&PlatformUiProfile.Read(row).Allows("save_world"); value.CanDelete=available&&!Ui.Bool(row,"running");
            return value;
        }
    }

    internal sealed class ServerDeleteDialog : Form {
        private readonly TextBox confirmation;
        private readonly Button remove,cancel;
        private readonly TextBox status;
        private bool pending,consumed;
        internal bool Deleted { get; private set; }
        internal ServerDeleteDialog(Dictionary<string,object> preview,Font font,Func<Dictionary<string,object>,Task<Dictionary<string,object>>> submit) {
            Name="ServerDeleteDialog"; Text="永久删除服务器"; Font=font; Width=740; Height=590; MinimumSize=new Size(620,470); StartPosition=FormStartPosition.CenterParent; MinimizeBox=false; MaximizeBox=false;
            var fields=Ui.Fields(); fields.Dock=DockStyle.Top;
            var warning=new Label { Name="ServerDeleteWarning",Text="此操作会永久删除下面的整个服务器文件夹，包括世界存档、模组、配置和目录内其他文件。删除不会进入回收站，无法由面板撤销。\r\n请确认需要的备份已另存到该目录之外。",AutoSize=true,MaximumSize=new Size(470,0),Padding=new Padding(0,3,0,8) }; Ui.Role(warning,"danger");
            var serverName=new TextBox {Name="ServerDeleteName",ReadOnly=true,Text=Ui.Text(preview,"name"),Width=430};
            var path=new TextBox {Name="ServerDeletePath",ReadOnly=true,Multiline=true,WordWrap=false,ScrollBars=ScrollBars.Both,Height=92,Width=430,Text=Ui.Text(preview,"path")};
            confirmation=new TextBox {Name="ServerDeleteConfirmation",Width=250,MaxLength=32};
            var instruction=new Label {Text="请逐字输入：同意删除\r\n必须完全一致，不接受多余空格。",AutoSize=true,MaximumSize=new Size(430,0)};
            Ui.Field(fields,"永久删除说明",warning); Ui.Field(fields,"服务器名称",serverName); Ui.Field(fields,"完整目录",path); Ui.Field(fields,"确认短语",instruction); Ui.Field(fields,"手动输入",confirmation);
            var scroll=new Panel {Dock=DockStyle.Fill,AutoScroll=true,Padding=new Padding(14,8,14,6)}; scroll.Controls.Add(fields);
            status=new TextBox {Name="ServerDeleteStatus",Dock=DockStyle.Bottom,Height=80,ReadOnly=true,Multiline=true,ScrollBars=ScrollBars.Vertical,BorderStyle=BorderStyle.None,Text="尚未执行删除。取消将保留全部文件。"}; Ui.Role(status,"muted");
            cancel=new Button {Name="ServerDeleteCancel",Text="取消，保留服务器",AutoSize=true,MinimumSize=new Size(158,36),Padding=new Padding(10,4,10,4),DialogResult=DialogResult.Cancel};
            remove=new Button {Name="ServerDeleteConfirm",Text="永久删除整个文件夹",AutoSize=true,MinimumSize=new Size(178,36),Padding=new Padding(10,4,10,4),Enabled=false}; Ui.Role(remove,"danger");
            var buttons=Ui.Toolbar(cancel,remove); buttons.Dock=DockStyle.Bottom; buttons.Padding=new Padding(18,8,18,10);
            confirmation.TextChanged+=delegate { remove.Enabled=!pending&&!consumed&&confirmation.Text=="同意删除"; };
            remove.Click+=async delegate {
                if(pending||consumed||confirmation.Text!="同意删除")return;
                pending=true;consumed=true;remove.Enabled=false;cancel.Enabled=false;confirmation.Enabled=false;status.Text="正在由后台重新核对服务器状态与目录，随后删除整个文件夹…";Ui.Role(status,"warning");
                try {
                    var result=await submit(Ui.Obj("id",Ui.Text(preview,"id"),"path",Ui.Text(preview,"path"),"token",Ui.Text(preview,"token"),"confirmation",confirmation.Text));
                    if(!Ui.Bool(result,"deleted"))throw new InvalidOperationException(Ui.Text(result,"message","后台尚未确认文件夹已删除；请检查服务器列表与目录。"));
                    Deleted=true;status.Text=Ui.Text(result,"message","服务器文件夹已删除。");pending=false;DialogResult=DialogResult.OK;Close();
                } catch(Exception error) {
                    status.Text="删除未完成："+error.Message+"\r\n本次确认已失效，请取消后重新发起检查。";Ui.Role(status,"danger");
                } finally {pending=false;if(!IsDisposed){cancel.Enabled=true;remove.Enabled=false;confirmation.Enabled=false;}}
            };
            FormClosing+=delegate(object sender,FormClosingEventArgs e){if(pending)e.Cancel=true;};
            Controls.Add(scroll);Controls.Add(status);Controls.Add(buttons);CancelButton=cancel;AcceptButton=cancel;Ui.ApplyTheme(this);Shown+=delegate{cancel.Select();};
        }
    }

    internal sealed partial class NativeMainForm {
        private bool serverSelectionActionBusy;
        private static Dictionary<string,object> ServerSelectionRowAt(DataGridView grid,int rowIndex) {
            if(rowIndex<0||rowIndex>=grid.Rows.Count||grid.Rows[rowIndex].IsNewRow)return Ui.Obj();
            var row=Ui.Map(grid.Rows[rowIndex].Tag);return row.Count==0?Ui.Obj():new Dictionary<string,object>(row);
        }
        private void AttachServerSelectionMenu(DataGridView grid,Func<string> workspaceError,Func<Task> refresh) {
            ContextMenuStrip current=null;
            Action<Dictionary<string,object>,Point> show=delegate(Dictionary<string,object> row,Point point){
                if(grid.IsDisposed||row.Count==0||Ui.Text(row,"id").Length==0)return;
                if(current!=null){current.Dispose();current=null;}
                var menu=BuildServerSelectionMenu(row,workspaceError(),refresh);current=menu;
                menu.Closed+=delegate{
                    if(Object.ReferenceEquals(current,menu))current=null;
                    // ToolStrip closes its popup BEFORE dispatching the clicked
                    // item's action. Dispose on the next UI message so mouse,
                    // keyboard and accessibility invocations can finish.
                    if(grid.IsHandleCreated&&!grid.IsDisposed)grid.BeginInvoke((Action)(delegate{if(!menu.IsDisposed)menu.Dispose();}));
                    else if(!menu.IsDisposed)menu.Dispose();
                };Ui.ApplyTheme(menu);menu.Show(grid,point);
            };
            grid.MouseUp+=delegate(object sender,MouseEventArgs e){
                if(e.Button!=MouseButtons.Right)return;var hit=grid.HitTest(e.X,e.Y);
                if(hit.RowIndex<0){if(current!=null)current.Close();grid.ClearSelection();grid.CurrentCell=null;return;}
                var row=ServerSelectionRowAt(grid,hit.RowIndex);if(row.Count==0)return;
                grid.ClearSelection();grid.CurrentCell=grid.Rows[hit.RowIndex].Cells[Math.Max(0,hit.ColumnIndex)];grid.Rows[hit.RowIndex].Selected=true;show(row,e.Location);
            };
            grid.KeyDown+=delegate(object sender,KeyEventArgs e){
                if(e.KeyCode!=Keys.Apps&&!(e.Shift&&e.KeyCode==Keys.F10))return;e.Handled=true;e.SuppressKeyPress=true;
                if(grid.CurrentRow==null||!grid.CurrentRow.Selected)return;
                var row=ServerSelectionRowAt(grid,grid.CurrentRow.Index);var rectangle=grid.GetRowDisplayRectangle(grid.CurrentRow.Index,false);show(row,new Point(Math.Max(8,rectangle.Left+18),Math.Max(8,rectangle.Top+Math.Min(rectangle.Height,28))));
            };
            grid.Disposed+=delegate{if(current!=null){current.Dispose();current=null;}};
        }
        private ContextMenuStrip BuildServerSelectionMenu(Dictionary<string,object> source,string workspaceError,Func<Task> refresh) {
            // Copy the object identity at invocation. A polling refresh must never
            // redirect an already open menu to a newly selected grid row.
            var row=new Dictionary<string,object>(source);string account=StartupRecoveryAccount();RpcClient origin=rpc;
            var state=ServerSelectionAvailability.Read(row,workspaceError,serverSelectionActionBusy);
            var menu=new ServerSelectionContextMenu();
            var title=new ToolStripMenuItem(Ui.Text(row,"name","服务器")) {Name="ServerMenuTarget",Enabled=false};menu.Items.Add(title);menu.Items.Add(new ToolStripSeparator());
            Action<string,string,bool,string> add=delegate(string name,string text,bool enabled,string action){
                var item=new ToolStripMenuItem(text){Name=name,Enabled=enabled,Tag=Ui.Text(row,"id")};
                if(name=="ServerMenuDelete"){
                    item.ForeColor=ServerSelectionMenuRenderer.PermanentDeleteRed;
                    item.ForeColorChanged+=delegate{if(item.ForeColor!=ServerSelectionMenuRenderer.PermanentDeleteRed)item.ForeColor=ServerSelectionMenuRenderer.PermanentDeleteRed;};
                }
                item.ToolTipText=enabled?"目标："+Ui.Text(row,"name")+(action=="delete"?"；将先核对完整目录并要求输入确认短语。":""):state.Reason.Length>0?state.Reason:"当前服务器状态或版本不支持此操作。";
                item.Click+=async delegate{if(serverSelectionActionBusy)return;serverSelectionActionBusy=true;try{await Safe(async delegate{if(!authenticated||StartupRecoveryAccount()!=account||rpc!=origin)throw new InvalidOperationException("当前连接或账号已经改变，请重新选择服务器。");await RunServerSelectionActionAsync(row,action,refresh,account,origin);});}finally{serverSelectionActionBusy=false;}};menu.Items.Add(item);
            };
            add("ServerMenuManage","进入服务器管理",state.CanEnter,"dashboard");add("ServerMenuConsole","控制台",state.CanEnter,"console");
            menu.Items.Add(new ToolStripSeparator());
            add("ServerMenuStart","启动服务器",state.CanStart,"start");add("ServerMenuStop","正常停服…",state.CanStop,"stop");add("ServerMenuSave","保存世界",state.CanSave,"save");
            menu.Items.Add(new ToolStripSeparator());
            add("ServerMenuBackups","备份管理",state.CanEnter,"backups");add("ServerMenuSettings","服务器设置",state.CanEnter,"settings");
            add("ServerMenuOpenFolder","打开本机目录",state.Unlocked&&Ui.Text(row,"path").Length>0&&!serverSelectionActionBusy,"folder");
            add("ServerMenuCopyPath","复制服务器路径",Ui.Text(row,"path").Length>0&&!serverSelectionActionBusy,"copy");add("ServerMenuRefresh","刷新状态",!serverSelectionActionBusy,"refresh");
            menu.Items.Add(new ToolStripSeparator());
            bool removable=state.CanDelete;
            add("ServerMenuRemove","从面板移除（保留文件）…",removable,"remove");add("ServerMenuDelete","永久删除服务器…",state.CanDelete,"delete");
            return menu;
        }
        private async Task RunServerSelectionActionAsync(Dictionary<string,object> row,string action,Func<Task> refresh,string account,RpcClient origin) {
            string id=Ui.Text(row,"id"),name=Ui.Text(row,"name"),path=Ui.Text(row,"path");
            if(action=="refresh"){await refresh();return;}
            if(action=="copy"){Clipboard.SetText(path);SetStatus("已复制“"+name+"”的服务器路径。");return;}
            if(action=="folder"){if(!Directory.Exists(path))throw new InvalidOperationException("服务器目录不存在，请先检查或更改目录。");Process.Start(new ProcessStartInfo("explorer.exe",NativeProgram.Quote(Path.GetFullPath(path))){UseShellExecute=true});return;}
            if(action=="remove"){await RemoveServerSelectionBindingAsync(row,refresh);return;}
            if(action=="delete"){await DeleteServerSelectionAsync(row,account,origin);return;}
            await EnterServerAsync(id);
            if(!authenticated||StartupRecoveryAccount()!=account||rpc!=origin||selectedServerId!=id)throw new InvalidOperationException("当前连接、账号或服务器已经改变，请重新选择目标。");
            if(action=="dashboard")return;
            if(action=="console"||action=="backups"||action=="settings"){await NavigateAsync(action);return;}
            var snapshot=await Call("status",null,id);var state=ServerPresentation.Read(snapshot);
            if(!authenticated||StartupRecoveryAccount()!=account||rpc!=origin||selectedServerId!=id||!inServerManagement)throw new InvalidOperationException("当前连接、账号或服务器已经改变，本次操作未提交。");
            if(!state.Known||!state.OperationKnown||state.Busy||state.Countdown||state.Starting)throw new InvalidOperationException("服务器状态未知或正在执行其他操作，请在管理页确认状态后再试。");
            if(action=="save"&&!PlatformUiProfile.Read(snapshot).Allows("save_world"))throw new InvalidOperationException("当前平台没有世界保存操作。");if(action=="start"){if(state.Running)throw new InvalidOperationException("这台服务器已经运行。");await StartServerWithRecoveryAsync();return;}
            if(action=="stop"){
                if(!state.Running)throw new InvalidOperationException("这台服务器已经停止。");
                if(!Ui.Confirm(this,"确认正常关闭“"+name+"”？在线玩家会断开连接。服务器将通过正常停服流程保存并退出。","正常停服"))return;
            } else if(action=="save"&&!state.Ready)throw new InvalidOperationException("服务器尚未就绪，不能提交保存世界命令。");
            if(!authenticated||StartupRecoveryAccount()!=account||rpc!=origin||selectedServerId!=id)throw new InvalidOperationException("目标上下文已经改变，本次操作未提交。");
            await Call("server.action",Ui.Obj("action",action),id);await RefreshCurrentPageAsync();
        }
        private async Task RemoveServerSelectionBindingAsync(Dictionary<string,object> row,Func<Task> refresh) {
            string id=Ui.Text(row,"id");
            if(!AdminConfirm("仅从面板列表移除“"+Ui.Text(row,"name")+"”的绑定？\r\n服务器整个文件夹、世界存档、模组与配置都会保留。"))return;
            await Call("servers.remove",Ui.Obj("id",id),id);await RefreshServers();await refresh();
        }
        private async Task DeleteServerSelectionAsync(Dictionary<string,object> row,string account,RpcClient origin) {
            string id=Ui.Text(row,"id");var preview=await Call("servers.delete.preview",Ui.Obj("id",id),id);
            if(!authenticated||StartupRecoveryAccount()!=account||rpc!=origin)throw new InvalidOperationException("当前连接或账号已经改变，删除检查已取消。");
            if(Ui.Text(preview,"id")!=id||String.IsNullOrWhiteSpace(Ui.Text(preview,"path"))||String.IsNullOrWhiteSpace(Ui.Text(preview,"token")))throw new InvalidOperationException("后台未返回有效的删除预览；未删除任何文件。");
            using(var dialog=new ServerDeleteDialog(preview,Font,async delegate(Dictionary<string,object> payload){
                if(!authenticated||StartupRecoveryAccount()!=account||rpc!=origin)throw new InvalidOperationException("当前连接或账号已经改变，删除未提交。");
                return await Call("servers.delete",payload,id);
            })) {if(dialog.ShowDialog(this)!=DialogResult.OK||!dialog.Deleted)return;}
            await RefreshServers();await ShowServerSelectionAsync();SetStatus("“"+Ui.Text(preview,"name",Ui.Text(row,"name"))+"”的服务器文件夹已永久删除。");
        }
    }
}

