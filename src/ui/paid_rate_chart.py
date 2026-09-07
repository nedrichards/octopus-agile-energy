"""A separate, keyboard-accessible rolling energy-price history chart."""
from datetime import date

import cairo
from gi.repository import Adw, Gdk, Gtk, Pango, PangoCairo

from ..usage_insights import paid_rate_period_options, select_paid_rate_period


class PaidRateChart(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("card")
        self.history = []
        self.points = []
        self.selected = 0
        self.period_options = [(None, "All available")]
        self._changing_periods = False
        self.period = Gtk.DropDown.new_from_strings(["All available"])
        self.period.set_valign(Gtk.Align.START)
        self.period.set_tooltip_text("Rolling price history period")
        self.period.connect("notify::selected", self._update)
        header = Adw.WrapBox(child_spacing=12, line_spacing=8)
        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.value = Gtk.Label(label="—", xalign=0)
        self.value.add_css_class("title-1")
        summary.append(self.value)
        self.detail = Gtk.Label(xalign=0, wrap=True)
        self.detail.add_css_class("dim-label")
        summary.append(self.detail)
        header.append(summary)
        header.append(self.period)
        self.history_span = Gtk.Label(xalign=0, wrap=True)
        self.history_span.add_css_class("caption")
        self.history_span.add_css_class("dim-label")
        header.append(self.history_span)
        self.append(header)
        self.area = Gtk.DrawingArea()
        self.area.set_content_height(200)
        self.area.set_hexpand(True)
        self.area.set_focusable(True)
        self.area.set_tooltip_text("Drag sideways to inspect dates. Left/Right moves by day; Home/End jumps to the edges.")
        self.area.set_draw_func(self._draw)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.area.add_controller(keys)
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.area.add_controller(click)
        self._drag_start_x = None
        self._scrubbing = False
        drag = Gtk.GestureDrag.new()
        drag.set_button(Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        drag.connect("cancel", self._drag_cancel)
        self.area.add_controller(drag)
        drag.group(click)
        self.append(self.area)
        self.coverage_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        icon.set_valign(Gtk.Align.START)
        self.coverage_box.append(icon)
        self.coverage = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.coverage.add_css_class("caption")
        self.coverage_box.append(self.coverage)
        self.coverage_box.add_css_class("dim-label")
        self.append(self.coverage_box)
        style = Adw.StyleManager.get_default()
        for prop in ("dark", "high-contrast", "accent-color"):
            style.connect(f"notify::{prop}", lambda *_: self.area.queue_draw())
        self.connect("notify::root", lambda *_: self.area.queue_draw())

    def set_history(self, history):
        index = self.period.get_selected()
        previous = self.period_options[index][0] if index < len(self.period_options) else None
        self.history = history
        self.period_options, span = paid_rate_period_options(history)
        self._changing_periods = True
        self.period.set_model(Gtk.StringList.new([label for _months, label in self.period_options]))
        selected = next((i for i, (months, _) in enumerate(self.period_options) if months == previous),
                        len(self.period_options) - 1)
        self.period.set_selected(selected)
        self._changing_periods = False
        self.period.set_visible(len(self.period_options) > 1)
        self.history_span.set_text(span)
        self.history_span.set_visible(bool(span) and len(self.period_options) == 1)
        self._update()

    def _update(self, *_args):
        if self._changing_periods:
            return
        index = self.period.get_selected()
        if index >= len(self.period_options):
            return
        available, _ = select_paid_rate_period(self.history, None)
        months = self.period_options[index][0]
        self.points, coverage = select_paid_rate_period(available or self.history, months)
        self.coverage.set_text(coverage)
        self.coverage_box.set_visible(bool(coverage))
        self.area.set_visible(len(self.points) > 1)
        self.selected = max(0, len(self.points) - 1)
        self._describe()

    def _describe(self):
        if self.points:
            day, rate = self.points[self.selected]
            value = f"{rate:.1f}p/kWh" if rate is not None else "—"
            text = f"30 days to {date.fromisoformat(day):%d %b %Y}"
            if rate is None:
                text += " · Incomplete coverage"
        else:
            value = "—"
            text = "Not enough matched history"
        self.value.set_text(value)
        self.detail.set_text(text)
        self.area.update_property([Gtk.AccessibleProperty.LABEL], [f"{value}. {text}"])
        self.area.queue_draw()

    def _key(self, _controller, key, _code, _state):
        if not self.points or key not in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Home, Gdk.KEY_End):
            return False
        if key == Gdk.KEY_Home:
            self.selected = 0
        elif key == Gdk.KEY_End:
            self.selected = len(self.points) - 1
        else:
            self.selected = max(0, min(len(self.points) - 1, self.selected + (1 if key == Gdk.KEY_Right else -1)))
        self._describe()
        return True

    def _click(self, _gesture, _count, x, _y):
        self._select_at_x(x)

    def _select_at_x(self, x):
        if self.points:
            fraction = (x - 52) / max(1, self.area.get_width() - 68)
            selected = max(0, min(len(self.points) - 1, round(fraction * (len(self.points) - 1))))
            self.area.grab_focus()
            if selected != self.selected:
                self.selected = selected
                self._describe()

    def _drag_begin(self, _gesture, x, _y):
        self._drag_start_x = x
        self._scrubbing = False

    def _drag_update(self, gesture, offset_x, offset_y):
        if self._drag_start_x is None or not self.points:
            return
        if not self._scrubbing:
            if max(abs(offset_x), abs(offset_y)) < 8:
                return
            if abs(offset_y) >= abs(offset_x):
                gesture.set_state(Gtk.EventSequenceState.DENIED)
                self._drag_cancel(gesture, None)
                return
            self._scrubbing = True
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._select_at_x(self._drag_start_x + offset_x)

    def _drag_end(self, gesture, offset_x, _offset_y):
        if self._scrubbing and self._drag_start_x is not None:
            self._select_at_x(self._drag_start_x + offset_x)
        self._drag_cancel(gesture, None)

    def _drag_cancel(self, _gesture, _sequence):
        self._drag_start_x = None
        self._scrubbing = False

    def _draw(self, area, cr, width, height):
        color = area.get_color()
        fg = (color.red, color.green, color.blue)
        found, accent = area.get_style_context().lookup_color("accent_color")
        rgb = (accent.red, accent.green, accent.blue) if found else fg
        values = [value for _day, value in self.points if value is not None]
        if not values:
            return
        padding = max(1, (max(values) - min(values)) * 0.15)
        low, high = min(values) - padding, max(values) + padding
        left, top, plot_width, plot_height = 52, 18, max(1, width - 68), height - 48
        def label(text, x, y, align=0):
            layout = area.create_pango_layout(text)
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_scale_new(0.85))
            layout.set_attributes(attrs)
            text_width, _ = layout.get_pixel_size()
            cr.set_source_rgba(*fg, 0.65)
            cr.move_to(x - text_width * align, y)
            PangoCairo.show_layout(cr, layout)

        for value in (low, (low + high) / 2, high):
            y = top + (high - value) / (high - low) * plot_height
            cr.set_source_rgba(*fg, 0.1)
            cr.set_line_width(1)
            cr.move_to(left, y)
            cr.line_to(left + plot_width, y)
            cr.stroke()
            label(f"{value:.1f}p", left - 8, y - 8, 1)
        for index, align in ((0, 0), (len(self.points) - 1, 1)):
            label(f"{date.fromisoformat(self.points[index][0]):%d %b %Y}",
                  left + plot_width * align, height - 20, align)
        segments, segment = [], []
        for index, (_day, value) in enumerate(self.points):
            if value is None:
                if segment:
                    segments.append(segment)
                    segment = []
                continue
            x = left + index / max(1, len(self.points) - 1) * plot_width
            y = top + (high - value) / (high - low) * plot_height
            segment.append((x, y))
        if segment:
            segments.append(segment)
        for segment in segments:
            cr.move_to(segment[0][0], top + plot_height)
            for x, y in segment:
                cr.line_to(x, y)
            cr.line_to(segment[-1][0], top + plot_height)
            cr.close_path()
            gradient = cairo.LinearGradient(0, top, 0, top + plot_height)
            gradient.add_color_stop_rgba(0, *rgb, 0.18)
            gradient.add_color_stop_rgba(1, *rgb, 0.015)
            cr.set_source(gradient)
            cr.fill()
            cr.set_source_rgb(*rgb)
            cr.set_line_width(2.5)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.move_to(*segment[0])
            for point in segment[1:]:
                cr.line_to(*point)
            cr.stroke()
            if len(segment) == 1:
                cr.arc(*segment[0], 3, 0, 6.2832)
                cr.fill()
        x = left + self.selected / max(1, len(self.points) - 1) * plot_width
        cr.set_source_rgba(*fg, 0.3)
        cr.set_line_width(1)
        cr.move_to(x, top)
        cr.line_to(x, top + plot_height)
        cr.stroke()
        selected_value = self.points[self.selected][1]
        if selected_value is not None:
            y = top + (high - selected_value) / (high - low) * plot_height
            cr.set_source_rgb(*rgb)
            cr.arc(x, y, 4.5, 0, 6.2832)
            cr.fill()
