// QiZhang Control Panel - original panel code belongs to EeryFrank.
// https://github.com/EeryFrank - third-party rights and licenses remain unchanged.
using System;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace QiZhang.NativePanel
{
    internal sealed class OpsStackPanel : Panel
    {
        private bool arranging;
        internal OpsStackPanel() { AutoSize = true; AutoSizeMode = AutoSizeMode.GrowAndShrink; }
        private int Measure(Control child, int width)
        {
            if (child is Label) child.MaximumSize = new Size(Math.Max(1, width - child.Margin.Horizontal), 0);
            int height = child.GetPreferredSize(new Size(Math.Max(1, width - child.Margin.Horizontal), 0)).Height;
            return Math.Max(child.MinimumSize.Height, child.AutoSize ? height : child.Height);
        }
        public override Size GetPreferredSize(Size proposedSize)
        {
            int width = proposedSize.Width > 0 ? proposedSize.Width : Width;
            if (Parent != null && Parent.ClientSize.Width > 0) width = Math.Min(width, Math.Max(1, Parent.ClientSize.Width - Parent.Padding.Horizontal - Margin.Horizontal));
            int height = Padding.Vertical; foreach (Control child in Controls) height += Measure(child, width - Padding.Horizontal) + child.Margin.Vertical;
            return new Size(Math.Max(1, width), height);
        }
        protected override void OnLayout(LayoutEventArgs e)
        {
            if (arranging) return; arranging = true;
            try {
                int width = Math.Max(1, ClientSize.Width - Padding.Horizontal), top = Padding.Top;
                foreach (Control child in Controls) { int childWidth = Math.Max(1, width - child.Margin.Horizontal); child.MaximumSize = new Size(childWidth, 0); int height = Measure(child, width); top += child.Margin.Top; child.SetBounds(Padding.Left + child.Margin.Left, top, childWidth, height); top += height + child.Margin.Bottom; }
                int required = top + Padding.Bottom; if (Dock != DockStyle.Fill && Height != required) Height = required;
            } finally { arranging = false; }
            base.OnLayout(e);
        }
    }

    internal sealed partial class NativeMainForm
    {
        // Layout controls have no timers. Polling belongs to the selected page only.
        static Label OpsNote(string text, bool emphasized = false)
        {
            var label = new Label { Text = text, AutoSize = true, Dock = DockStyle.Top, Margin = new Padding(0, 3, 0, 7), Padding = new Padding(0, 2, 0, 2) };
            if (emphasized) label.Font = Ui.HeaderFont;
            Ui.Role(label, emphasized ? "" : "muted");
            label.ParentChanged += delegate { if (label.Parent != null) label.MaximumSize = new Size(Math.Max(160, label.Parent.ClientSize.Width - label.Parent.Padding.Horizontal - 12), 0); };
            return label;
        }

        static Panel OpsStack(params Control[] controls)
        {
            var stack = new OpsStackPanel { Dock = DockStyle.Top, Margin = Padding.Empty, Padding = Padding.Empty }; Ui.Role(stack, "canvas");
            foreach (Control control in controls) { control.Dock = DockStyle.None; stack.Controls.Add(control); }
            return stack;
        }

        static Panel OpsCard(Control content, string title)
        {
            var card = new Panel { Dock = DockStyle.Fill, Padding = new Padding(14), Margin = new Padding(0, 4, 0, 8) }; Ui.Role(card, "surface");
            content.Dock = DockStyle.Fill; card.Controls.Add(content);
            if (!String.IsNullOrEmpty(title)) { var heading = OpsNote(title, true); heading.Padding = new Padding(0, 0, 0, 10); card.Controls.Add(heading); }
            card.Paint += delegate(object sender, PaintEventArgs e) { using (var pen = new Pen(Ui.Line)) e.Graphics.DrawRectangle(pen, 0, 0, Math.Max(0, card.Width - 1), Math.Max(0, card.Height - 1)); };
            return card;
        }

        static void OpsCompose(Panel page, string description, Control filters, Control content, Control footer, Label activity)
        {
            var header = OpsStack(OpsNote(description), filters, activity);
            OpsDock(page, content, header, footer);
        }

        static void OpsActivity(Label label, string message, bool error = false)
        {
            if (label.IsDisposed) return;
            label.Text = message; Ui.Role(label, error ? "danger" : "muted");
        }

        async Task OpsWorking(Label activity, string running, string completed, Func<Task> action)
        {
            OpsActivity(activity, running);
            try { await action(); if (!activity.IsDisposed) OpsActivity(activity, completed + " · " + DateTime.Now.ToString("HH:mm:ss")); }
            catch (Exception error) { OpsActivity(activity, "未完成：" + error.Message, true); throw; }
        }

        static TableLayoutPanel OpsInspector(Control main, Control inspector, int inspectorWidth = 318)
        {
            // The supported minimum window still has room for two panes. Keep its
            // table tall and allow horizontal scrolling instead of reducing it to
            // only a header. Stack only for widths below the supported workspace.
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Margin = Padding.Empty };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, inspectorWidth));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            main.Dock = DockStyle.Fill; inspector.Dock = DockStyle.Fill; main.Margin = new Padding(0, 0, 10, 0); inspector.Margin = Padding.Empty;
            layout.Controls.Add(main, 0, 0); layout.Controls.Add(inspector, 1, 0); bool? compact = null;
            layout.SizeChanged += delegate {
                bool next = layout.ClientSize.Width < 650;
                int detailsWidth = layout.ClientSize.Width < 950 ? 320 : inspectorWidth;
                if (compact == next && (next || layout.ColumnStyles[1].Width == detailsWidth)) return; compact = next;
                layout.SuspendLayout();
                if (next) {
                    layout.ColumnStyles[1].Width = 0; layout.RowCount = 2; layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 204));
                    layout.SetCellPosition(inspector, new TableLayoutPanelCellPosition(0, 1)); main.Margin = new Padding(0, 0, 0, 8);
                } else {
                    layout.SetCellPosition(inspector, new TableLayoutPanelCellPosition(1, 0)); layout.RowCount = 1;
                    while (layout.RowStyles.Count > 1) layout.RowStyles.RemoveAt(layout.RowStyles.Count - 1);
                    layout.ColumnStyles[1].Width = detailsWidth; main.Margin = new Padding(0, 0, 10, 0);
                }
                layout.ResumeLayout(true);
            };
            return layout;
        }

        static TableLayoutPanel OpsCompactFields()
        {
            var fields = Ui.Fields(); fields.Padding = new Padding(0, 4, 0, 4); fields.ColumnStyles[0].Width = 88; fields.Margin = Padding.Empty;
            fields.ControlAdded += delegate(object sender, ControlEventArgs e) { if (!(e.Control is Label)) e.Control.MinimumSize = new Size(100, 26); };
            return fields;
        }

        static Label OpsMetric(FlowLayoutPanel parent, string title)
        {
            var value = new Label { Text = "—", Dock = DockStyle.Top, AutoSize = true, Font = new Font(Ui.BodyFont.FontFamily, 18, FontStyle.Bold), Padding = new Padding(0, 4, 0, 0) }; Ui.Role(value, "brand");
            Font valueFont = value.Font; value.Disposed += delegate { valueFont.Dispose(); };
            var card = new Panel { Width = 165, Height = 82, Padding = new Padding(12, 8, 12, 8), Margin = new Padding(0, 0, 8, 8) }; Ui.Role(card, "surface");
            card.Controls.Add(value); var label = OpsNote(title); label.Dock = DockStyle.Top; card.Controls.Add(label); parent.Controls.Add(card); return value;
        }
    }
}
