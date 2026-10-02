// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using QiZhang.Shared;

namespace QiZhang.NativePanel {
    internal static class WindowChrome {
        private static readonly ConditionalWeakTable<Form,Frame> frames=new ConditionalWeakTable<Form,Frame>();
        internal static void Attach(Form form){
            if(form==null||form.IsDisposed)return;Frame frame;
            if(!frames.TryGetValue(form,out frame)){frame=new Frame(form);frames.Add(form,frame);frame.Install();}
            frame.Refresh();
        }
        internal static void Refresh(Form form){Attach(form);}
        internal static void SetFullScreen(Form form,bool value){Attach(form);frames.GetValue(form,delegate(Form f){throw new InvalidOperationException();}).SetFullScreen(value);}
        internal static void SetSettingsAction(Form form,Action action){Attach(form);frames.GetValue(form,delegate(Form f){throw new InvalidOperationException();}).SetSettings(action);}

        private sealed class Frame {
            internal readonly Form Owner;
            internal readonly bool Resizable;
            internal bool FullScreen;
            private Panel body;
            private Caption caption;
            private FrameWindow window;
            private bool installing,disposed;
            private Size minimum,maximum;
            internal Frame(Form owner){Owner=owner;Resizable=owner.FormBorderStyle==FormBorderStyle.Sizable||owner.FormBorderStyle==FormBorderStyle.SizableToolWindow;}
            internal void Install(){
                installing=true;Size original=Owner.ClientSize;Padding padding=Owner.Padding;minimum=Owner.MinimumSize;maximum=Owner.MaximumSize;
                body=new Panel {Name="WindowChromeBody",Dock=DockStyle.Fill,Padding=padding,Margin=new Padding(0)};
                var controls=new Control[Owner.Controls.Count];Owner.Controls.CopyTo(controls,0);
                Owner.SuspendLayout();foreach(Control control in controls)Owner.Controls.Remove(control);body.Controls.AddRange(controls);
                Owner.FormBorderStyle=FormBorderStyle.None;Owner.Padding=new Padding(1);caption=new Caption(this){Name="WindowChromeCaption",Dock=DockStyle.Top,Height=42};
                Owner.Controls.Add(body);Owner.Controls.Add(caption);Ui.Role(body,"canvas");Ui.Role(caption,"surface");Owner.ClientSize=new Size(original.Width+2,original.Height+caption.Height+2);Owner.MinimumSize=minimum;Owner.MaximumSize=maximum;
                Owner.ControlAdded+=Added;Owner.TextChanged+=Changed;Owner.Resize+=Changed;Owner.FontChanged+=Changed;Owner.VisibleChanged+=Changed;Owner.Disposed+=Disposed;
                window=new FrameWindow(this);Owner.ResumeLayout(true);installing=false;
            }
            private void Added(object sender,ControlEventArgs e){if(installing||e.Control==body||e.Control==caption)return;Owner.Controls.Remove(e.Control);body.Controls.Add(e.Control);e.Control.BringToFront();}
            private void Changed(object sender,EventArgs e){Refresh();}
            internal void Refresh(){if(disposed||caption==null)return;Owner.BackColor=Ui.Line;body.BackColor=Ui.Canvas;caption.BackColor=Ui.Surface;caption.ForeColor=Ui.Ink;caption.UpdateButtons();caption.Invalidate();}
            internal void SetFullScreen(bool value){FullScreen=value;caption.Visible=!value;Owner.Padding=value?new Padding(0):new Padding(1);if(window!=null)window.RefreshStyles();}
            internal void SetSettings(Action action){caption.SetSettings(action);}
            internal void ToggleMaximize(){if(!Owner.MaximizeBox||FullScreen)return;Owner.WindowState=Owner.WindowState==FormWindowState.Maximized?FormWindowState.Normal:FormWindowState.Maximized;}
            internal void Drag(){if(FullScreen)return;Native.ReleaseCapture();Native.SendMessage(Owner.Handle,0xA1,new IntPtr(2),IntPtr.Zero);}
            private void Disposed(object sender,EventArgs e){disposed=true;Owner.ControlAdded-=Added;Owner.TextChanged-=Changed;Owner.Resize-=Changed;Owner.FontChanged-=Changed;Owner.VisibleChanged-=Changed;Owner.Disposed-=Disposed;if(window!=null)window.Dispose();}
        }

        private sealed class Caption:Panel {
            private readonly Frame frame;
            private readonly ChromeButton minimize,maximize,close,settings;
            private readonly ToolTip tips=new ToolTip();
            private Action settingsAction;
            internal Caption(Frame value){frame=value;DoubleBuffered=true;
                close=AddButton("ChromeClose","关闭窗口","close",delegate{frame.Owner.Close();});
                maximize=AddButton("ChromeMaximize","最大化 / 还原","maximize",delegate{frame.ToggleMaximize();});
                minimize=AddButton("ChromeMinimize","最小化","minimize",delegate{frame.Owner.WindowState=FormWindowState.Minimized;});
                settings=AddButton("ChromeSettings","软件设置","settings",delegate{if(settingsAction!=null)settingsAction();});settings.Visible=false;
                Resize+=delegate{LayoutButtons();};MouseDown+=delegate(object sender,MouseEventArgs e){if(e.Button==MouseButtons.Left){if(e.Clicks==2)frame.ToggleMaximize();else frame.Drag();}};
            }
            private ChromeButton AddButton(string name,string description,string kind,Action action){var button=new ChromeButton(kind,action){Name=name,AccessibleName=description,AccessibleRole=AccessibleRole.PushButton,TabStop=true};tips.SetToolTip(button,description);Controls.Add(button);return button;}
            internal void SetSettings(Action value){settingsAction=value;settings.Visible=value!=null;LayoutButtons();}
            internal void UpdateButtons(){close.Visible=frame.Owner.ControlBox;maximize.Visible=frame.Owner.ControlBox&&frame.Owner.MaximizeBox;minimize.Visible=frame.Owner.ControlBox&&frame.Owner.MinimizeBox;settings.Visible=settingsAction!=null;maximize.Restore=frame.Owner.WindowState==FormWindowState.Maximized;LayoutButtons();foreach(Control c in Controls)c.Invalidate();}
            private bool Wanted(ChromeButton button){return button==settings?settingsAction!=null:frame.Owner.ControlBox&&(button==close||(button==maximize?frame.Owner.MaximizeBox:frame.Owner.MinimizeBox));}
            private void LayoutButtons(){int right=Width-4;foreach(ChromeButton button in new[]{close,maximize,minimize,settings})if(Wanted(button)){button.Bounds=new Rectangle(right-42,4,40,Math.Max(24,Height-8));right-=44;}Invalidate();}
            protected override void OnPaint(PaintEventArgs e){base.OnPaint(e);int iconSize=24,x=14;var icon=frame.Owner.Icon;if(icon!=null&&frame.Owner.ShowIcon){using(var brush=new SolidBrush(AppTheme.IsDark?Ui.Canvas:Ui.Ink))e.Graphics.FillRectangle(brush,new Rectangle(x-3,(Height-30)/2,30,30));e.Graphics.DrawIcon(icon,new Rectangle(x,(Height-iconSize)/2,iconSize,iconSize));x+=34;}int right=Width-12;foreach(ChromeButton button in Controls)if(Wanted(button))right=Math.Min(right,button.Left-10);TextRenderer.DrawText(e.Graphics,frame.Owner.Text,frame.Owner.Font,new Rectangle(x,0,Math.Max(0,right-x),Height),Ui.Ink,TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine|TextFormatFlags.EndEllipsis|TextFormatFlags.NoPrefix);using(var pen=new Pen(Ui.Line))e.Graphics.DrawLine(pen,0,Height-1,Width,Height-1);}
            protected override void Dispose(bool disposing){if(disposing)tips.Dispose();base.Dispose(disposing);}
        }

        private sealed class ChromeButton:Control {
            private readonly string kind;private readonly Action action;private bool hovered,pressed;internal bool Restore;
            internal ChromeButton(string type,Action callback){kind=type;action=callback;SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer|ControlStyles.Selectable|ControlStyles.StandardClick,true);SetStyle(ControlStyles.StandardDoubleClick,false);Cursor=Cursors.Default;}
            protected override void OnMouseEnter(EventArgs e){hovered=true;Invalidate();base.OnMouseEnter(e);}
            protected override void OnMouseLeave(EventArgs e){hovered=false;pressed=false;Invalidate();base.OnMouseLeave(e);}
            protected override void OnMouseDown(MouseEventArgs e){if(e.Button==MouseButtons.Left){pressed=true;Capture=true;Invalidate();}base.OnMouseDown(e);}
            // StandardClick already dispatches Click from the native mouse-up message.
            // Dispatching it again here immediately restores a just-maximized window.
            protected override void OnMouseUp(MouseEventArgs e){pressed=false;Capture=false;Invalidate();base.OnMouseUp(e);}
            protected override void OnKeyDown(KeyEventArgs e){if(e.KeyCode==Keys.Enter||e.KeyCode==Keys.Space){e.Handled=true;OnClick(EventArgs.Empty);}base.OnKeyDown(e);}
            protected override void OnClick(EventArgs e){var mouse=e as MouseEventArgs;if(mouse!=null&&mouse.Button!=MouseButtons.Left)return;if(Enabled)action();base.OnClick(e);}
            protected override void OnGotFocus(EventArgs e){Invalidate();base.OnGotFocus(e);}
            protected override void OnLostFocus(EventArgs e){Invalidate();base.OnLostFocus(e);}
            protected override void OnPaint(PaintEventArgs e){Color fill=pressed?Ui.PrimarySoft:hovered?Ui.PrimarySoft:Ui.Surface;e.Graphics.Clear(fill);e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;float x=Width/2f,y=Height/2f;Color ink=kind=="close"&&hovered?Ui.Danger:kind=="settings"?Ui.Primary:Ui.Ink;using(var pen=new Pen(ink,1.5f)){
                if(kind=="close"){e.Graphics.DrawLine(pen,x-5,y-5,x+5,y+5);e.Graphics.DrawLine(pen,x+5,y-5,x-5,y+5);}
                else if(kind=="minimize")e.Graphics.DrawLine(pen,x-6,y+3,x+6,y+3);
                else if(kind=="maximize"){if(Restore){e.Graphics.DrawLines(pen,new[]{new PointF(x-3,y-5),new PointF(x+6,y-5),new PointF(x+6,y+3)});e.Graphics.DrawRectangle(pen,x-6,y-2,9,8);}else e.Graphics.DrawRectangle(pen,x-5,y-5,10,10);}
                else{e.Graphics.DrawEllipse(pen,x-5,y-5,10,10);e.Graphics.DrawEllipse(pen,x-1.5f,y-1.5f,3,3);for(int i=0;i<8;i++){double a=i*Math.PI/4;e.Graphics.DrawLine(pen,x+(float)Math.Cos(a)*5,y+(float)Math.Sin(a)*5,x+(float)Math.Cos(a)*8,y+(float)Math.Sin(a)*8);}}
            }if(Focused)ControlPaint.DrawFocusRectangle(e.Graphics,Rectangle.Inflate(ClientRectangle,-3,-3),Ui.Ink,fill);}
        }

        private sealed class FrameWindow:NativeWindow,IDisposable {
            private readonly Frame frame;private bool disposed;
            internal FrameWindow(Frame owner){frame=owner;frame.Owner.HandleCreated+=Created;frame.Owner.HandleDestroyed+=Destroyed;if(frame.Owner.IsHandleCreated)Created(null,EventArgs.Empty);}
            private void Created(object sender,EventArgs e){if(disposed)return;AssignHandle(frame.Owner.Handle);RefreshStyles();}
            private void Destroyed(object sender,EventArgs e){ReleaseHandle();}
            internal void RefreshStyles(){if(Handle==IntPtr.Zero)return;int style=Native.GetWindowLong(Handle,-16);style&=~0x00C00000;style|=0x00080000;if(frame.Resizable&&!frame.FullScreen)style|=0x00040000;else style&=~0x00040000;if(frame.Owner.MinimizeBox)style|=0x00020000;if(frame.Owner.MaximizeBox)style|=0x00010000;Native.SetWindowLong(Handle,-16,style);Native.SetWindowPos(Handle,IntPtr.Zero,0,0,0,0,0x0020|0x0001|0x0002|0x0004|0x0010);}
            protected override void WndProc(ref Message m){
                // WinForms can restore WS_CAPTION during WindowState/handle transitions.
                // Keep the real resizing/system-menu styles while reserving drawing to us.
                if(m.Msg==0x7C&&m.WParam.ToInt64()==-16){var styles=(Native.STYLESTRUCT)Marshal.PtrToStructure(m.LParam,typeof(Native.STYLESTRUCT));styles.next&=~0x00C00000;Marshal.StructureToPtr(styles,m.LParam,false);}
                if(m.Msg==0x83){m.Result=IntPtr.Zero;return;}
                if(m.Msg==0x85){m.Result=IntPtr.Zero;return;}
                if(m.Msg==0x86){m.Result=new IntPtr(1);return;}
                if(m.Msg==0x24){base.WndProc(ref m);var info=(Native.MINMAXINFO)Marshal.PtrToStructure(m.LParam,typeof(Native.MINMAXINFO));var monitor=new Native.MONITORINFO {cbSize=Marshal.SizeOf(typeof(Native.MONITORINFO))};if(Native.GetMonitorInfo(Native.MonitorFromWindow(Handle,2),ref monitor)){var area=frame.FullScreen?monitor.monitor:monitor.work;info.maxPosition.x=area.left-monitor.monitor.left;info.maxPosition.y=area.top-monitor.monitor.top;info.maxSize.x=area.right-area.left;info.maxSize.y=area.bottom-area.top;}Marshal.StructureToPtr(info,m.LParam,false);return;}
                if(m.Msg==0x84&&frame.Resizable&&!frame.FullScreen&&frame.Owner.WindowState==FormWindowState.Normal){base.WndProc(ref m);long raw=m.LParam.ToInt64();var point=frame.Owner.PointToClient(new Point((short)(raw&0xffff),(short)((raw>>16)&0xffff)));int border=7;bool left=point.X<border,right=point.X>=frame.Owner.ClientSize.Width-border,top=point.Y<border,bottom=point.Y>=frame.Owner.ClientSize.Height-border;int hit=top?(left?13:right?14:12):bottom?(left?16:right?17:15):left?10:right?11:0;if(hit!=0)m.Result=new IntPtr(hit);return;}
                base.WndProc(ref m);
            }
            public void Dispose(){if(disposed)return;disposed=true;frame.Owner.HandleCreated-=Created;frame.Owner.HandleDestroyed-=Destroyed;ReleaseHandle();}
        }
        private static class Native {
            [StructLayout(LayoutKind.Sequential)]internal struct POINT{internal int x,y;}
            [StructLayout(LayoutKind.Sequential)]internal struct STYLESTRUCT{internal int previous,next;}
            [StructLayout(LayoutKind.Sequential)]internal struct MINMAXINFO{internal POINT reserved,maxSize,maxPosition,minTrackSize,maxTrackSize;}
            [StructLayout(LayoutKind.Sequential)]internal struct RECT{internal int left,top,right,bottom;}
            [StructLayout(LayoutKind.Sequential)]internal struct MONITORINFO{internal int cbSize;internal RECT monitor,work;internal int flags;}
            [DllImport("user32.dll")]internal static extern bool ReleaseCapture();
            [DllImport("user32.dll")]internal static extern IntPtr SendMessage(IntPtr h,int msg,IntPtr w,IntPtr l);
            [DllImport("user32.dll")]internal static extern int GetWindowLong(IntPtr h,int index);
            [DllImport("user32.dll")]internal static extern int SetWindowLong(IntPtr h,int index,int value);
            [DllImport("user32.dll")]internal static extern bool SetWindowPos(IntPtr h,IntPtr after,int x,int y,int cx,int cy,int flags);
            [DllImport("user32.dll")]internal static extern IntPtr MonitorFromWindow(IntPtr h,int flags);
            [DllImport("user32.dll")]internal static extern bool GetMonitorInfo(IntPtr h,ref MONITORINFO info);
        }
    }
}
