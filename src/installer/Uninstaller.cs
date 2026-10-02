// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Management;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;
using QiZhang.NativePanel;
using QiZhang.Shared;

namespace QiZhang.Installer {
    internal sealed class UninstallPlan {
        internal string Root;
        internal bool DeleteData, DeleteServers;
        internal readonly Dictionary<string,string> Files=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        internal readonly HashSet<string> Directories=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        internal readonly List<string> Preserved=new List<string>();
    }
    internal static class PackageUninstaller {
        internal const string Executable="卸载七章控制面板.exe";
        private const string UninstallRegistry=@"Software\Microsoft\Windows\CurrentVersion\Uninstall";
        private static readonly string[] RootFiles={InstallerProgram.MainExe,InstallerProgram.MainExe+".config",Executable,"native-host.py","QiZhang.ico","portable.flag","edition.json","七章控制面板-使用说明.md","免责说明.md","第三方组件.md","本次更新说明.md"};
        internal static bool Within(string path,string root){return Path.GetFullPath(path).StartsWith(root.TrimEnd('\\','/')+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase);}
        internal static void CheckNoReparse(string path){
            string current=Path.GetFullPath(path);
            while(!String.IsNullOrEmpty(current)){
                try {if((File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0)throw new InstallFailure(2,"检测到符号链接或目录联接，已停止操作："+current);}
                catch(FileNotFoundException){}catch(DirectoryNotFoundException){}
                DirectoryInfo parent=Directory.GetParent(current);if(parent==null)break;current=parent.FullName;
            }
        }
        internal static string ValidateRoot(string target){
            if(String.IsNullOrWhiteSpace(target)||!Path.IsPathRooted(target)||target.StartsWith("\\\\",StringComparison.Ordinal))throw new InstallFailure(2,"请选择本机磁盘中的完整面板目录。");
            string full=Path.GetFullPath(target.Trim()).TrimEnd('\\','/');string drive=Path.GetPathRoot(full);
            if(drive.Length!=3||drive[1]!=':'||String.Equals(full,drive.TrimEnd('\\','/'),StringComparison.OrdinalIgnoreCase))throw new InstallFailure(2,"不能操作磁盘根目录。");
            foreach(string segment in full.Substring(drive.Length).Split('\\','/'))if(segment.Length==0||segment=="."||segment==".."||segment.EndsWith(" ")||segment.EndsWith(".")||segment.IndexOfAny(Path.GetInvalidFileNameChars())>=0)throw new InstallFailure(2,"目录格式不安全。");
            foreach(var special in new[]{Environment.SpecialFolder.Windows,Environment.SpecialFolder.UserProfile,Environment.SpecialFolder.DesktopDirectory,Environment.SpecialFolder.MyDocuments,Environment.SpecialFolder.LocalApplicationData,Environment.SpecialFolder.ApplicationData,Environment.SpecialFolder.ProgramFiles,Environment.SpecialFolder.ProgramFilesX86,Environment.SpecialFolder.Programs,Environment.SpecialFolder.Startup}){
                string reserved=Environment.GetFolderPath(special);if(reserved.Length==0)continue;
                if(String.Equals(full,reserved.TrimEnd('\\','/'),StringComparison.OrdinalIgnoreCase)||(special==Environment.SpecialFolder.Windows&&Within(full,reserved)))throw new InstallFailure(2,"不能操作系统目录或用户资料根目录。");
            }
            CheckNoReparse(full);return full;
        }
        private static string Child(string root,string relative){
            if(String.IsNullOrWhiteSpace(relative)||Path.IsPathRooted(relative)||relative.IndexOf(':')>=0)throw new InstallFailure(2,"卸载清单包含非法路径。");
            foreach(string part in relative.Replace('\\','/').Split('/'))if(part.Length==0||part=="."||part==".."||part.EndsWith(".")||part.EndsWith(" ")||part.IndexOfAny(Path.GetInvalidFileNameChars())>=0)throw new InstallFailure(2,"卸载清单包含不安全路径。");
            string path=Path.GetFullPath(Path.Combine(root,relative.Replace('/',Path.DirectorySeparatorChar)));if(!Within(path,root))throw new InstallFailure(2,"卸载路径越界，已拒绝操作。");CheckNoReparse(path);return path;
        }
        private static bool ProgramFile(string relative){
            string name=relative.Replace('\\','/');if(RootFiles.Contains(name,StringComparer.OrdinalIgnoreCase))return true;
            if(name.StartsWith("runtime/",StringComparison.OrdinalIgnoreCase))return new[]{".exe",".dll",".pyd",".zip","._pth",".cat",".txt"}.Contains(Path.GetExtension(name),StringComparer.OrdinalIgnoreCase);
            if(name.StartsWith("backend/",StringComparison.OrdinalIgnoreCase))return new[]{".py",".ps1",".cmd",".bat",".java",".class",".jar",".json",".md",".txt",".mf"}.Contains(Path.GetExtension(name),StringComparer.OrdinalIgnoreCase);
            return false;
        }
        private static string Hash(string path){using(var sha=SHA256.Create())using(var file=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read))return BitConverter.ToString(sha.ComputeHash(file)).Replace("-","").ToLowerInvariant();}
        private static void AddFile(UninstallPlan plan,string path){CheckNoReparse(path);if(File.Exists(path)){using(var probe=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.None)){}plan.Files[path]=Hash(path);}string parent=Path.GetDirectoryName(path);while(Within(parent,plan.Root)){plan.Directories.Add(parent);parent=Path.GetDirectoryName(parent);}}
        private static void AddTree(UninstallPlan plan,string directory){
            CheckNoReparse(directory);if(!Directory.Exists(directory))return;
            if(!Within(directory,plan.Root))throw new InstallFailure(2,"数据目录越界，已拒绝操作。");
            foreach(string file in Directory.GetFiles(directory))AddFile(plan,file);
            foreach(string child in Directory.GetDirectories(directory))AddTree(plan,child);
            plan.Directories.Add(directory);
        }
        internal static UninstallPlan Prepare(string target,bool deleteData,bool deleteServers){
            string root=ValidateRoot(target),manifest=Child(root,"manifest.sha256.json");
            if(!Directory.Exists(root)||!File.Exists(manifest))throw new InstallFailure(2,"所选目录没有本产品文件清单，不能自动卸载。请保留数据并重新安装当前版本后再卸载。");
            if(new FileInfo(manifest).Length>8*1024*1024)throw new InstallFailure(2,"程序文件清单过大。");
            var rows=new JavaScriptSerializer{MaxJsonLength=8*1024*1024}.DeserializeObject(File.ReadAllText(manifest,Encoding.UTF8)) as object[];
            if(rows==null||rows.Length==0||rows.Length>20000)throw new InstallFailure(2,"程序文件清单无效。");
            var plan=new UninstallPlan{Root=root,DeleteData=deleteData,DeleteServers=deleteServers};bool product=false;var unique=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(object raw in rows){
                var row=raw as Dictionary<string,object>;object rawPath,rawHash;if(row==null||!row.TryGetValue("path",out rawPath)||!row.TryGetValue("sha256",out rawHash))throw new InstallFailure(2,"程序文件清单字段无效。");
                string relative=Convert.ToString(rawPath),expected=Convert.ToString(rawHash).ToLowerInvariant(),path=Child(root,relative);
                if(!unique.Add(path)||expected.Length!=64||expected.Any(c=>!Uri.IsHexDigit(c)))throw new InstallFailure(2,"程序文件清单重复或哈希无效。");
                if(!ProgramFile(relative))throw new InstallFailure(2,"程序文件清单包含非程序目录，已拒绝卸载："+relative);
                if(relative.Equals(InstallerProgram.MainExe,StringComparison.OrdinalIgnoreCase))product=true;
                if(File.Exists(path)){if(Hash(path)==expected)AddFile(plan,path);else plan.Preserved.Add(relative+"（文件已被修改）");}
            }
            if(!product||(!File.Exists(Path.Combine(root,InstallerProgram.MainExe))&&!File.Exists(Path.Combine(root,"native-host.py"))))throw new InstallFailure(2,"无法确认这是七章控制面板目录。");
            if(deleteData){foreach(string folder in new[]{"data","profiles"})AddTree(plan,Child(root,folder));foreach(string file in new[]{"accounts.json","native-state.json"})AddFile(plan,Child(root,file));}
            if(deleteServers)AddTree(plan,Child(root,"mcSever"));
            AddFile(plan,manifest);CheckProcesses(root);ProbeServerLocks(Path.Combine(root,"mcSever"));return plan;
        }
        private static void ProbeServerLocks(string directory){
            CheckNoReparse(directory);if(!Directory.Exists(directory))return;
            foreach(string marker in new[]{".qizhang-server-starting.flag",".qizhang-panel-maintenance.flag"})if(File.Exists(Path.Combine(directory,marker)))throw new InstallFailure(3,"服务器仍有启动或维护标记，请先在面板确认操作已结束并正常停服："+directory);
            string session=Path.Combine(directory,"session.lock");if(File.Exists(session)){CheckNoReparse(session);try{using(var probe=new FileStream(session,FileMode.Open,FileAccess.Read,FileShare.None)){}}catch(IOException error){throw new InstallFailure(3,"服务器世界文件仍被占用，请先正常停服："+session,error);}}
            foreach(string child in Directory.GetDirectories(directory))ProbeServerLocks(child);
        }
        private static bool Mentions(string text,string root){if(String.IsNullOrEmpty(text))return false;string value=text.Replace('\\','/').ToLowerInvariant(),path=root.Replace('\\','/').TrimEnd('/').ToLowerInvariant();int start=value.IndexOf(path,StringComparison.Ordinal);while(start>=0){int end=start+path.Length;if(end==value.Length||value[end]=='/'||value[end]=='"'||Char.IsWhiteSpace(value[end]))return true;start=value.IndexOf(path,start+1,StringComparison.Ordinal);}return false;}
        private static void CheckProcesses(string root){
            try{
                using(var search=new ManagementObjectSearcher("SELECT ProcessId,Name,ExecutablePath,CommandLine FROM Win32_Process"))using(var rows=search.Get()){
                    int own=Process.GetCurrentProcess().Id;
                    foreach(ManagementObject row in rows)using(row){int pid=Convert.ToInt32(row["ProcessId"]);if(pid==own)continue;string executable=Convert.ToString(row["ExecutablePath"]),command=Convert.ToString(row["CommandLine"]);
                        if(Mentions(executable,root)||Mentions(command,root))throw new InstallFailure(3,"相关程序仍在运行（PID "+pid+"，"+Convert.ToString(row["Name"])+"）。请正常关闭服务器，并从系统托盘退出面板后再卸载。");
                    }
                }
            }catch(InstallFailure){throw;}catch(Exception error){throw new InstallFailure(3,"无法检查运行进程，已停止卸载："+error.Message,error);}
        }
        internal static List<string> Execute(UninstallPlan plan,bool cleanRegistration){
            if(plan==null)throw new ArgumentNullException("plan");string root=ValidateRoot(plan.Root);CheckProcesses(root);ProbeServerLocks(Path.Combine(root,"mcSever"));
            // Verify every selected file before any deletion; never recurse during delete.
            foreach(var file in plan.Files){if(!Within(file.Key,root))throw new InstallFailure(2,"卸载文件越界。");CheckNoReparse(file.Key);if(!File.Exists(file.Key))continue;using(var probe=new FileStream(file.Key,FileMode.Open,FileAccess.Read,FileShare.None)){}if(Hash(file.Key)!=file.Value)throw new InstallFailure(3,"文件在确认后已变化，已停止卸载："+file.Key);}
            foreach(string directory in plan.Directories){if(!Within(directory,root))throw new InstallFailure(2,"卸载目录越界。");CheckNoReparse(directory);}
            if(cleanRegistration)RemoveRegistration(root);
            string manifest=Path.Combine(root,"manifest.sha256.json");
            foreach(var file in plan.Files.Where(value=>!Same(value.Key,manifest))){CheckNoReparse(file.Key);if(File.Exists(file.Key))File.Delete(file.Key);}
            CheckNoReparse(manifest);if(File.Exists(manifest))File.Delete(manifest);
            foreach(string directory in plan.Directories.OrderByDescending(value=>value.Length)){CheckNoReparse(directory);if(Directory.Exists(directory)&&Directory.GetFileSystemEntries(directory).Length==0)Directory.Delete(directory,false);}
            return new List<string>(plan.Preserved);
        }
        private static string RegistrationName(string target){using(var sha=SHA256.Create())return "QiZhangControlPanel-"+BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(target.ToUpperInvariant()))).Replace("-","").Substring(0,16);}
        internal static void Register(string target){
            string root=ValidateRoot(target),uninstaller=Path.Combine(root,Executable);if(!File.Exists(uninstaller))throw new IOException("独立卸载程序不存在。");
            using(var key=Registry.CurrentUser.CreateSubKey(UninstallRegistry+"\\"+RegistrationName(root))){key.SetValue("DisplayName","七章控制面板 · "+InstallerProgram.EditionLabel);key.SetValue("Publisher","EeryFrank");key.SetValue("DisplayVersion",Assembly.GetExecutingAssembly().GetName().Version.ToString(3));key.SetValue("InstallLocation",root);key.SetValue("UninstallString","\""+uninstaller+"\" --uninstall \""+root+"\"");key.SetValue("DisplayIcon",Path.Combine(root,InstallerProgram.MainExe));key.SetValue("NoModify",1,RegistryValueKind.DWord);key.SetValue("NoRepair",1,RegistryValueKind.DWord);}
        }
        private static object Com(object obj,string name,BindingFlags kind,params object[] args){return obj.GetType().InvokeMember(name,kind,null,obj,args);}
        private static bool Same(string one,string two){try{return String.Equals(Path.GetFullPath(one).TrimEnd('\\','/'),Path.GetFullPath(two).TrimEnd('\\','/'),StringComparison.OrdinalIgnoreCase);}catch{return false;}}
        private static void Release(object value){if(value!=null&&Marshal.IsComObject(value))Marshal.FinalReleaseComObject(value);}
        private static void RemoveRegistration(string root){
            string main=Path.Combine(root,InstallerProgram.MainExe),uninstaller=Path.Combine(root,Executable);
            // Scheduled tasks are removed only after checking both product name and
            // their actual executable target. No arbitrary task-name deletion.
            object service=null,folder=null,tasks=null;
            try{service=Activator.CreateInstance(Type.GetTypeFromProgID("Schedule.Service",true));Com(service,"Connect",BindingFlags.InvokeMethod);folder=Com(service,"GetFolder",BindingFlags.InvokeMethod,"\\");tasks=Com(folder,"GetTasks",BindingFlags.InvokeMethod,0);int count=Convert.ToInt32(Com(tasks,"Count",BindingFlags.GetProperty));
                for(int i=count;i>=1;i--){object task=null,definition=null,actions=null,action=null;try{task=Com(tasks,"Item",BindingFlags.GetProperty,i);string name=Convert.ToString(Com(task,"Name",BindingFlags.GetProperty));if(!name.StartsWith("QiZhangControlPanel-",StringComparison.OrdinalIgnoreCase))continue;definition=Com(task,"Definition",BindingFlags.GetProperty);actions=Com(definition,"Actions",BindingFlags.GetProperty);if(Convert.ToInt32(Com(actions,"Count",BindingFlags.GetProperty))!=1)continue;action=Com(actions,"Item",BindingFlags.GetProperty,1);bool owned=Convert.ToInt32(Com(action,"Type",BindingFlags.GetProperty))==0&&Same(Convert.ToString(Com(action,"Path",BindingFlags.GetProperty)),main);if(owned)Com(folder,"DeleteTask",BindingFlags.InvokeMethod,name,0);}finally{Release(action);Release(actions);Release(definition);Release(task);}}
            }catch(Exception error){throw new InstallFailure(3,"无法检查或移除此安装的开机任务，请检查权限后重试。程序文件尚未删除。"+error.Message,error);}finally{Release(tasks);Release(folder);Release(service);}
            object shell=null;try{shell=Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell",true));foreach(var special in new[]{Environment.SpecialFolder.DesktopDirectory,Environment.SpecialFolder.Startup,Environment.SpecialFolder.Programs}){string directory=Environment.GetFolderPath(special);if(!Directory.Exists(directory))continue;foreach(string link in Directory.GetFiles(directory,"*.lnk")){string name=Path.GetFileName(link);if(!name.StartsWith("七章控制面板",StringComparison.OrdinalIgnoreCase)&&!name.StartsWith("卸载七章控制面板",StringComparison.OrdinalIgnoreCase)&&!name.StartsWith("QiZhangControlPanel-",StringComparison.OrdinalIgnoreCase))continue;CheckNoReparse(link);object shortcut=null;try{shortcut=Com(shell,"CreateShortcut",BindingFlags.InvokeMethod,link);string executable=Convert.ToString(Com(shortcut,"TargetPath",BindingFlags.GetProperty));if(Same(executable,main)||Same(executable,uninstaller))File.Delete(link);}finally{Release(shortcut);}}}}finally{Release(shell);}
            using(var key=Registry.CurrentUser.OpenSubKey(InstallationLocation.RegistryPath,false)){if(key!=null&&Same(Convert.ToString(key.GetValue("InstallPath","")),root)){key.Close();Registry.CurrentUser.DeleteSubKeyTree(InstallationLocation.RegistryPath,false);}}
            using(var uninstall=Registry.CurrentUser.OpenSubKey(UninstallRegistry,true)){if(uninstall!=null)foreach(string name in uninstall.GetSubKeyNames()){if(!name.StartsWith("QiZhangControlPanel-",StringComparison.OrdinalIgnoreCase))continue;bool owned=false;using(var key=uninstall.OpenSubKey(name,false))owned=key!=null&&Same(Convert.ToString(key.GetValue("InstallLocation","")),root);if(owned)uninstall.DeleteSubKeyTree(name,false);}}
            using(var run=Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run",true)){if(run!=null)foreach(string name in run.GetValueNames()){if(!name.StartsWith("QiZhangControlPanel",StringComparison.OrdinalIgnoreCase)&&!name.StartsWith("七章控制面板",StringComparison.OrdinalIgnoreCase))continue;string command=run.GetValue(name,"") as string;if(command!=null&&(command.StartsWith("\""+main+"\"",StringComparison.OrdinalIgnoreCase)||Same(command,main)))run.DeleteValue(name,false);}}
        }
    }
    internal static class UninstallerProgram {
        [DllImport("user32.dll")]private static extern bool SetProcessDPIAware();
        [STAThread]private static int Main(string[] args){if(args.Length==0)return Run(AppDomain.CurrentDomain.BaseDirectory);if(args.Length==2&&args[0]=="--uninstall")return Run(args[1]);return 2;}
        internal static int Run(string target){
            try{
                string root=PackageUninstaller.ValidateRoot(target);
                if(PackageUninstaller.Within(Application.ExecutablePath,root)){
                    string cache=Path.Combine(Path.GetTempPath(),"QiZhangPanel-uninstall");string stage=Path.Combine(cache,Guid.NewGuid().ToString("N"));Directory.CreateDirectory(stage);string helper=Path.Combine(stage,PackageUninstaller.Executable);File.Copy(Application.ExecutablePath,helper,false);if(File.Exists(Application.ExecutablePath+".config"))File.Copy(Application.ExecutablePath+".config",helper+".config",false);
                    Process.Start(new ProcessStartInfo(helper,"--uninstall \""+root+"\""){UseShellExecute=false,WorkingDirectory=stage,WindowStyle=ProcessWindowStyle.Normal});return 0;
                }
                SetProcessDPIAware();Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);AppTheme.Initialize(InstallationOptions.ReadThemeMode(root),InstallationOptions.ReadThemeAccent(root));try{Application.Run(new UninstallerForm(root));}finally{AppTheme.Shutdown();}return 0;
            }catch(Exception error){MessageBox.Show(error.Message,"卸载未开始",MessageBoxButtons.OK,MessageBoxIcon.Warning);return 2;}
        }
    }
    internal sealed class UninstallerForm:Form {
        private readonly string root;
        private readonly CheckBox confirm,deleteData,deleteServers;
        private readonly TextBox dataPhrase,serversPhrase;
        private readonly Button remove;
        private readonly Label state;
        private bool busy;
        internal UninstallerForm(string target){
            root=PackageUninstaller.ValidateRoot(target);Text="卸载七章控制面板";ClientSize=new Size(740,610);MinimumSize=new Size(660,580);StartPosition=FormStartPosition.CenterParent;Font=Ui.BodyFont;Icon=Icon.ExtractAssociatedIcon(typeof(UninstallerForm).Assembly.Location);
            var fields=Ui.Fields();var warning=new Label{Name="UninstallWarning",Text="卸载和删除数据无法撤销。请先正常停服并退出面板，确认下方目标与删除范围。",AutoSize=true,MaximumSize=new Size(500,0),Font=new Font(Font,FontStyle.Bold)};Ui.Role(warning,"danger");Ui.Field(fields,"请仔细确认",warning);
            Ui.Field(fields,"绝对目标目录",new TextBox{Name="UninstallTarget",Text=root,ReadOnly=true,Multiline=true,Height=52});
            Ui.Field(fields,"默认卸载范围",new Label{Text="仅删除文件清单中属于七章控制面板的程序文件。保留账号配置、mcSever 服务器、其他文件及所有外部服务器；不会删除安装根目录。",AutoSize=true,MaximumSize=new Size(500,0)});
            deleteData=new CheckBox{Name="DeletePanelData",Text="同时删除安装目录内的面板账号和配置",AutoSize=true};dataPhrase=new TextBox{Name="ConfirmDeletePanelData",Enabled=false};
            deleteServers=new CheckBox{Name="DeleteInternalServers",Text="同时删除安装目录内 mcSever 的服务器数据",AutoSize=true};serversPhrase=new TextBox{Name="ConfirmDeleteInternalServers",Enabled=false};
            Ui.Field(fields,"可选删除",deleteData);Ui.Field(fields,"输入：删除账号配置",dataPhrase);Ui.Field(fields,"可选删除",deleteServers);Ui.Field(fields,"输入：删除内部服务器",serversPhrase);
            Ui.Field(fields,"外部目录",new Label{Text="自定义到安装目录以外的账号数据和服务器均保留。仅移除路径确实指向本安装的七章开机项、任务和快捷方式。",AutoSize=true,MaximumSize=new Size(500,0)});
            confirm=new CheckBox{Name="ConfirmUninstall",Text="我已确认目标目录和上述删除范围",AutoSize=true};Ui.Field(fields,"最终确认",confirm);
            state=new Label{Name="UninstallState",Text="尚未执行任何卸载操作。",AutoSize=true,MaximumSize=new Size(500,0)};Ui.Field(fields,"状态",state);
            var scroll=new Panel{Dock=DockStyle.Fill,AutoScroll=true,Padding=new Padding(16)};scroll.Controls.Add(fields);
            remove=Ui.Button("确认卸载",UninstallAsync);remove.Name="ConfirmUninstallButton";Ui.Role(remove,"danger");remove.Enabled=false;var cancel=Ui.Button("取消",delegate{if(!busy)Close();return Task.CompletedTask;});var actions=Ui.Toolbar(remove,cancel);actions.Dock=DockStyle.Bottom;actions.Padding=new Padding(20,8,20,8);Controls.Add(scroll);Controls.Add(actions);CancelButton=cancel;
            Action update=delegate{dataPhrase.Enabled=deleteData.Checked&&!busy;serversPhrase.Enabled=deleteServers.Checked&&!busy;remove.Enabled=!busy&&confirm.Checked&&(!deleteData.Checked||dataPhrase.Text=="删除账号配置")&&(!deleteServers.Checked||serversPhrase.Text=="删除内部服务器");};confirm.CheckedChanged+=delegate{update();};deleteData.CheckedChanged+=delegate{update();};deleteServers.CheckedChanged+=delegate{update();};dataPhrase.TextChanged+=delegate{update();};serversPhrase.TextChanged+=delegate{update();};remove.EnabledChanged+=delegate{if(remove.Enabled&&(!confirm.Checked||busy||(deleteData.Checked&&dataPhrase.Text!="删除账号配置")||(deleteServers.Checked&&serversPhrase.Text!="删除内部服务器")))remove.Enabled=false;};
            FormClosing+=delegate(object sender,FormClosingEventArgs e){if(busy)e.Cancel=true;};Ui.ApplyTheme(this);
        }
        private async Task UninstallAsync(){
            if(busy||!confirm.Checked||(deleteData.Checked&&dataPhrase.Text!="删除账号配置")||(deleteServers.Checked&&serversPhrase.Text!="删除内部服务器"))return;
            bool data=deleteData.Checked,servers=deleteServers.Checked;busy=true;confirm.Enabled=deleteData.Enabled=deleteServers.Enabled=dataPhrase.Enabled=serversPhrase.Enabled=false;
            try{
                state.Text="正在检查文件清单和运行状态…";var plan=await Task.Run(delegate{return PackageUninstaller.Prepare(root,data,servers);});
                string message="目标：\r\n"+root+"\r\n\r\n将删除 "+plan.Files.Count+" 个已确认文件。\r\n账号配置："+(data?"删除安装目录内的账号配置":"保留")+"\r\nmcSever："+(servers?"删除安装目录内的服务器数据":"保留")+"\r\n外部服务器和安装根目录始终保留。\r\n\r\n确认继续？";
                if(!Ui.Confirm(this,message,"最后确认卸载")){state.Text="已取消，未删除文件。";return;}
                state.Text="正在卸载…";var preserved=await Task.Run(delegate{return PackageUninstaller.Execute(plan,true);});state.Text="卸载完成。安装根目录和未选中的数据已保留。"+(preserved.Count>0?"另保留 "+preserved.Count+" 个被修改的文件。":"");confirm.Checked=false;
            }finally{busy=false;confirm.Enabled=deleteData.Enabled=deleteServers.Enabled=true;dataPhrase.Enabled=deleteData.Checked;serversPhrase.Enabled=deleteServers.Checked;}
        }
    }
}
