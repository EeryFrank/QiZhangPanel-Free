// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    internal struct ResourceSample {
        internal const int MaximumSamples=360;
        internal readonly double Value;
        internal readonly string Timestamp;
        internal readonly bool BackendTime;
        internal ResourceSample(double value,string timestamp,DateTimeOffset received) {
            Value=value;BackendTime=!String.IsNullOrWhiteSpace(timestamp);
            // Keep the backend's timezone and precision. A missing timestamp is
            // explicitly labelled as receipt time, never invented server time.
            Timestamp=BackendTime?timestamp.Replace('T',' '):received.ToString("yyyy-MM-dd HH:mm:ss.fff zzz",CultureInfo.InvariantCulture);
        }
        internal static bool IsValid(double value){return !Double.IsNaN(value)&&!Double.IsInfinity(value)&&value>=0;}
        internal static bool TryValue(object raw,out double value){
            value=0;return raw!=null&&Double.TryParse(Convert.ToString(raw,CultureInfo.InvariantCulture),NumberStyles.Float,CultureInfo.InvariantCulture,out value)&&IsValid(value);
        }
        internal static void Append(List<ResourceSample> history,ResourceSample sample){
            if(!IsValid(sample.Value))return;
            if(history.Count>=MaximumSamples)history.RemoveRange(0,history.Count-MaximumSamples+1);
            history.Add(sample);
        }
        internal string Clock {
            get {int space=Timestamp.IndexOf(' ');return space>=0&&Timestamp.Length>=space+9?Timestamp.Substring(space+1,8):Timestamp;}
        }
    }

    internal sealed class ResourceTrend : Control {
        private readonly string title,unit;
        private List<ResourceSample> samples=new List<ResourceSample>();
        private PointF[] points=new PointF[0];
        private int selected=-1;
        private Point? pointer;
        private Rectangle plot;
        internal string HoverText { get; private set; }
        internal int SelectedSample { get {return selected;} }
        internal ResourceTrend(string text,string suffix){
            title=text;unit=suffix;Height=182;MinimumSize=new Size(180,140);TabStop=true;AccessibleName=text;AccessibleRole=AccessibleRole.Chart;
            SetStyle(ControlStyles.OptimizedDoubleBuffer|ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.ResizeRedraw,true);
            HoverText="";AccessibleDescription="等待真实采样。鼠标靠近节点可查看数值和时间。";
        }
        internal void SetSamples(List<ResourceSample> values){
            // The bounded list is reused and can roll while its last value and
            // timestamp stay identical. Always rebind the hovered node as well.
            samples=values;int count=values.Count;
            LayoutPoints();if(pointer.HasValue)SelectAt(pointer.Value);else if(selected>=count)SetSelection(-1);else UpdateDescription();Invalidate();
        }
        private void LayoutPoints(){
            plot=Rectangle.FromLTRB(15,60,Math.Max(16,Width-16),Math.Max(61,Height-42));
            if(points.Length!=samples.Count)points=new PointF[samples.Count];
            double maximum=1;foreach(var sample in samples)maximum=Math.Max(maximum,sample.Value);
            for(int i=0;i<samples.Count;i++)points[i]=new PointF(samples.Count==1?plot.Left+plot.Width/2f:plot.Left+plot.Width*i/(float)(samples.Count-1),plot.Bottom-(float)(samples[i].Value/maximum)*plot.Height);
        }
        private void UpdateDescription(){
            HoverText=selected>=0&&selected<samples.Count?title+"："+samples[selected].Value.ToString("G",CultureInfo.CurrentCulture)+unit+"\n"+(samples[selected].BackendTime?"后台采样：":"本机接收（后台未提供时间）：")+"\n"+samples[selected].Timestamp:"";
            AccessibleDescription=HoverText.Length>0?HoverText:"保留最近 "+samples.Count+" 个实际采样节点（最多 "+ResourceSample.MaximumSamples+" 个）。悬停或用左右键查看具体数值和时间。";
        }
        private void SetSelection(int index){if(selected==index){UpdateDescription();return;}selected=index;UpdateDescription();Invalidate();}
        private void SelectAt(Point location){
            if(samples.Count==0||location.X<plot.Left||location.X>plot.Right||location.Y<plot.Top-8||location.Y>plot.Bottom+8){SetSelection(-1);return;}
            int index=samples.Count==1?0:(int)Math.Round((location.X-plot.Left)*(samples.Count-1)/(double)Math.Max(1,plot.Width));
            SetSelection(Math.Max(0,Math.Min(samples.Count-1,index)));
        }
        protected override void OnMouseMove(MouseEventArgs e){base.OnMouseMove(e);pointer=e.Location;SelectAt(e.Location);}
        protected override void OnMouseLeave(EventArgs e){base.OnMouseLeave(e);pointer=null;SetSelection(-1);}
        protected override void OnResize(EventArgs e){base.OnResize(e);LayoutPoints();if(pointer.HasValue)SelectAt(pointer.Value);}
        protected override bool IsInputKey(Keys keyData){return keyData==Keys.Left||keyData==Keys.Right||keyData==Keys.Home||keyData==Keys.End||base.IsInputKey(keyData);}
        protected override void OnKeyDown(KeyEventArgs e){
            base.OnKeyDown(e);if(samples.Count==0)return;int index=selected;
            if(e.KeyCode==Keys.Left)index=selected<0?samples.Count-1:Math.Max(0,selected-1);
            else if(e.KeyCode==Keys.Right)index=Math.Min(samples.Count-1,selected+1);
            else if(e.KeyCode==Keys.Home)index=0;else if(e.KeyCode==Keys.End)index=samples.Count-1;else if(e.KeyCode==Keys.Escape)index=-1;else return;
            pointer=null;SetSelection(index);e.Handled=true;e.SuppressKeyPress=true;
        }
        protected override void OnLostFocus(EventArgs e){base.OnLostFocus(e);if(!pointer.HasValue)SetSelection(-1);}
        protected override void OnPaint(PaintEventArgs e){
            base.OnPaint(e);LayoutPoints();e.Graphics.Clear(Ui.Surface);e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;
            TextRenderer.DrawText(e.Graphics,title,Ui.HeaderFont,new Rectangle(14,9,Width-28,24),Ui.Ink,TextFormatFlags.Left|TextFormatFlags.EndEllipsis);
            if(samples.Count==0){TextRenderer.DrawText(e.Graphics,"等待真实采样",Ui.BodyFont,new Rectangle(14,52,Width-28,40),Ui.Muted,TextFormatFlags.Left|TextFormatFlags.WordBreak);return;}
            double maximum=0;foreach(var sample in samples)maximum=Math.Max(maximum,sample.Value);
            TextRenderer.DrawText(e.Graphics,"最近 "+samples.Count+" 次 · 最高 "+maximum.ToString("0.##")+unit,Ui.BodyFont,new Rectangle(14,32,Width-28,22),Ui.Muted,TextFormatFlags.Left|TextFormatFlags.EndEllipsis);
            using(var grid=new Pen(Ui.Line)){e.Graphics.DrawLine(grid,plot.Left,plot.Top,plot.Right,plot.Top);e.Graphics.DrawLine(grid,plot.Left,plot.Bottom,plot.Right,plot.Bottom);}
            if(points.Length>1)using(var line=new Pen(Ui.Primary,1.7f))e.Graphics.DrawLines(line,points);
            using(var dot=new SolidBrush(Ui.Primary))foreach(var point in points)e.Graphics.FillEllipse(dot,point.X-2,point.Y-2,4,4);
            int half=Math.Max(1,(Width-28)/2);TextRenderer.DrawText(e.Graphics,samples[0].Clock,Ui.BodyFont,new Rectangle(14,Height-39,half,18),Ui.Muted,TextFormatFlags.Left|TextFormatFlags.EndEllipsis);
            if(samples.Count>1)TextRenderer.DrawText(e.Graphics,samples[samples.Count-1].Clock,Ui.BodyFont,new Rectangle(Width-half-14,Height-39,half,18),Ui.Muted,TextFormatFlags.Right|TextFormatFlags.EndEllipsis);
            TextRenderer.DrawText(e.Graphics,"悬停吸附节点 · 最多保留 "+ResourceSample.MaximumSamples+" 次",Ui.BodyFont,new Rectangle(14,Height-21,Width-28,18),Ui.Muted,TextFormatFlags.Left|TextFormatFlags.EndEllipsis);
            if(selected<0||selected>=points.Length)return;
            var focus=points[selected];using(var guide=new Pen(Ui.Muted,1)){guide.DashStyle=DashStyle.Dot;e.Graphics.DrawLine(guide,focus.X,plot.Top,focus.X,plot.Bottom);}
            using(var fill=new SolidBrush(Ui.Surface))e.Graphics.FillEllipse(fill,focus.X-5,focus.Y-5,10,10);
            using(var border=new Pen(Ui.Primary,2))e.Graphics.DrawEllipse(border,focus.X-5,focus.Y-5,10,10);
            UpdateDescription();int maxWidth=Math.Max(120,Math.Min(355,Width-22));var flags=TextFormatFlags.Left|TextFormatFlags.WordBreak|TextFormatFlags.NoPrefix;
            var measured=TextRenderer.MeasureText(HoverText,Ui.BodyFont,new Size(maxWidth-18,Int32.MaxValue),flags);int boxWidth=Math.Min(maxWidth,measured.Width+18),boxHeight=measured.Height+14;
            int boxX=(int)focus.X+13;if(boxX+boxWidth>Width-8)boxX=(int)focus.X-boxWidth-13;boxX=Math.Max(8,Math.Min(Width-boxWidth-8,boxX));int boxY=Math.Max(5,Math.Min(Height-boxHeight-5,(int)focus.Y-boxHeight-12));
            var box=new Rectangle(boxX,boxY,boxWidth,boxHeight);using(var fill=new SolidBrush(Ui.Surface))e.Graphics.FillRectangle(fill,box);using(var border=new Pen(Ui.Primary))e.Graphics.DrawRectangle(border,box);
            TextRenderer.DrawText(e.Graphics,HoverText,Ui.BodyFont,Rectangle.Inflate(box,-8,-6),Ui.Ink,flags);
        }
    }
}
