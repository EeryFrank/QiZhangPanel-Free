// Copyright (c) 2026 EeryFrank - https://github.com/EeryFrank
using System;
using System.Drawing;
using System.Windows.Forms;

namespace QiZhang.NativePanel {
    // A clipped, single-column native viewport. There is no horizontal scroll surface.
    // Keep one scrollbar and the existing controls; no page cache, timer or animation.
    internal sealed class NavigationViewport : Panel {
        private readonly Panel clip, stack;
        private readonly VScrollBar scroll;
        private bool arranging;
        private int wheelRemainder;
        private float layoutScale = 1F;
        internal NavigationViewport() {
            Name = "GroupedNavigation"; AutoScroll = false; TabStop = false;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
            clip = new Panel { Name = "NavigationClip", AutoScroll = false, TabStop = false };
            stack = new Panel { Name = "NavigationStack", AutoScroll = false, TabStop = false };
            scroll = new VScrollBar { Name = "NavigationScroll", Visible = false, TabStop = false };
            clip.Controls.Add(stack); Controls.Add(clip); Controls.Add(scroll);
            foreach (Control item in new Control[] { this, clip, stack, scroll }) Ui.Role(item, "sidebar");
            scroll.ValueChanged += delegate { PositionStack(); };
            clip.Resize += delegate { Arrange(); };
        }
        internal void AddSection(NavigationSection section) {
            stack.Controls.Add(section);
            foreach (Control child in section.Controls) {
                child.Enter += delegate(object sender, EventArgs args) { EnsureVisible((Control)sender); };
            }
            section.FontChanged += delegate { Arrange(); };
            Arrange();
        }
        protected override void OnLayout(LayoutEventArgs args) { base.OnLayout(args); Arrange(); }
        protected override void ScaleControl(SizeF factor, BoundsSpecified specified) {
            layoutScale *= factor.Height;
            base.ScaleControl(factor, specified); Arrange();
        }
        private void Arrange() {
            if (arranging || clip == null || stack == null || scroll == null || IsDisposed) return;
            arranging = true;
            try {
                int gap = Math.Max(1, (int)Math.Round(12 * layoutScale));
                int height = 0;
                foreach (NavigationSection section in stack.Controls) height += section.PreferredHeight + gap;
                height = Math.Max(0, height - gap);
                bool needed = height > ClientSize.Height && ClientSize.Height > 0;
                scroll.Visible = needed;
                // Calculate independently of delayed docking so a resize cannot retain old widths.
                int width = Math.Max(0, ClientSize.Width - (needed ? scroll.Width : 0));
                int viewHeight = Math.Max(1, ClientSize.Height);
                // Explicit bounds also cover the first reveal after a hidden sidebar.
                // Toggling Visible inside Dock layout can leave the native scrollbar at height 0.
                clip.SetBounds(0, 0, width, ClientSize.Height);
                scroll.SetBounds(width, 0, scroll.Width, ClientSize.Height);
                scroll.Minimum = 0; scroll.Maximum = Math.Max(0, height - 1);
                scroll.LargeChange = viewHeight; scroll.SmallChange = Math.Max(1, (int)Math.Round(36 * layoutScale));
                int max = Math.Max(0, height - viewHeight);
                if (scroll.Value > max) scroll.Value = max;
                if (!needed && scroll.Value != 0) scroll.Value = 0;
                stack.SetBounds(0, -scroll.Value, width, Math.Max(height, viewHeight));
                int top = 0;
                foreach (NavigationSection section in stack.Controls) {
                    section.SetBounds(0, top, width, section.PreferredHeight);
                    top += section.Height + gap;
                }
            } finally { arranging = false; }
        }
        private void PositionStack() { if (stack != null && !stack.IsDisposed && stack.Top != -scroll.Value) stack.Top = -scroll.Value; }
        internal void ScrollByWheel(int delta) {
            if (!scroll.Visible || delta == 0 || SystemInformation.MouseWheelScrollLines == 0) return;
            wheelRemainder += delta;
            int notches = wheelRemainder / 120; wheelRemainder %= 120;
            int distance = SystemInformation.MouseWheelScrollLines < 0 ? scroll.LargeChange : scroll.SmallChange * Math.Max(1, SystemInformation.MouseWheelScrollLines);
            int maximum = Math.Max(0, scroll.Maximum - scroll.LargeChange + 1);
            scroll.Value = (int)Math.Max(0L, Math.Min(maximum, (long)scroll.Value - (long)notches * distance));
        }
        protected override void OnMouseWheel(MouseEventArgs args) {
            ScrollByWheel(args.Delta);
            var handled = args as HandledMouseEventArgs; if (handled != null) handled.Handled = true;
        }
        internal void EnsureVisible(Control control) {
            if (!scroll.Visible || control == null || !stack.Contains(control)) return;
            Point position = stack.PointToClient(control.PointToScreen(Point.Empty));
            int target = scroll.Value, inset = Math.Max(1, (int)Math.Round(4 * layoutScale));
            if (position.Y < target + inset) target = Math.Max(0, position.Y - inset);
            else if (position.Y + control.Height > target + clip.ClientSize.Height - inset) target = position.Y + control.Height - clip.ClientSize.Height + inset;
            scroll.Value = Math.Max(0, Math.Min(Math.Max(0, scroll.Maximum - scroll.LargeChange + 1), target));
        }
    }

    internal sealed class NavigationSection : Panel {
        private readonly Label heading;
        private float layoutScale = 1F;
        internal NavigationSection(string key, string title) {
            Name = "NavigationGroup_" + key; AccessibleName = title;
            AutoScroll = false; TabStop = false;
            SetStyle(ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint | ControlStyles.ResizeRedraw, true);
            heading = new Label { Name = "NavigationHeading_" + key, Text = title, Font = Ui.HeaderFont,
                AutoSize = false, AutoEllipsis = false, TextAlign = ContentAlignment.MiddleLeft, UseMnemonic = false };
            Controls.Add(heading); Ui.Role(this, "sidebar"); Ui.Role(heading, "navheading");
        }
        private int Unit(int pixels) { return Math.Max(1, (int)Math.Round(pixels * layoutScale)); }
        private int RowHeight(Control control) { return Math.Max(Unit(35), control.Font.Height + Unit(12)); }
        private int HeaderHeight { get { return Math.Max(Unit(32), heading.Font.Height + Unit(12)); } }
        internal int PreferredHeight {
            get { int height = HeaderHeight + Unit(5); foreach (Control child in Controls) if (child != heading) height += RowHeight(child) + Unit(2); return height; }
        }
        internal void AddItem(Button button) { Controls.Add(button); button.TabIndex = Controls.Count - 2; PerformLayout(); }
        protected override void ScaleControl(SizeF factor, BoundsSpecified specified) { layoutScale *= factor.Height; base.ScaleControl(factor, specified); }
        protected override void OnFontChanged(EventArgs args) { base.OnFontChanged(args); PerformLayout(); if (Parent != null) Parent.PerformLayout(); }
        protected override void OnLayout(LayoutEventArgs args) {
            base.OnLayout(args); if (heading == null) return;
            int inset = Unit(5), width = Math.Max(0, ClientSize.Width - inset * 2);
            heading.Padding = new Padding(Unit(13), 0, Unit(5), 0);
            heading.SetBounds(1, 1, Math.Max(0, ClientSize.Width - 2), HeaderHeight - 1);
            int top = HeaderHeight;
            foreach (Control child in Controls) if (child != heading) {
                child.SetBounds(inset, top, width, RowHeight(child)); top += child.Height + Unit(2);
            }
        }
        protected override void OnPaint(PaintEventArgs args) {
            base.OnPaint(args);
            using (var pen = new Pen(Ui.Line)) args.Graphics.DrawRectangle(pen, 0, 0, Math.Max(0, Width - 1), Math.Max(0, Height - 1));
        }
    }
}
