// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
// WPF is initialized only after fancy mode AND animations are enabled.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Runtime.CompilerServices;
using System.Windows.Forms;
using System.Windows.Forms.Integration;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Interop;
using WpfColor=System.Windows.Media.Color;
using DrawingColor=System.Drawing.Color;

namespace QiZhang.NativePanel {
    internal static class VisualEffects {
        private static string mode="economy";
        private static bool animations=true,hardware=true;
        private static IPageEffects engine;
        private static bool engineFailed;
        private static Timer timer;
        private static readonly List<ColorTransition> transitions=new List<ColorTransition>();
        internal static bool Enabled {get{return mode=="fancy"&&animations;}}
        internal static bool EngineLoaded {get{return engine!=null;}}
        internal static int ActiveAnimations {get{return transitions.Count+(engine==null?0:engine.ActiveCount);}}
        internal static bool AnimationTimerRunning {get{return timer!=null&&timer.Enabled;}}
        internal static string StatusText {get{
            if(mode!="fancy")return "节省模式：动画与动效硬件加速均未启用。";
            if(!animations)return "华丽模式：动画已关闭；硬件加速偏好已保留。";
            return engine==null?(engineFailed?"当前环境无法初始化页面动效；按钮反馈仍可用。":"动效层尚未初始化。"):engine.Status;
        }}
        internal static void Configure(string requestedMode,bool animationsEnabled,bool hardwareAcceleration){
            mode=requestedMode=="fancy"?"fancy":"economy";animations=animationsEnabled;hardware=hardwareAcceleration;
            StopAll();
            if(Enabled){try{if(engine==null)engine=CreateEngine();engine.Configure(hardware);engineFailed=false;}catch(Exception){if(engine!=null)engine.Stop();engine=null;engineFailed=true;}}
        }
        [MethodImpl(MethodImplOptions.NoInlining)]private static IPageEffects CreateEngine(){return new WpfPageEffects();}
        internal static void Reveal(Control page){
            if(!Enabled||engine==null||!Usable(page))return;
            try{engine.Reveal(page);}catch(Exception){engine.Stop();}
        }
        internal static void Suspend(Form window){
            if(engine!=null)engine.Stop(window);
            for(int i=transitions.Count-1;i>=0;i--)if(window==null||transitions[i].Owner.FindForm()==window)Finish(i);
            StopTimerIfIdle();
        }
        internal static void Cancel(Control owner){for(int i=transitions.Count-1;i>=0;i--)if(transitions[i].Owner==owner)Finish(i);StopTimerIfIdle();}
        internal static void Transition(Control owner,DrawingColor from,DrawingColor to,Action<DrawingColor> draw,Action finished){
            Cancel(owner);
            if(!Enabled||!Usable(owner)||from.ToArgb()==to.ToArgb()){finished();owner.Invalidate();return;}
            draw(from);
            transitions.Add(new ColorTransition{Owner=owner,From=from,To=to,Draw=draw,Finished=finished,Started=Stopwatch.GetTimestamp()});
            if(timer==null){timer=new Timer{Interval=20};timer.Tick+=Tick;}timer.Start();
        }
        private static bool Usable(Control control){var form=control==null?null:control.FindForm();return control!=null&&!control.IsDisposed&&control.Visible&&form!=null&&form.Visible&&form.WindowState!=FormWindowState.Minimized;}
        private static void Tick(object sender,EventArgs args){
            for(int i=transitions.Count-1;i>=0;i--){var item=transitions[i];if(!Enabled||!Usable(item.Owner)){Finish(i);continue;}
                double progress=Math.Min(1,(Stopwatch.GetTimestamp()-item.Started)*1000.0/Stopwatch.Frequency/120.0);double eased=1-Math.Pow(1-progress,3);
                item.Draw(DrawingColor.FromArgb(Mix(item.From.R,item.To.R,eased),Mix(item.From.G,item.To.G,eased),Mix(item.From.B,item.To.B,eased)));
                if(progress>=1)Finish(i);
            }StopTimerIfIdle();
        }
        private static int Mix(int a,int b,double progress){return (int)Math.Round(a+(b-a)*progress);}
        private static void Finish(int index){var item=transitions[index];transitions.RemoveAt(index);if(!item.Owner.IsDisposed)item.Finished();}
        private static void StopTimerIfIdle(){if(transitions.Count==0&&timer!=null){timer.Stop();timer.Dispose();timer=null;}}
        private static void StopAll(){if(engine!=null)engine.Stop();for(int i=transitions.Count-1;i>=0;i--)Finish(i);StopTimerIfIdle();}
        private sealed class ColorTransition {internal Control Owner;internal DrawingColor From,To;internal Action<DrawingColor> Draw;internal Action Finished;internal long Started;}
        private interface IPageEffects {int ActiveCount{get;}string Status{get;}void Configure(bool useHardware);void Reveal(Control page);void Stop();void Stop(Form window);}

        // Separate type/method boundary keeps PresentationFramework unloaded in
        // the default economy path. No bitmap capture or continuous animation.
        private sealed class WpfPageEffects:IPageEffects {
            private PageReveal active;
            private bool useHardware;
            private int tier;
            public int ActiveCount{get{return active==null?0:1;}}
            public string Status{get{return !useHardware?"动效使用软件渲染（已关闭硬件加速）。":tier==0?"当前设备不支持 WPF 硬件加速，动效已回退到软件渲染。":"动效允许硬件加速（能力等级 "+tier+"）；实际渲染由 Windows 决定，必要时自动回退到软件。";}}
            public void Configure(bool requested){useHardware=requested;RenderOptions.ProcessRenderMode=requested?RenderMode.Default:RenderMode.SoftwareOnly;tier=RenderCapability.Tier>>16;}
            public void Reveal(Control page){Stop();active=new PageReveal(page,delegate{active=null;});active.Start();}
            public void Stop(){if(active!=null){var item=active;active=null;item.Dispose();}}
            public void Stop(Form window){if(active!=null&&(window==null||active.Owner==window))Stop();}
        }
        private sealed class PageReveal:IDisposable {
            private readonly Control page;
            internal readonly Form Owner;
            private readonly Action completed;
            private ElementHost host;
            private TranslateTransform translation;
            private bool disposed;
            internal PageReveal(Control page,Action completed){this.page=page;Owner=page.FindForm();this.completed=completed;}
            internal void Start(){
                int width=Math.Max(1,page.ClientSize.Width);var accent=Ui.Primary;var surface=Ui.Canvas;
                var canvas=new System.Windows.Controls.Canvas{ClipToBounds=true,Background=new SolidColorBrush(WpfColor.FromRgb(surface.R,surface.G,surface.B)),IsHitTestVisible=false};
                var gradient=new LinearGradientBrush();gradient.StartPoint=new System.Windows.Point(0,0);gradient.EndPoint=new System.Windows.Point(1,0);
                gradient.GradientStops.Add(new GradientStop(WpfColor.FromArgb(0,accent.R,accent.G,accent.B),0));gradient.GradientStops.Add(new GradientStop(WpfColor.FromArgb(255,accent.R,accent.G,accent.B),.5));gradient.GradientStops.Add(new GradientStop(WpfColor.FromArgb(0,accent.R,accent.G,accent.B),1));gradient.Freeze();
                double span=Math.Max(80,width*.4);translation=new TranslateTransform(-span,0);
                var stripe=new System.Windows.Shapes.Rectangle{Width=span,Height=3,Fill=gradient,RenderTransform=translation,IsHitTestVisible=false};canvas.Children.Add(stripe);
                host=new EffectHost {Name="TransientPageEffect",Bounds=new Rectangle(0,0,width,3),Anchor=AnchorStyles.Top|AnchorStyles.Left|AnchorStyles.Right,TabStop=false,Enabled=false,BackColor=surface,Child=canvas};
                page.Controls.Add(host);host.BringToFront();
                page.Disposed+=Changed;page.VisibleChanged+=Changed;page.SizeChanged+=Changed;if(Owner!=null){Owner.VisibleChanged+=Changed;Owner.Resize+=Changed;}
                var movement=new DoubleAnimation(-span,width,TimeSpan.FromMilliseconds(240)){FillBehavior=FillBehavior.Stop,EasingFunction=new CubicEase{EasingMode=EasingMode.EaseOut}};
                Timeline.SetDesiredFrameRate(movement,40);movement.Completed+=delegate{Dispose();};translation.BeginAnimation(TranslateTransform.XProperty,movement);
            }
            private void Changed(object sender,EventArgs args){if(page.IsDisposed||!page.Visible||Owner==null||!Owner.Visible||Owner.WindowState==FormWindowState.Minimized||sender==page)Dispose();}
            public void Dispose(){if(disposed)return;disposed=true;
                page.Disposed-=Changed;page.VisibleChanged-=Changed;page.SizeChanged-=Changed;if(Owner!=null){Owner.VisibleChanged-=Changed;Owner.Resize-=Changed;}
                if(translation!=null){translation.BeginAnimation(TranslateTransform.XProperty,null);translation=null;}
                if(host!=null){var item=host;host=null;if(!page.IsDisposed)page.Controls.Remove(item);item.Child=null;item.Dispose();}
                completed();
            }
        }
        private sealed class EffectHost:ElementHost {
            protected override CreateParams CreateParams{get{var parameters=base.CreateParams;parameters.ExStyle|=0x20|0x08000000;return parameters;}}
            protected override void WndProc(ref Message message){if(message.Msg==0x84){message.Result=new IntPtr(-1);return;}base.WndProc(ref message);}
        }
    }
}
