// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    // The host owns platform policy. The four legacy profiles only preserve
    // compatibility with older hosts; unknown engines never inherit Java policy.
    internal sealed class PlatformUiProfile {
        internal Dictionary<string,object> Data;
        internal string Id,Label,Family,Runtime,ConfigFile,Protocol,InstallMethod,OfficialUrl;
        internal static PlatformUiProfile Read(Dictionary<string,object> source) {
            object raw;var data=source??Ui.Obj();
            if(data.TryGetValue("platform_profile",out raw))data=Ui.Map(raw);
            else if(data.TryGetValue("profile",out raw))data=Ui.Map(raw);
            else if(!data.ContainsKey("capabilities")&&data.TryGetValue("server",out raw))return Read(Ui.Map(raw));
            if(source!=null&&!Object.ReferenceEquals(source,data)){
                data=new Dictionary<string,object>(data);
                foreach(string key in new[]{"install_method","official_url","editable_properties"})if(source.TryGetValue(key,out raw))data[key]=raw;
            }
            string id=Ui.Text(data,"platform",Ui.Text(data,"id",Ui.Text(source??Ui.Obj(),"platform"))).ToLowerInvariant();
            bool legacy=Array.IndexOf(new[]{"vanilla","neoforge","forge","fabric"},id)>=0;
            return new PlatformUiProfile {Data=data,Id=id,Label=Ui.Text(data,"label",Ui.Text(data,"name",id.Length>0?id:"未识别平台")),Family=Ui.Text(data,"family",legacy?"java":"custom"),Runtime=Ui.Text(data,"runtime",legacy?"java":"custom"),ConfigFile=Ui.Text(data,"config_file",legacy?"server.properties":""),Protocol=Ui.Text(data,"network_protocol",legacy?"tcp":""),InstallMethod=Ui.Text(data,"install_method",legacy?"builtin":"import"),OfficialUrl=Ui.Text(data,"official_url")};
        }
        internal bool Allows(string capability) {
            object raw;var caps=Data.TryGetValue("capabilities",out raw)?Ui.Map(raw):Ui.Obj();
            if(caps.ContainsKey(capability))return Ui.Bool(caps,capability);
            if(capability=="console")return true;
            bool legacy=Array.IndexOf(new[]{"vanilla","neoforge","forge","fabric"},Id)>=0;
            return legacy&&Array.IndexOf(new[]{"save_world","online_backup","rcon","java","properties"},capability)>=0;
        }
        internal bool PageAllowed(string page) {return page!="console"||Allows("console");}


        internal bool PropertyAllowed(string key) {
            object raw;if(Data.TryGetValue("editable_properties",out raw)&&raw!=null){
                var values=raw as System.Collections.IEnumerable;if(values==null||raw is string)return false;
                foreach(object value in values)if(Convert.ToString(value)==key)return true;return false;
            }
            return Allows("properties")&&Family=="java";
        }
        internal string RuntimeLabel {get{return Runtime=="java"?"Java":Runtime=="php"?"PHP":"程序";}}
    }
    internal sealed partial class NativeMainForm {
        private readonly Dictionary<string,PlatformUiProfile> platformProfiles=new Dictionary<string,PlatformUiProfile>();
        private PlatformUiProfile CurrentPlatform {
            get {PlatformUiProfile value;return platformProfiles.TryGetValue(selectedServerId,out value)?value:PlatformUiProfile.Read(serverPresentation.Server);}
        }
        private void RememberPlatform(Dictionary<string,object> result,string id) {
            if(String.IsNullOrEmpty(id))return;var profile=PlatformUiProfile.Read(result);
            if(profile.Id.Length>0&&(profile.Data.ContainsKey("family")||profile.Data.ContainsKey("platform_profile")||profile.Family=="java"))platformProfiles[id]=profile;
        }
        private Control PlatformUnsupportedPage(string key) {
            var profile=CurrentPlatform;var message=new Label {Name="PlatformUnsupported",Dock=DockStyle.Fill,Padding=new Padding(26),AutoSize=false,Text=profile.Label+" 不提供此面板功能。\r\n\r\n"+"后台未提供此操作能力。",Font=Ui.BodyFont};Ui.Role(message,"muted");return message;
        }
        private void UpdatePlatformNavigation() {
            foreach(var entry in navigation){bool allowed=CurrentPlatform.PageAllowed(entry.Key);entry.Value.Enabled=allowed;statusTip.SetToolTip(entry.Value,allowed?"":"当前平台不支持此功能。");}
        }
        private static void PlatformFieldVisible(TableLayoutPanel fields,Control control,bool visible) {
            int row=fields.GetRow(control);if(row<0)return;foreach(Control child in fields.Controls)if(fields.GetRow(child)==row)child.Visible=visible;
        }
        private static bool PlatformFolderRecognized(string path,PlatformUiProfile profile) {
            if(!Directory.Exists(path))return false;
            if(profile!=null&&profile.ConfigFile.Length>0&&File.Exists(Path.Combine(path,profile.ConfigFile)))return true;
            foreach(string file in new[]{"server.properties","velocity.toml","config.yml","bedrock_server.exe","PocketMine-MP.phar","qizhang-platform-launch.json","qizhang-server-run-once.bat","start.cmd","start.bat","run.bat"})if(File.Exists(Path.Combine(path,file)))return true;
            return Directory.GetFiles(path,"*.jar",SearchOption.TopDirectoryOnly).Length>0;
        }
    }
}
