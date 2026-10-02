// Copyright (c) 2026 EeryFrank - https://github.com/EeryFrank
using System;
using System.Drawing;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using QiZhang.Shared;

namespace QiZhang.NativePanel {
    // Keep the native scrollbar, its full layout reservation and all input/accessibility behavior.
    // SetWindowTheme is documented at https://learn.microsoft.com/windows/win32/api/uxtheme/nf-uxtheme-setwindowtheme
    // DarkMode_Explorer is an OS visual-style association, verified on the supported Windows host;
    // it is not an accent-color API. Unsupported systems retain their normal native appearance.
    internal static class ScrollBarTheme {
        [DllImport("uxtheme.dll", CharSet = CharSet.Unicode)]
        private static extern int SetWindowTheme(IntPtr window, string application, string classes);
        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetComboBoxInfo(IntPtr window, ref ComboInfo info);
        [StructLayout(LayoutKind.Sequential)] private struct NativeRect {internal int Left, Top, Right, Bottom;}
        [StructLayout(LayoutKind.Sequential)] private struct ComboInfo {
            internal int Size;
            internal NativeRect Item, Button;
            internal int ButtonState;
            internal IntPtr Combo, Edit, List;
        }

        private static readonly ConditionalWeakTable<Control, Binding> Bindings = new ConditionalWeakTable<Control, Binding>();
        internal static void Apply(Control control) {
            if (control == null || control.IsDisposed || !Supported(control)) return;
            Bindings.GetValue(control, delegate(Control value) {return new Binding(value);}).Refresh();
            // Ui.ApplyTheme deliberately does not restyle grid child controls. Their managed native
            // ScrollBar HWNDs still need the same association as the grid's nonclient area.
            if (control is DataGridView) foreach (Control child in control.Controls) if (child is ScrollBar) Apply(child);
        }
        private static bool Supported(Control control) {
            return (control is ScrollableControl && !(control is Form)) || control is ScrollBar || control is DataGridView ||
                control is TextBoxBase || control is ListBox || control is ListView || control is TreeView || control is ComboBox;
        }
        private static void Associate(IntPtr handle, bool dark) {
            if (handle == IntPtr.Zero) return;
            try {SetWindowTheme(handle, dark ? "DarkMode_Explorer" : "Explorer", null);}
            catch (DllNotFoundException) { }
            catch (EntryPointNotFoundException) { }
        }

        private sealed class Binding {
            private readonly Control owner;
            private IntPtr appliedHandle, appliedList;
            private bool appliedDark, applying;
            internal Binding(Control control) {
                owner = control;
                owner.HandleCreated += HandleCreated;
                owner.HandleDestroyed += HandleDestroyed;
                owner.Disposed += Disposed;
                if (owner is DataGridView) {owner.ControlAdded += ChildAdded; owner.Paint += PaintGridCorner;}
                ComboBox combo = owner as ComboBox;
                if (combo != null) combo.DropDown += DropDown;
            }
            private void HandleCreated(object sender, EventArgs args) {Refresh();}
            private void HandleDestroyed(object sender, EventArgs args) {appliedHandle = appliedList = IntPtr.Zero;}
            private void ChildAdded(object sender, ControlEventArgs args) {if (args.Control is ScrollBar) Apply(args.Control);}
            private void PaintGridCorner(object sender, PaintEventArgs args) {
                // DataGridView paints its scrollbar intersection with SystemColors.Control even
                // after both native bars are dark. Repaint only that empty, noninteractive corner.
                ScrollBar vertical = null, horizontal = null;
                foreach (Control child in owner.Controls) {
                    if (child.Visible && child is VScrollBar) vertical = (ScrollBar)child;
                    if (child.Visible && child is HScrollBar) horizontal = (ScrollBar)child;
                }
                if (vertical == null || horizontal == null) return;
                Rectangle corner = new Rectangle(vertical.Left, horizontal.Top, vertical.Width, horizontal.Height);
                corner.Intersect(owner.ClientRectangle);
                if (corner.Width > 0 && corner.Height > 0 && !corner.IntersectsWith(vertical.Bounds) && !corner.IntersectsWith(horizontal.Bounds))
                    using (SolidBrush fill = new SolidBrush(AppTheme.IsDark ? Ui.Surface : SystemColors.Control)) args.Graphics.FillRectangle(fill, corner);
            }
            private void DropDown(object sender, EventArgs args) {RefreshList(AppTheme.IsDark);}
            private void Disposed(object sender, EventArgs args) {
                owner.HandleCreated -= HandleCreated; owner.HandleDestroyed -= HandleDestroyed; owner.Disposed -= Disposed;
                if (owner is DataGridView) {owner.ControlAdded -= ChildAdded; owner.Paint -= PaintGridCorner;}
                ComboBox combo = owner as ComboBox; if (combo != null) combo.DropDown -= DropDown;
                appliedHandle = appliedList = IntPtr.Zero;
            }
            internal void Refresh() {
                if (applying || owner.IsDisposed || !owner.IsHandleCreated) return;
                bool dark = AppTheme.IsDark;
                if (owner.Handle == appliedHandle && dark == appliedDark) {RefreshList(dark); return;}
                applying = true;
                try {
                    appliedHandle = owner.Handle; appliedDark = dark; appliedList = IntPtr.Zero;
                    Associate(appliedHandle, dark); RefreshList(dark);
                    owner.Invalidate();
                } finally {applying = false;}
            }
            private void RefreshList(bool dark) {
                if (!(owner is ComboBox) || owner.IsDisposed || !owner.IsHandleCreated) return;
                ComboInfo info = new ComboInfo {Size = Marshal.SizeOf(typeof(ComboInfo))};
                if (GetComboBoxInfo(owner.Handle, ref info) && info.List != IntPtr.Zero && (info.List != appliedList || dark != appliedDark)) {
                    appliedList = info.List; Associate(info.List, dark);
                }
            }
        }
    }
}
