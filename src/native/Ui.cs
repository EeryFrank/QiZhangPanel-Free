// QiZhang Control Panel - original panel code belongs to EeryFrank.
// https://github.com/EeryFrank - third-party rights and licenses remain unchanged.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using QiZhang.Shared;

namespace QiZhang.NativePanel {
    internal static class Ui {
        private static Color Tone(int light,int dark){return Color.FromArgb(unchecked((int)0xFF000000)|(AppTheme.IsDark?dark:light));}
        internal static Color Canvas {get{return Tone(0xF5F6F7,0x17191C);}}
        internal static Color Surface {get{return Tone(0xFFFFFF,0x23262B);}}
        internal static Color RaisedSurface {get{return Tone(0xF8F9FA,0x2B2F35);}}
        internal static Color Ink {get{return Tone(0x242A32,0xEBEDF1);}}
        internal static Color Muted {get{return Tone(0x616B79,0xADB5C1);}}
        private static Color AccentTone(int greenLight,int greenDark,int blueLight,int blueDark,int violetLight,int violetDark,int roseLight,int roseDark,int amberLight,int amberDark,int tealLight,int tealDark,int slateLight,int slateDark){
            switch(AppTheme.Accent){case "blue":return Tone(blueLight,blueDark);case "violet":return Tone(violetLight,violetDark);case "rose":return Tone(roseLight,roseDark);case "amber":return Tone(amberLight,amberDark);case "teal":return Tone(tealLight,tealDark);case "slate":return Tone(slateLight,slateDark);default:return Tone(greenLight,greenDark);}
        }
        internal static Color Primary {get{return AccentTone(0x127752,0x63CFA1,0x2563EB,0x82B1FF,0x7047CC,0xBCA5FF,0xBE3568,0xF2A0BF,0x936200,0xE6BC62,0x0B7378,0x6AD2D3,0x53657C,0xAFBDD0);}}
        internal static Color OnPrimary {get{return AccentTone(0xFFFFFF,0x092B1D,0xFFFFFF,0x092142,0xFFFFFF,0x251442,0xFFFFFF,0x43162A,0xFFFFFF,0x352409,0xFFFFFF,0x092C2D,0xFFFFFF,0x1A2431);}}
        internal static Color PrimarySoft {get{return AccentTone(0xE5F3EB,0x244333,0xEAF1FD,0x253956,0xF0EBFB,0x3B2E53,0xFBEAF1,0x4E293B,0xFFF2D7,0x473A23,0xE3F2F2,0x234344,0xECF0F5,0x34404F);}}
        private static Color Blend(Color color,Color target,double amount){return Color.FromArgb((int)Math.Round(color.R+(target.R-color.R)*amount),(int)Math.Round(color.G+(target.G-color.G)*amount),(int)Math.Round(color.B+(target.B-color.B)*amount));}
        internal static Color PrimaryHover {get{return Blend(Primary,AppTheme.IsDark?Color.White:Color.Black,.1);}}
        internal static Color PrimaryPressed {get{return Blend(Primary,AppTheme.IsDark?Color.White:Color.Black,.18);}}
        internal static Color Line {get{return Tone(0xDDE1E7,0x424851);}}
        internal static Color Sidebar {get{return Tone(0xEDF0F3,0x111316);}}
        internal static Color SidebarInk {get{return Tone(0x424D5D,0xD7DDE6);}}
        internal static Color NavSelected {get{return PrimarySoft;}}
        internal static Color NavigationHeadingSurface {get{return Tone(0x354150,0x080B10);}}
        internal static Color NavigationHeadingInk {get{return Tone(0xF5F7FA,0xCBD4E0);}}
        internal static Color HoverSurface {get{return Tone(0xEBEEF2,0x343A43);}}
        internal static Color DisabledSurface {get{return Tone(0xECEFF3,0x2C323A);}}
        internal static Color DisabledInk {get{return Tone(0x626B78,0xA6B0BE);}}
        internal static Color Warning {get{return Tone(0x89590E,0xF0BF70);}}
        internal static Color WarningSoft {get{return Tone(0xFFF3DC,0x493A23);}}
        internal static Color Danger {get{return Tone(0xB34040,0xF4A3A0);}}
        internal static Color DangerSoft {get{return Tone(0xFBECEC,0x4B2C2B);}}
        internal static readonly Font BodyFont=new Font("Microsoft YaHei UI",9F);
        internal static readonly Font HeaderFont=new Font("Microsoft YaHei UI",9F,FontStyle.Bold);
        private sealed class ThemeMarker {internal bool Bound;internal string Role="";internal ThemeChromeWindow Chrome;}
        private static Icon ApplicationIcon;
        private static readonly ConditionalWeakTable<Control,ThemeMarker> Themed=new ConditionalWeakTable<Control,ThemeMarker>();
        private static readonly ToolStripRenderer MenuRenderer=new ThemeMenuRenderer();
        private static ThemeMarker Marker(Control control){return Themed.GetValue(control,delegate(Control ignored){return new ThemeMarker();});}
        internal static void Role(Control control,string role){if(control==null)return;var marker=Marker(control);string next=(role??"").ToLowerInvariant();if(marker.Bound&&marker.Role==next)return;marker.Role=next;ApplyTheme(control);}
        internal static void SetRole(Control control,string role){Role(control,role);}
        private static string Semantic(Control control){ThemeMarker marker;return control!=null&&Themed.TryGetValue(control,out marker)?marker.Role:"";}
        internal static Dictionary<string,object> Obj(params object[] pairs) {
            var result=new Dictionary<string,object>();
            for(int i=0;i+1<pairs.Length;i+=2)result[Convert.ToString(pairs[i])]=pairs[i+1];
            return result;
        }
        internal static Dictionary<string,object> Map(object value) { return value as Dictionary<string,object> ?? new Dictionary<string,object>(); }
        internal static string Text(Dictionary<string,object> value,string key,string fallback="") { object v;return value!=null&&value.TryGetValue(key,out v)&&v!=null?Convert.ToString(v):fallback; }
        internal static bool Bool(Dictionary<string,object> value,string key) { object v;if(value==null||!value.TryGetValue(key,out v)||v==null)return false;bool b;return bool.TryParse(Convert.ToString(v),out b)?b:Convert.ToString(v)=="1"; }
        internal static double Num(Dictionary<string,object> value,string key) { double n;return double.TryParse(Text(value,key),out n)?n:0; }
        internal static List<Dictionary<string,object>> List(Dictionary<string,object> value,string key) {
            var result=new List<Dictionary<string,object>>();object raw;
            if(value==null||!value.TryGetValue(key,out raw))return result;
            var array=raw as IEnumerable;if(array==null || raw is string)return result;
            foreach(var row in array){var map=row as Dictionary<string,object>;if(map!=null)result.Add(map);}return result;
        }
        internal static Button Button(string text,Func<Task> action) {
            var button=new NativeActionButton { Text=text,AutoSize=true,MinimumSize=new Size(96,36),Padding=new Padding(12,4,12,4),FlatStyle=FlatStyle.Flat,BackColor=Surface,ForeColor=Ink,Margin=new Padding(0,0,8,6) };
            StyleButton(button);
            button.Click+=async delegate { button.Enabled=false;try {await action();}catch(Exception ex){Message(button.FindForm(),ex.Message,"操作未完成",MessageBoxIcon.Warning);}finally{if(!button.IsDisposed)button.Enabled=true;} };
            return button;
        }
        internal static DataGridView Grid(params string[] columns) {
            var grid=new DataGridView {Dock=DockStyle.Fill,ReadOnly=true,AllowUserToAddRows=false,AllowUserToDeleteRows=false,AutoGenerateColumns=false,SelectionMode=DataGridViewSelectionMode.FullRowSelect,MultiSelect=false,RowHeadersVisible=false,BackgroundColor=Color.White,BorderStyle=BorderStyle.None,AutoSizeColumnsMode=DataGridViewAutoSizeColumnsMode.Fill,AllowUserToResizeRows=false,EnableHeadersVisualStyles=false,ColumnHeadersHeight=38,RowTemplate={Height=32},Margin=new Padding(0,10,0,0)};
            foreach(string column in columns)grid.Columns.Add(column,column);
            StyleGrid(grid);return grid;
        }
        internal static Dictionary<string,object> Selected(DataGridView grid) { return grid.CurrentRow==null?new Dictionary<string,object>():Map(grid.CurrentRow.Tag); }
        internal static TableLayoutPanel Fields() {
            var fields=new TableLayoutPanel {Dock=DockStyle.Top,AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,ColumnCount=2,Padding=new Padding(14,10,14,10),BackColor=Surface,GrowStyle=TableLayoutPanelGrowStyle.AddRows};
            Marker(fields).Role="surface";
            fields.Paint+=delegate(object sender,PaintEventArgs e){using(var pen=new Pen(Line))e.Graphics.DrawRectangle(pen,0,0,Math.Max(0,fields.Width-1),Math.Max(0,fields.Height-1));};
            fields.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,170));fields.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));return fields;
        }
        internal static void Field(TableLayoutPanel fields,string label,Control control) {
            int row=fields.RowCount++;fields.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            var text=new Label {Text=label,AutoSize=true,Anchor=AnchorStyles.Left,ForeColor=Muted,Margin=new Padding(2,10,8,10)};
            Marker(text).Role="muted";
            control.Anchor=AnchorStyles.Left|AnchorStyles.Right;control.Margin=new Padding(2,5,2,5);if(control.MinimumSize.Width==0)control.MinimumSize=new Size(200,26);
            fields.Controls.Add(text,0,row);fields.Controls.Add(control,1,row);
        }
        internal static FlowLayoutPanel Toolbar(params Control[] controls) {
            var panel=new FlowLayoutPanel {Dock=DockStyle.Top,AutoSize=true,WrapContents=true,Padding=new Padding(0,6,0,6),Margin=new Padding(0),BackColor=Canvas};Marker(panel).Role="canvas";panel.Controls.AddRange(controls);return panel;
        }
        internal static void FillGrid(DataGridView grid,List<Dictionary<string,object>> rows) {
            grid.Rows.Clear();foreach(var row in rows){var values=new object[grid.Columns.Count];for(int i=0;i<values.Length;i++)values[i]=Text(row,grid.Columns[i].Name);int index=grid.Rows.Add(values);grid.Rows[index].Tag=row;}
        }
        internal static void AddOwnershipFooter(Form form) {
            if(form==null||form.IsDisposed)return;
            var pending=new Stack<Control>();pending.Push(form);
            while(pending.Count>0){var control=pending.Pop();if(control.Name=="OwnershipFooter")return;foreach(Control child in control.Controls)pending.Push(child);}
            const int footerHeight=32;
            var originalSize=form.ClientSize;
            var content=new Panel {Name="OwnershipContent",Dock=DockStyle.Fill,Size=originalSize,BackColor=form.BackColor};
            var original=new List<Control>();foreach(Control control in form.Controls)original.Add(control);
            var footer=new LinkLabel {Name="OwnershipFooter",Text="© 2026 EeryFrank 所有",Dock=DockStyle.Bottom,Height=footerHeight,TextAlign=ContentAlignment.MiddleRight,Padding=new Padding(0,0,14,0),Font=BodyFont,BackColor=Canvas,LinkColor=Primary,ActiveLinkColor=Primary,VisitedLinkColor=Primary,LinkBehavior=LinkBehavior.HoverUnderline,TabStop=true};
            Marker(footer).Role="muted";
            footer.LinkClicked+=delegate {try{Process.Start(new ProcessStartInfo("https://github.com/EeryFrank"){UseShellExecute=true});}catch(Exception error){Message(form,error.Message,"无法打开项目主页",MessageBoxIcon.Warning);}};
            form.SuspendLayout();content.SuspendLayout();
            try{
                foreach(Control control in original){form.Controls.Remove(control);content.Controls.Add(control);}
                if(!form.MinimumSize.IsEmpty)form.MinimumSize=new Size(form.MinimumSize.Width,form.MinimumSize.Height+footerHeight);
                if(!form.MaximumSize.IsEmpty)form.MaximumSize=new Size(form.MaximumSize.Width,form.MaximumSize.Height+footerHeight);
                form.ClientSize=new Size(originalSize.Width,originalSize.Height+footerHeight);
                form.Controls.Add(content);form.Controls.Add(footer);
            }finally{content.ResumeLayout(true);form.ResumeLayout(true);}
        }

        private static bool Starts(string text,params string[] prefixes){foreach(string prefix in prefixes)if(text.StartsWith(prefix,StringComparison.Ordinal))return true;return false;}
        private static void StyleButton(Button button){
            button.FlatStyle=FlatStyle.Flat;button.UseVisualStyleBackColor=false;
            string role=Semantic(button);
            bool navigation=role=="nav"||role=="selected";
            var nativeButton=button as NativeActionButton;if(nativeButton!=null)nativeButton.NavigationSelected=role=="selected";
            bool danger=role=="danger"||(role==""&&Starts(button.Text,"删除","强制","清空违规"));
            bool primary=role=="primary"||(role==""&&Starts(button.Text,"保存","创建","登录","注册","启动","发送","执行","添加","确认","应用","导入","下载","同意"));
            button.BackColor=navigation?(role=="selected"?NavSelected:Sidebar):danger?DangerSoft:primary?Primary:Surface;
            button.ForeColor=navigation?(role=="selected"?Primary:SidebarInk):danger?Danger:primary?OnPrimary:Ink;
            button.FlatAppearance.BorderSize=navigation?0:1;
            button.FlatAppearance.BorderColor=danger?DangerSoft:primary?Primary:Line;
            button.FlatAppearance.MouseOverBackColor=navigation?NavSelected:danger?DangerSoft:primary?PrimaryHover:HoverSurface;
            button.FlatAppearance.MouseDownBackColor=navigation?PrimarySoft:danger?DangerSoft:primary?PrimaryPressed:PrimarySoft;
        }
        private static void StyleGrid(DataGridView grid){
            grid.Font=BodyFont;grid.ColumnHeadersDefaultCellStyle.Font=HeaderFont;grid.DefaultCellStyle.Font=BodyFont;
            grid.BackgroundColor=Surface;grid.ForeColor=Ink;grid.BorderStyle=BorderStyle.None;grid.GridColor=Line;
            grid.EnableHeadersVisualStyles=false;grid.CellBorderStyle=DataGridViewCellBorderStyle.SingleHorizontal;
            grid.ColumnHeadersBorderStyle=DataGridViewHeaderBorderStyle.Single;grid.ColumnHeadersHeight=40;
            grid.ColumnHeadersDefaultCellStyle.BackColor=RaisedSurface;grid.ColumnHeadersDefaultCellStyle.ForeColor=Muted;
            grid.ColumnHeadersDefaultCellStyle.SelectionBackColor=RaisedSurface;grid.ColumnHeadersDefaultCellStyle.SelectionForeColor=Ink;
            grid.ColumnHeadersDefaultCellStyle.Padding=new Padding(8,4,4,4);
            grid.DefaultCellStyle.BackColor=Surface;grid.DefaultCellStyle.ForeColor=Ink;
            grid.DefaultCellStyle.SelectionBackColor=PrimarySoft;grid.DefaultCellStyle.SelectionForeColor=Ink;
            grid.DefaultCellStyle.Padding=new Padding(8,2,4,2);grid.AlternatingRowsDefaultCellStyle.BackColor=RaisedSurface;
            grid.AlternatingRowsDefaultCellStyle.ForeColor=Ink;grid.AlternatingRowsDefaultCellStyle.SelectionBackColor=PrimarySoft;grid.AlternatingRowsDefaultCellStyle.SelectionForeColor=Ink;
            grid.RowHeadersDefaultCellStyle.BackColor=RaisedSurface;grid.RowHeadersDefaultCellStyle.ForeColor=Muted;
            grid.RowTemplate.Height=35;
            foreach(DataGridViewColumn column in grid.Columns)column.MinimumWidth=70;
        }
        private static Color ParentSurface(Control control){Control parent=control.Parent;while(parent!=null){if(parent.BackColor.A==255)return parent.BackColor;parent=parent.Parent;}return Canvas;}
        private static Color RoleSurface(string role,Color fallback){switch(role){case "surface":case "console":return Surface;case "sidebar":return Sidebar;case "navheading":return NavigationHeadingSurface;case "warning":return WarningSoft;case "danger":return DangerSoft;case "selected":return NavSelected;case "canvas":return Canvas;default:return fallback;}}
        private static Color RoleInk(string role,Control control){switch(role){case "navheading":return NavigationHeadingInk;case "muted":return Muted;case "brand":return Primary;case "warning":return Warning;case "danger":return Danger;case "sidebar":case "nav":return SidebarInk;case "selected":return Primary;default:return Semantic(control.Parent)=="sidebar"?SidebarInk:Ink;}}
        private static void Bind(Control root,ThemeMarker marker){
            if(marker.Bound)return;marker.Bound=true;
            root.ControlAdded+=delegate(object sender,ControlEventArgs e){ApplyTheme(e.Control);};
            root.HandleCreated+=delegate{ApplyTheme(root);};
            root.EnabledChanged+=delegate{if(!root.IsDisposed){StyleOne(root,marker);root.Invalidate();}};
            var choice=root as ButtonBase;
            if(choice is CheckBox||choice is RadioButton)choice.Paint+=delegate(object sender,PaintEventArgs e){if(!choice.Enabled)PaintDisabledChoice(choice,e.Graphics);};
            var strip=root as ToolStrip;
            if(strip!=null)strip.ItemAdded+=delegate{StyleStrip(strip);};
            var combo=root as ComboBox;
            if(combo!=null){marker.Chrome=new ThemeChromeWindow(combo);combo.DrawItem+=delegate(object sender,DrawItemEventArgs e){
                bool selected=(e.State&DrawItemState.Selected)!=0;Color background=selected?PrimarySoft:Surface;
                using(var brush=new SolidBrush(background))e.Graphics.FillRectangle(brush,e.Bounds);
                string text=e.Index>=0&&e.Index<combo.Items.Count?combo.GetItemText(combo.Items[e.Index]):combo.Text;
                TextRenderer.DrawText(e.Graphics,text,combo.Font,new Rectangle(e.Bounds.X+8,e.Bounds.Y,e.Bounds.Width-12,e.Bounds.Height),combo.Enabled?Ink:DisabledInk,TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine|TextFormatFlags.EndEllipsis|TextFormatFlags.NoPrefix);
            };}
            var tabs=root as TabControl;
            if(tabs!=null){
                tabs.DrawItem+=delegate(object sender,DrawItemEventArgs e){
                    if(e.Index<0||e.Index>=tabs.TabPages.Count)return;
                    bool selected=tabs.SelectedIndex==e.Index;Rectangle rect=tabs.GetTabRect(e.Index);
                    using(var brush=new SolidBrush(selected?Surface:Canvas))e.Graphics.FillRectangle(brush,rect);
                    if(selected)using(var pen=new Pen(Primary,3))e.Graphics.DrawLine(pen,rect.Left+8,rect.Bottom-2,rect.Right-8,rect.Bottom-2);
                    TextRenderer.DrawText(e.Graphics,tabs.TabPages[e.Index].Text,tabs.Font,rect,selected?Primary:Muted,TextFormatFlags.HorizontalCenter|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine|TextFormatFlags.EndEllipsis|TextFormatFlags.NoPrefix);
                };
                marker.Chrome=new ThemeChromeWindow(tabs);
            }
            var progress=root as ProgressBar;if(progress!=null)marker.Chrome=new ThemeChromeWindow(progress);
            if(root is TextBoxBase)marker.Chrome=new ThemeChromeWindow(root);
            if(root is CheckedListBox)marker.Chrome=new ThemeChromeWindow(root);
            if(root.GetType().Name=="UpDownButtons")marker.Chrome=new ThemeChromeWindow(root);
            var list=root as ListBox;
            if(list!=null&&!(root is CheckedListBox))list.DrawItem+=delegate(object sender,DrawItemEventArgs e){
                bool selected=(e.State&DrawItemState.Selected)!=0;using(var brush=new SolidBrush(selected?PrimarySoft:Surface))e.Graphics.FillRectangle(brush,e.Bounds);
                if(e.Index>=0&&e.Index<list.Items.Count)TextRenderer.DrawText(e.Graphics,list.GetItemText(list.Items[e.Index]),list.Font,new Rectangle(e.Bounds.X+8,e.Bounds.Y,e.Bounds.Width-12,e.Bounds.Height),list.Enabled?Ink:DisabledInk,TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.EndEllipsis|TextFormatFlags.NoPrefix);
                if((e.State&DrawItemState.Focus)!=0)e.DrawFocusRectangle();
            };
            var view=root as ListView;
            if(view!=null){
                view.DrawColumnHeader+=delegate(object sender,DrawListViewColumnHeaderEventArgs e){using(var brush=new SolidBrush(RaisedSurface))e.Graphics.FillRectangle(brush,e.Bounds);TextRenderer.DrawText(e.Graphics,e.Header.Text,HeaderFont,Rectangle.Inflate(e.Bounds,-8,0),Muted,TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.EndEllipsis|TextFormatFlags.NoPrefix);using(var pen=new Pen(Line))e.Graphics.DrawLine(pen,e.Bounds.Left,e.Bounds.Bottom-1,e.Bounds.Right,e.Bounds.Bottom-1);};
                view.DrawItem+=delegate(object sender,DrawListViewItemEventArgs e){if(view.View!=View.Details)e.DrawDefault=true;else using(var brush=new SolidBrush(e.Item.Selected?PrimarySoft:Surface))e.Graphics.FillRectangle(brush,e.Bounds);};
                view.DrawSubItem+=delegate(object sender,DrawListViewSubItemEventArgs e){using(var brush=new SolidBrush(e.Item.Selected?PrimarySoft:Surface))e.Graphics.FillRectangle(brush,e.Bounds);TextRenderer.DrawText(e.Graphics,e.SubItem.Text,view.Font,Rectangle.Inflate(e.Bounds,-8,0),view.Enabled?Ink:DisabledInk,TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.EndEllipsis|TextFormatFlags.NoPrefix);};
            }
            var group=root as GroupBox;
            if(group!=null)group.Paint+=delegate(object sender,PaintEventArgs e){
                e.Graphics.Clear(group.BackColor);Size text=TextRenderer.MeasureText(group.Text,group.Font);
                using(var pen=new Pen(Line))e.Graphics.DrawRectangle(pen,1,text.Height/2,Math.Max(0,group.Width-3),Math.Max(0,group.Height-text.Height/2-2));
                using(var brush=new SolidBrush(group.BackColor))e.Graphics.FillRectangle(brush,9,0,text.Width+8,text.Height);
                TextRenderer.DrawText(e.Graphics,group.Text,group.Font,new Point(13,0),group.Enabled?Ink:DisabledInk,TextFormatFlags.NoPrefix);
            };
        }
        private static void PaintDisabledChoice(ButtonBase choice,Graphics graphics){
            // WinForms' flat checkbox renderer uses system gray text even when
            // ForeColor is set. Redraw only its disabled presentation; the actual
            // control still owns selection, keyboard input and accessibility.
            var check=choice as CheckBox;var radio=choice as RadioButton;
            bool button=check!=null?check.Appearance==Appearance.Button:radio.Appearance==Appearance.Button;
            graphics.Clear(choice.BackColor);Rectangle text=choice.ClientRectangle;
            text=new Rectangle(text.Left+choice.Padding.Left,text.Top+choice.Padding.Top,Math.Max(0,text.Width-choice.Padding.Horizontal),Math.Max(0,text.Height-choice.Padding.Vertical));
            if(button){using(var brush=new SolidBrush(DisabledSurface))graphics.FillRectangle(brush,text);using(var pen=new Pen(Line))graphics.DrawRectangle(pen,text.Left,text.Top,Math.Max(0,text.Width-1),Math.Max(0,text.Height-1));}
            else{
                ContentAlignment align=check!=null?check.CheckAlign:radio.CheckAlign;int size=13;
                bool right=align==ContentAlignment.TopRight||align==ContentAlignment.MiddleRight||align==ContentAlignment.BottomRight;
                bool center=align==ContentAlignment.TopCenter||align==ContentAlignment.MiddleCenter||align==ContentAlignment.BottomCenter;
                if(choice.RightToLeft==RightToLeft.Yes&&!center)right=!right;
                int x=center?text.Left+(text.Width-size)/2:right?text.Right-size:text.Left;
                int y=(align==ContentAlignment.TopLeft||align==ContentAlignment.TopCenter||align==ContentAlignment.TopRight)?text.Top:(align==ContentAlignment.BottomLeft||align==ContentAlignment.BottomCenter||align==ContentAlignment.BottomRight)?text.Bottom-size:text.Top+(text.Height-size)/2;
                Rectangle glyph=new Rectangle(x,y,size-1,size-1);
                using(var fill=new SolidBrush(DisabledSurface))using(var pen=new Pen(DisabledInk)){
                    if(radio!=null){graphics.FillEllipse(fill,glyph);graphics.DrawEllipse(pen,glyph);if(radio.Checked)using(var dot=new SolidBrush(DisabledInk))graphics.FillEllipse(dot,Rectangle.Inflate(glyph,-4,-4));}
                    else{graphics.FillRectangle(fill,glyph);graphics.DrawRectangle(pen,glyph);if(check.CheckState==CheckState.Indeterminate)using(var mark=new SolidBrush(DisabledInk))graphics.FillRectangle(mark,Rectangle.Inflate(glyph,-3,-3));else if(check.Checked)using(var mark=new Pen(DisabledInk,2))graphics.DrawLines(mark,new[]{new Point(x+3,y+size/2),new Point(x+size/2-1,y+size-4),new Point(x+size-3,y+3)});}
                }
                if(!center){if(right)text.Width=Math.Max(0,text.Width-size-3);else{text.X+=size+3;text.Width=Math.Max(0,text.Width-size-3);}}
            }
            TextFormatFlags flags=TextFormatFlags.NoPadding|TextFormatFlags.PreserveGraphicsClipping|(choice.AutoSize?TextFormatFlags.SingleLine:TextFormatFlags.WordBreak);
            if(!choice.UseMnemonic)flags|=TextFormatFlags.NoPrefix;
            ContentAlignment alignment=choice.TextAlign;
            if(alignment==ContentAlignment.TopRight||alignment==ContentAlignment.MiddleRight||alignment==ContentAlignment.BottomRight)flags|=TextFormatFlags.Right;
            else if(alignment==ContentAlignment.TopCenter||alignment==ContentAlignment.MiddleCenter||alignment==ContentAlignment.BottomCenter)flags|=TextFormatFlags.HorizontalCenter;
            if(alignment==ContentAlignment.MiddleLeft||alignment==ContentAlignment.MiddleCenter||alignment==ContentAlignment.MiddleRight)flags|=TextFormatFlags.VerticalCenter;
            else if(alignment==ContentAlignment.BottomLeft||alignment==ContentAlignment.BottomCenter||alignment==ContentAlignment.BottomRight)flags|=TextFormatFlags.Bottom;
            if(choice.RightToLeft==RightToLeft.Yes)flags|=TextFormatFlags.RightToLeft;
            TextRenderer.DrawText(graphics,choice.Text,choice.Font,text,DisabledInk,flags);
        }
        private static void StyleStrip(ToolStrip strip){
            strip.Renderer=MenuRenderer;strip.BackColor=Surface;strip.ForeColor=Ink;
            foreach(ToolStripItem item in strip.Items){item.BackColor=Surface;item.ForeColor=item.Enabled?Ink:DisabledInk;var dropdown=item as ToolStripDropDownItem;if(dropdown!=null&&dropdown.HasDropDownItems)StyleStrip(dropdown.DropDown);}
        }
        private static void StyleOne(Control root,ThemeMarker marker){
            string role=marker.Role;Color surrounding=ParentSurface(root);
            root.ForeColor=root.Enabled?RoleInk(role,root):DisabledInk;
            var form=root as Form;if(form!=null){root.BackColor=RoleSurface(role,Canvas);AppTheme.ApplyTitleBar(form);return;}
            var grid=root as DataGridView;if(grid!=null){StyleGrid(grid);return;}
            var button=root as Button;if(button!=null){StyleButton(button);return;}
            var rich=root as RichTextBox;if(rich!=null){rich.BackColor=RoleSurface(role,Surface);rich.ForeColor=rich.Enabled?Ink:DisabledInk;rich.BorderStyle=BorderStyle.FixedSingle;return;}
            var text=root as TextBox;if(text!=null){text.BackColor=RoleSurface(role,text.ReadOnly?RaisedSurface:Surface);text.ForeColor=text.Enabled?Ink:DisabledInk;text.BorderStyle=BorderStyle.FixedSingle;return;}
            var combo=root as ComboBox;if(combo!=null){combo.BackColor=Surface;combo.ForeColor=combo.Enabled?Ink:DisabledInk;combo.FlatStyle=FlatStyle.Flat;combo.DrawMode=DrawMode.OwnerDrawFixed;combo.ItemHeight=Math.Max(24,combo.Font.Height+8);return;}
            var number=root as NumericUpDown;if(number!=null){number.BackColor=Surface;number.ForeColor=number.Enabled?Ink:DisabledInk;number.BorderStyle=BorderStyle.FixedSingle;return;}
            var date=root as DateTimePicker;if(date!=null){date.BackColor=Surface;date.CalendarMonthBackground=Surface;date.CalendarForeColor=Ink;date.CalendarTitleBackColor=RaisedSurface;date.CalendarTitleForeColor=Ink;date.CalendarTrailingForeColor=Muted;return;}
            var tabs=root as TabControl;if(tabs!=null){tabs.BackColor=Canvas;tabs.ForeColor=Ink;tabs.DrawMode=TabDrawMode.OwnerDrawFixed;tabs.Padding=new Point(15,8);tabs.ItemSize=new Size(104,Math.Max(34,tabs.Font.Height+17));return;}
            var link=root as LinkLabel;if(link!=null){link.BackColor=RoleSurface(role,surrounding);link.LinkColor=role=="muted"?Muted:Primary;link.ActiveLinkColor=Primary;link.VisitedLinkColor=link.LinkColor;link.DisabledLinkColor=DisabledInk;return;}
            var list=root as ListBox;if(list!=null){list.BackColor=Surface;list.ForeColor=list.Enabled?Ink:DisabledInk;list.BorderStyle=BorderStyle.FixedSingle;if(!(list is CheckedListBox)){list.DrawMode=DrawMode.OwnerDrawFixed;list.ItemHeight=Math.Max(26,list.Font.Height+8);}return;}
            var view=root as ListView;if(view!=null){view.BackColor=Surface;view.ForeColor=view.Enabled?Ink:DisabledInk;view.BorderStyle=BorderStyle.FixedSingle;view.OwnerDraw=view.View==View.Details;return;}
            var strip=root as ToolStrip;if(strip!=null){StyleStrip(strip);return;}
            var progress=root as ProgressBar;if(progress!=null){progress.BackColor=DisabledSurface;progress.ForeColor=Primary;return;}
            var check=root as ButtonBase;if(check!=null){check.BackColor=RoleSurface(role,surrounding);check.FlatStyle=FlatStyle.Flat;check.FlatAppearance.BorderColor=Line;check.FlatAppearance.CheckedBackColor=PrimarySoft;check.FlatAppearance.MouseOverBackColor=HoverSurface;return;}
            if(root is TabPage){root.BackColor=Surface;return;}
            if(root is Label){root.BackColor=RoleSurface(role,surrounding);return;}
            if(root is GroupBox){root.BackColor=RoleSurface(role,surrounding);return;}
            root.BackColor=RoleSurface(role,root is Panel?Canvas:surrounding);
        }
        internal static void ApplyTheme(Control root){
            if(root==null||root.IsDisposed)return;
            root.SuspendLayout();
            try{
            ThemeMarker marker=Marker(root);bool first=!marker.Bound;Bind(root,marker);
            var form=root as Form;
            if(form!=null&&first){AddOwnershipFooter(form);try{if(ApplicationIcon==null)ApplicationIcon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);if(ApplicationIcon!=null)form.Icon=ApplicationIcon;}catch{}}
            StyleOne(root,marker);
            ScrollBarTheme.Apply(root);
            if(root.ContextMenuStrip!=null)ApplyTheme(root.ContextMenuStrip);
            if(root is DataGridView){root.Invalidate();return;}
            foreach(Control child in root.Controls)ApplyTheme(child);
            if(form!=null)WindowChrome.Attach(form);
            root.Invalidate();
            }finally{root.ResumeLayout(true);}
        }
        internal static DialogResult Message(IWin32Window owner,string text,string title,MessageBoxIcon icon=MessageBoxIcon.Information){return ShowMessage(owner,text,title,icon,false);}
        internal static DialogResult Message(string text,string title,MessageBoxIcon icon=MessageBoxIcon.Information){return Message(Form.ActiveForm,text,title,icon);}
        internal static bool Confirm(IWin32Window owner,string text,string title="请确认"){return ShowMessage(owner,text,title,MessageBoxIcon.Question,true)==DialogResult.Yes;}
        private static DialogResult ShowMessage(IWin32Window owner,string text,string title,MessageBoxIcon icon,bool confirm){
            const int width=610;Size measured=TextRenderer.MeasureText(text??"",BodyFont,new Size(width-72,int.MaxValue),TextFormatFlags.WordBreak|TextFormatFlags.NoPrefix);
            using(var dialog=new Form{Text=title??"七章控制面板",ClientSize=new Size(width,Math.Max(150,Math.Min(370,measured.Height+56))+62),StartPosition=owner==null?FormStartPosition.CenterScreen:FormStartPosition.CenterParent,FormBorderStyle=FormBorderStyle.FixedDialog,MaximizeBox=false,MinimizeBox=false,ShowInTaskbar=false,Font=BodyFont}){
                var body=new Panel{Dock=DockStyle.Fill,AutoScroll=true,Padding=new Padding(24,20,24,16)};Marker(body).Role="surface";
                var message=new Label{Text=text??"",AutoSize=true,MaximumSize=new Size(width-72,0),Location=new Point(24,20),UseMnemonic=false};Marker(message).Role=icon==MessageBoxIcon.Error?"danger":icon==MessageBoxIcon.Warning?"warning":"title";body.Controls.Add(message);
                var buttons=new FlowLayoutPanel{Dock=DockStyle.Bottom,Height=62,FlowDirection=FlowDirection.RightToLeft,WrapContents=false,Padding=new Padding(12,10,18,8)};Marker(buttons).Role="canvas";
                Button accept=new NativeActionButton{Text=confirm?"确认":"知道了",AutoSize=true,MinimumSize=new Size(100,36),Margin=new Padding(0,0,8,0),DialogResult=confirm?DialogResult.Yes:DialogResult.OK};Marker(accept).Role="primary";
                if(confirm){var cancel=new NativeActionButton{Text="取消",AutoSize=true,MinimumSize=new Size(100,36),Margin=new Padding(0,0,8,0),DialogResult=DialogResult.No};Marker(cancel).Role="secondary";buttons.Controls.Add(cancel);buttons.Controls.Add(accept);dialog.AcceptButton=cancel;dialog.CancelButton=cancel;}
                else{buttons.Controls.Add(accept);dialog.AcceptButton=accept;dialog.CancelButton=accept;}
                dialog.Controls.Add(body);dialog.Controls.Add(buttons);ApplyTheme(dialog);
                return owner==null?dialog.ShowDialog():dialog.ShowDialog(owner);
            }
        }
    }

    // Draw only the native chrome. Values, selection, accessibility and keyboard
    // behavior stay on the original WinForms controls; no animation timer is added.
    internal sealed class ThemeChromeWindow : NativeWindow {
        private readonly Control control;
        [StructLayout(LayoutKind.Sequential)]private struct TextRect {internal int Left,Top,Right,Bottom;}
        [DllImport("user32.dll")]private static extern IntPtr SendMessage(IntPtr handle,int message,IntPtr wparam,IntPtr lparam);
        [DllImport("user32.dll",EntryPoint="SendMessageW")]private static extern IntPtr GetTextRect(IntPtr handle,int message,IntPtr wparam,ref TextRect rectangle);
        internal ThemeChromeWindow(Control control){
            this.control=control;
            control.HandleCreated+=delegate{Attach();};
            control.HandleDestroyed+=delegate{if(Handle!=IntPtr.Zero)ReleaseHandle();};
            control.Disposed+=delegate{if(Handle!=IntPtr.Zero)ReleaseHandle();};
            if(control.IsHandleCreated)Attach();
        }
        private void Attach(){if(control.IsDisposed||!control.IsHandleCreated)return;if(Handle!=IntPtr.Zero)ReleaseHandle();AssignHandle(control.Handle);}
        protected override void WndProc(ref System.Windows.Forms.Message message){
            base.WndProc(ref message);
            if(control.IsDisposed||!control.IsHandleCreated)return;
            if(message.Msg==0x000F||message.Msg==0x0317||message.Msg==0x0318){
                try{using(var graphics=(message.Msg==0x000F||message.WParam==IntPtr.Zero)?Graphics.FromHwnd(control.Handle):Graphics.FromHdc(message.WParam))PaintChrome(graphics);}catch(ArgumentException){}catch(ExternalException){}
            }else if(control is ProgressBar&&message.Msg>=0x0400&&message.Msg<=0x0420)control.Invalidate();
        }
        private void PaintChrome(Graphics graphics){
            var checkedList=control as CheckedListBox;
            if(checkedList!=null){
                if(checkedList.Enabled)return;
                using(var background=new SolidBrush(Ui.Surface))graphics.FillRectangle(background,checkedList.ClientRectangle);
                for(int index=checkedList.TopIndex;index<checkedList.Items.Count;index++){
                    Rectangle item=checkedList.GetItemRectangle(index);if(item.Top>=checkedList.ClientSize.Height)break;
                    using(var background=new SolidBrush(index==checkedList.SelectedIndex?Ui.PrimarySoft:Ui.Surface))graphics.FillRectangle(background,item);
                    int size=Math.Min(13,Math.Max(9,item.Height-4)),x=item.Left+2,y=item.Top+(item.Height-size)/2;
                    Rectangle glyph=new Rectangle(x,y,size,size);
                    using(var fill=new SolidBrush(Ui.DisabledSurface))graphics.FillRectangle(fill,glyph);
                    using(var pen=new Pen(Ui.DisabledInk))graphics.DrawRectangle(pen,glyph);
                    CheckState state=checkedList.GetItemCheckState(index);
                    if(state==CheckState.Indeterminate)using(var fill=new SolidBrush(Ui.DisabledInk))graphics.FillRectangle(fill,Rectangle.Inflate(glyph,-3,-3));
                    else if(state==CheckState.Checked)using(var pen=new Pen(Ui.DisabledInk,2))graphics.DrawLines(pen,new[]{new Point(x+3,y+size/2),new Point(x+size/2-1,y+size-3),new Point(x+size-2,y+3)});
                    TextRenderer.DrawText(graphics,checkedList.GetItemText(checkedList.Items[index]),checkedList.Font,new Rectangle(item.Left+size+8,item.Top,Math.Max(0,item.Width-size-8),item.Height),Ui.DisabledInk,TextFormatFlags.NoPrefix|TextFormatFlags.NoPadding|TextFormatFlags.SingleLine|TextFormatFlags.VerticalCenter);
                }return;
            }
            var text=control as TextBox;
            if(text!=null){
                if(text.Enabled)return;
                // A disabled Windows EDIT ignores ForeColor. Paint its existing
                // presentation only; retain the native value, mask and input state.
                var native=new TextRect();GetTextRect(text.Handle,0x00B2,IntPtr.Zero,ref native);
                Rectangle bounds=Rectangle.FromLTRB(native.Left,native.Top,native.Right,native.Bottom);
                if(bounds.Width<=0||bounds.Height<=0)bounds=text.ClientRectangle;
                using(var brush=new SolidBrush(text.BackColor))graphics.FillRectangle(brush,text.ClientRectangle);
                int mask=SendMessage(text.Handle,0x00D2,IntPtr.Zero,IntPtr.Zero).ToInt32();
                string displayed=mask==0?text.Text:new string((char)mask,text.TextLength);
                int first=SendMessage(text.Handle,0x00CE,IntPtr.Zero,IntPtr.Zero).ToInt32();
                int start=text.Multiline?text.GetFirstCharIndexFromLine(first):first;
                if(start>0&&start<displayed.Length)displayed=displayed.Substring(start);
                TextFormatFlags flags=TextFormatFlags.NoPrefix|TextFormatFlags.NoPadding|TextFormatFlags.PreserveGraphicsClipping;
                flags|=text.Multiline?(text.WordWrap?TextFormatFlags.WordBreak:TextFormatFlags.Default):TextFormatFlags.SingleLine;
                if(text.TextAlign==HorizontalAlignment.Center)flags|=TextFormatFlags.HorizontalCenter;else if(text.TextAlign==HorizontalAlignment.Right)flags|=TextFormatFlags.Right;
                if(text.RightToLeft==RightToLeft.Yes)flags|=TextFormatFlags.RightToLeft;
                TextRenderer.DrawText(graphics,displayed,text.Font,bounds,Ui.DisabledInk,flags);return;
            }
            var combo=control as ComboBox;
            if(combo!=null){
                Rectangle bounds=combo.ClientRectangle;if(bounds.Width<4||bounds.Height<4)return;
                if(combo.DropDownStyle!=ComboBoxStyle.Simple){
                    int width=SystemInformation.VerticalScrollBarWidth+2;
                    Rectangle button=new Rectangle(bounds.Right-width,1,width-1,bounds.Height-2);
                    using(var brush=new SolidBrush(Ui.RaisedSurface))graphics.FillRectangle(brush,button);
                    int x=button.Left+button.Width/2,y=button.Top+button.Height/2;
                    using(var pen=new Pen(combo.Enabled?Ui.Muted:Ui.DisabledInk,1.5f))graphics.DrawLines(pen,new[]{new Point(x-3,y-1),new Point(x,y+2),new Point(x+3,y-1)});
                }
                using(var pen=new Pen(Ui.Line))graphics.DrawRectangle(pen,0,0,bounds.Width-1,bounds.Height-1);return;
            }
            if(control.GetType().Name=="UpDownButtons"){
                Rectangle bounds=control.ClientRectangle;if(bounds.Width<4||bounds.Height<4)return;
                using(var brush=new SolidBrush(Ui.RaisedSurface))graphics.FillRectangle(brush,bounds);
                using(var pen=new Pen(Ui.Line))graphics.DrawRectangle(pen,0,0,bounds.Width-1,bounds.Height-1);
                int x=bounds.Width/2,upper=bounds.Height/4,lower=bounds.Height*3/4;
                using(var pen=new Pen(control.Enabled?Ui.Muted:Ui.DisabledInk,1.5f)){
                    graphics.DrawLines(pen,new[]{new Point(x-3,upper+1),new Point(x,upper-2),new Point(x+3,upper+1)});
                    graphics.DrawLines(pen,new[]{new Point(x-3,lower-1),new Point(x,lower+2),new Point(x+3,lower-1)});
                }return;
            }
            var progress=control as ProgressBar;
            if(progress!=null){
                Rectangle bounds=progress.ClientRectangle;if(bounds.Width<2||bounds.Height<2)return;
                using(var brush=new SolidBrush(Ui.DisabledSurface))graphics.FillRectangle(brush,bounds);
                Rectangle inner=Rectangle.Inflate(bounds,-1,-1);
                double fraction=progress.Maximum<=progress.Minimum?0:(double)(progress.Value-progress.Minimum)/(progress.Maximum-progress.Minimum);
                Rectangle fill=new Rectangle(inner.X,inner.Y,(int)Math.Round(inner.Width*fraction),inner.Height);
                if(progress.Style==ProgressBarStyle.Marquee)fill=new Rectangle(inner.X+inner.Width/3,inner.Y,Math.Max(1,inner.Width/3),inner.Height);
                if(fill.Width>0)using(var brush=new SolidBrush(progress.Enabled?Ui.Primary:Ui.DisabledInk))graphics.FillRectangle(brush,fill);
                using(var pen=new Pen(Ui.Line))graphics.DrawRectangle(pen,0,0,bounds.Width-1,bounds.Height-1);
                return;
            }
            var tabs=control as TabControl;
            if(tabs==null||tabs.Alignment!=TabAlignment.Top||tabs.Multiline)return;
            Rectangle client=tabs.ClientRectangle,display=tabs.DisplayRectangle;
            if(client.Width==0||client.Height==0)return;
            using(var chrome=new Region(client)){
                chrome.Exclude(display);
                using(var brush=new SolidBrush(Ui.Canvas))graphics.FillRegion(brush,chrome);
            }
            for(int i=0;i<tabs.TabPages.Count;i++){
                bool selected=tabs.SelectedIndex==i;Rectangle tab=tabs.GetTabRect(i);
                using(var brush=new SolidBrush(selected?Ui.Surface:Ui.Canvas))graphics.FillRectangle(brush,tab);
                if(selected)using(var pen=new Pen(Ui.Primary,3))graphics.DrawLine(pen,tab.Left+8,tab.Bottom-2,tab.Right-8,tab.Bottom-2);
                TextRenderer.DrawText(graphics,tabs.TabPages[i].Text,tabs.Font,tab,selected?Ui.Primary:Ui.Muted,TextFormatFlags.HorizontalCenter|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine|TextFormatFlags.EndEllipsis|TextFormatFlags.NoPrefix);
            }
            using(var pen=new Pen(Ui.Line))graphics.DrawRectangle(pen,Math.Max(0,display.Left-1),Math.Max(0,display.Top-1),Math.Max(0,display.Width+1),Math.Max(0,display.Height+1));
        }
    }
    internal sealed class ThemeMenuRenderer : ToolStripProfessionalRenderer {
        internal ThemeMenuRenderer(){RoundedEdges=false;}
        protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e){using(var brush=new SolidBrush(Ui.Surface))e.Graphics.FillRectangle(brush,e.AffectedBounds);}
        protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e){if(e.ToolStrip is ToolStripDropDown)using(var pen=new Pen(Ui.Line))e.Graphics.DrawRectangle(pen,0,0,e.ToolStrip.Width-1,e.ToolStrip.Height-1);}
        protected override void OnRenderImageMargin(ToolStripRenderEventArgs e){using(var brush=new SolidBrush(Ui.RaisedSurface))e.Graphics.FillRectangle(brush,e.AffectedBounds);}
        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e){using(var brush=new SolidBrush(e.Item.Selected||e.Item.Pressed?Ui.PrimarySoft:Ui.Surface))e.Graphics.FillRectangle(brush,new Rectangle(Point.Empty,e.Item.Size));}
        protected override void OnRenderButtonBackground(ToolStripItemRenderEventArgs e){using(var brush=new SolidBrush(e.Item.Selected||e.Item.Pressed?Ui.PrimarySoft:Ui.Surface))e.Graphics.FillRectangle(brush,new Rectangle(Point.Empty,e.Item.Size));}
        protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e){using(var pen=new Pen(Ui.Line)){if(e.Vertical)e.Graphics.DrawLine(pen,e.Item.Width/2,4,e.Item.Width/2,e.Item.Height-4);else e.Graphics.DrawLine(pen,7,e.Item.Height/2,e.Item.Width-7,e.Item.Height/2);}}
        protected override void OnRenderArrow(ToolStripArrowRenderEventArgs e){e.ArrowColor=e.Item.Enabled?Ui.Ink:Ui.DisabledInk;base.OnRenderArrow(e);}
        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e){e.TextColor=e.Item.Enabled?Ui.Ink:Ui.DisabledInk;base.OnRenderItemText(e);}
        protected override void OnRenderItemCheck(ToolStripItemImageRenderEventArgs e){
            Rectangle bounds=e.ImageRectangle;using(var brush=new SolidBrush(Ui.PrimarySoft))e.Graphics.FillRectangle(brush,Rectangle.Inflate(bounds,2,2));
            using(var pen=new Pen(Ui.Primary,2))e.Graphics.DrawLines(pen,new[]{new Point(bounds.Left+2,bounds.Top+bounds.Height/2),new Point(bounds.Left+bounds.Width/2-1,bounds.Bottom-3),new Point(bounds.Right-2,bounds.Top+3)});
        }
    }

    // Native button. Optional bounded transitions have no timer when idle.
    internal sealed class NativeActionButton : Button {
        internal bool NavigationSelected;
        private bool hovered,pressed;
        private Color? transitionFill;
        internal NativeActionButton(){SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer,true);}
        private Color TargetFill {get{return !Enabled?Ui.DisabledSurface:pressed?FlatAppearance.MouseDownBackColor:hovered?FlatAppearance.MouseOverBackColor:BackColor;}}
        private void TransitionFrom(Color previous){VisualEffects.Transition(this,previous,TargetFill,delegate(Color value){transitionFill=value;Invalidate();},delegate{transitionFill=null;Invalidate();});}
        protected override void OnMouseEnter(EventArgs e){Color previous=transitionFill??TargetFill;hovered=true;TransitionFrom(previous);base.OnMouseEnter(e);}
        protected override void OnMouseLeave(EventArgs e){Color previous=transitionFill??TargetFill;hovered=false;pressed=false;TransitionFrom(previous);base.OnMouseLeave(e);}
        protected override void OnMouseDown(MouseEventArgs e){Color previous=transitionFill??TargetFill;if(e.Button==MouseButtons.Left)pressed=true;TransitionFrom(previous);base.OnMouseDown(e);}
        protected override void OnMouseUp(MouseEventArgs e){Color previous=transitionFill??TargetFill;pressed=false;TransitionFrom(previous);base.OnMouseUp(e);}
        protected override void OnEnabledChanged(EventArgs e){VisualEffects.Cancel(this);Invalidate();base.OnEnabledChanged(e);}
        protected override void OnVisibleChanged(EventArgs e){if(!Visible)VisualEffects.Cancel(this);base.OnVisibleChanged(e);}
        protected override void OnBackColorChanged(EventArgs e){VisualEffects.Cancel(this);base.OnBackColorChanged(e);}
        protected override void Dispose(bool disposing){if(disposing)VisualEffects.Cancel(this);base.Dispose(disposing);}
        protected override void OnPaint(PaintEventArgs e){
            e.Graphics.Clear(Parent==null?Ui.Canvas:Parent.BackColor);e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;
            Color fill=transitionFill??TargetFill;
            RectangleF rect=new RectangleF(.5f,.5f,Math.Max(1,Width-1),Math.Max(1,Height-1));float radius=Math.Min(8,Math.Min(rect.Width,rect.Height)/2);
            using(var path=new GraphicsPath()){
                float d=radius*2;path.AddArc(rect.Left,rect.Top,d,d,180,90);path.AddArc(rect.Right-d,rect.Top,d,d,270,90);path.AddArc(rect.Right-d,rect.Bottom-d,d,d,0,90);path.AddArc(rect.Left,rect.Bottom-d,d,d,90,90);path.CloseFigure();
                using(var brush=new SolidBrush(fill))e.Graphics.FillPath(brush,path);
                if(FlatAppearance.BorderSize>0)using(var pen=new Pen(Enabled?FlatAppearance.BorderColor:Ui.Line))e.Graphics.DrawPath(pen,path);
            }
            TextFormatFlags flags=TextFormatFlags.EndEllipsis|(Text.IndexOf('\n')>=0?TextFormatFlags.WordBreak:TextFormatFlags.SingleLine);
            if(!UseMnemonic)flags|=TextFormatFlags.NoPrefix;
            if(TextAlign==ContentAlignment.TopLeft||TextAlign==ContentAlignment.MiddleLeft||TextAlign==ContentAlignment.BottomLeft)flags|=TextFormatFlags.Left;
            else if(TextAlign==ContentAlignment.TopRight||TextAlign==ContentAlignment.MiddleRight||TextAlign==ContentAlignment.BottomRight)flags|=TextFormatFlags.Right;
            else flags|=TextFormatFlags.HorizontalCenter;
            if(TextAlign==ContentAlignment.TopLeft||TextAlign==ContentAlignment.TopCenter||TextAlign==ContentAlignment.TopRight)flags|=TextFormatFlags.Top;
            else if(TextAlign==ContentAlignment.BottomLeft||TextAlign==ContentAlignment.BottomCenter||TextAlign==ContentAlignment.BottomRight)flags|=TextFormatFlags.Bottom;
            else flags|=TextFormatFlags.VerticalCenter;
            int left=Math.Max(7,Padding.Left),right=Math.Max(7,Padding.Right);
            TextRenderer.DrawText(e.Graphics,Text,Font,new Rectangle(left,Math.Max(2,Padding.Top),Math.Max(1,Width-left-right),Math.Max(1,Height-Math.Max(2,Padding.Top)-Math.Max(2,Padding.Bottom))),Enabled?ForeColor:Ui.DisabledInk,flags);
            if(NavigationSelected){int markerWidth=Math.Max(3,Font.Height/5);using(var marker=new SolidBrush(Ui.Primary))e.Graphics.FillRectangle(marker,2,Height/4,markerWidth,Height/2);}
            if(Focused&&ShowFocusCues)ControlPaint.DrawFocusRectangle(e.Graphics,new Rectangle(5,5,Math.Max(1,Width-10),Math.Max(1,Height-10)),ForeColor,fill);
        }
    }
}
