// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal sealed partial class NativeMainForm {
        private Button DiagnosticsButton() {
            var button=Ui.Button("诊断与导出…",ShowDiagnosticsAsync);button.Name="OpenDiagnostics";
            button.Enabled=true;statusTip.SetToolTip(button,"查看脱敏诊断，确认内容后导出 ZIP。");return button;
        }
        private Task ShowDiagnosticsAsync() {
            string id=selectedServerId;
            using(var dialog=new Form {Name="DiagnosticsDialog",Text="服务器诊断与导出",Width=800,Height=640,MinimumSize=new Size(600,440),StartPosition=FormStartPosition.CenterParent,Font=Ui.BodyFont}) {
                string token="";bool busy=false;
                var output=new TextBox {Name="DiagnosticsPreview",Multiline=true,ReadOnly=true,Dock=DockStyle.Fill,ScrollBars=ScrollBars.Both,WordWrap=false};
                var logs=new CheckBox {Name="DiagnosticsIncludeLogs",Text="包含最近 150 行日志（按规则脱敏，请检查预览）",AutoSize=true};
                var note=new Label {Text="只导出当前服务器的诊断，不包含账号文件、存档或原始启动参数。",AutoSize=true,Padding=new Padding(8)};
                Button export=null,refresh=null;
                Func<Task> load=async delegate {
                    if(busy)return;busy=true;token="";export.Enabled=false;refresh.Enabled=false;logs.Enabled=false;
                    try {var data=await Call("diagnostics.preview",Ui.Obj("include_logs",logs.Checked),id);if(dialog.IsDisposed)return;
                        token=Ui.Text(data,"preview_token");
                        output.Text="诊断预览（下列内容将写入 ZIP）"+Environment.NewLine+Ui.Text(data,"preview_text").Replace("\r\n","\n").Replace("\n",Environment.NewLine);
                        export.Enabled=token.Length>0;note.Text="已生成预览。导出使用此份快照；如状态变化，请重新读取。";
                    }finally {busy=false;if(!dialog.IsDisposed){refresh.Enabled=true;logs.Enabled=true;}}
                };
                refresh=Ui.Button("重新读取",load);refresh.Name="DiagnosticsRefresh";
                export=Ui.Button("导出诊断 ZIP…",async delegate {
                    if(busy||token.Length==0)return;
                    using(var picker=new SaveFileDialog {Filter="诊断压缩包 (*.zip)|*.zip",FileName="QiZhang-diagnostics.zip",DefaultExt="zip",AddExtension=true,OverwritePrompt=true}) {
                        if(picker.ShowDialog(dialog)!=DialogResult.OK)return;
                        busy=true;export.Enabled=false;refresh.Enabled=false;logs.Enabled=false;
                        string exportToken=token;token="";
                        try {var result=await Call("diagnostics.export",Ui.Obj("preview_token",exportToken),id);
                            byte[] bytes=Convert.FromBase64String(Ui.Text(result,"archive_base64"));if(bytes.Length>262144)throw new InvalidOperationException("诊断包超过大小限制。");
                            using(var sha=System.Security.Cryptography.SHA256.Create()){string hash=BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();if(hash!=Ui.Text(result,"sha256"))throw new InvalidOperationException("诊断包校验失败。");}
                            File.WriteAllBytes(picker.FileName,bytes);note.Text="诊断已导出："+picker.FileName+"。可重新读取预览后再次导出。";
                        }catch {note.Text="导出未完成，请重新读取预览后重试。";throw;
                        }finally {busy=false;refresh.Enabled=true;logs.Enabled=true;}
                    }
                });export.Name="DiagnosticsExport";export.Enabled=false;
                export.EnabledChanged+=delegate {if(export.Enabled&&token.Length==0)export.Enabled=false;};
                logs.CheckedChanged+=async delegate {await Safe(load);};
                var close=Ui.Button("关闭",delegate{dialog.Close();return Task.CompletedTask;});
                var toolbar=Ui.Toolbar(logs,refresh,export,close);toolbar.Dock=DockStyle.Top;note.Dock=DockStyle.Bottom;
                dialog.Controls.Add(output);dialog.Controls.Add(note);dialog.Controls.Add(toolbar);dialog.CancelButton=close;
                dialog.FormClosing+=delegate(object sender,FormClosingEventArgs e){if(busy)e.Cancel=true;};
                dialog.Shown+=async delegate {await Safe(load);};Ui.ApplyTheme(dialog);dialog.ShowDialog(this);
            }
            return Task.CompletedTask;
        }
    }
}
