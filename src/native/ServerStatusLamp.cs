// 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;
using QiZhang.Shared;

namespace QiZhang.NativePanel {
    // A static owner-drawn circle: no polling, flashing, timers or animation.
    internal sealed class ServerStatusLamp : Control {
        private string state="warning";
        internal string State {get{return state;}}
        internal Color LampColor {get {
            switch(state){
                case "running":return AppTheme.IsDark?Color.FromArgb(99,207,161):Color.FromArgb(20,129,77);
                case "failed":return Ui.Danger;
                case "stopped":return Ui.Muted;
                default:return Ui.Warning;
            }
        }}
        internal ServerStatusLamp(){SetStyle(ControlStyles.UserPaint|ControlStyles.OptimizedDoubleBuffer|ControlStyles.AllPaintingInWmPaint|ControlStyles.SupportsTransparentBackColor,true);BackColor=Color.Transparent;TabStop=false;AccessibleRole=AccessibleRole.Indicator;}
        internal void SetState(string next,string description){AccessibleName="服务器状态："+description;if(state==next)return;state=next;Invalidate();}
        protected override void OnPaint(PaintEventArgs e){base.OnPaint(e);e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;int diameter=Math.Min(18,Math.Min(Width,Height)-4);if(diameter<2)return;var circle=new Rectangle((Width-diameter)/2,(Height-diameter)/2,diameter,diameter);using(var fill=new SolidBrush(LampColor))e.Graphics.FillEllipse(fill,circle);using(var border=new Pen(LampColor,1f))e.Graphics.DrawEllipse(border,circle);}
    }
}
