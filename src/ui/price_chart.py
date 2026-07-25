import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
import math
import time

import cairo
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from ..price_bands import (
    PRICE_BAND_HIGH,
    PRICE_BAND_LOW,
    PRICE_BAND_MEDIUM,
    PRICE_BAND_NEGATIVE,
    get_price_band,
)
from ..price_chart_presentation import (
    find_price_index_by_start,
    get_day_transition_markers,
    get_price_axis_bounds,
)
from ..price_formatting import format_gbp, format_unit_price_gbp
from .adaptive_layout import (
    get_chart_content_width,
    get_chart_height,
    get_time_label_interval,
    is_compact_width,
)


class PriceChartWidget(Gtk.DrawingArea):
    """
    A custom Gtk.DrawingArea widget for displaying half-hour electricity rates as a line chart.
    This version is optimized to work with pre-processed data for better performance.
    """
    def __init__(self):
        super().__init__()
        self.prices = []
        self.current_price_index = -1
        self.hovered_index = -1
        self.selected_index = -1
        self.compact = False
        # Margins for labels and chart area
        self.margin_left = 45
        self.margin_right = 15
        self.margin_top = 20
        self.margin_bottom = 30
        self.highlight_start_time = None
        self.highlight_end_time = None
        self.highlight_label = None
        self.slot_count = 0
        self.slot_energies = []
        self.animation_source_id = None
        self.hover_started_at = None

        self.set_size_request(-1, get_chart_height(0))
        self.set_draw_func(self.on_draw)
        self.set_accessible_role(Gtk.AccessibleRole.SLIDER)
        self.set_focusable(True)
        self.set_focus_on_click(True)
        self.connect("destroy", self._on_destroy)

        motion_controller = Gtk.EventControllerMotion.new()
        motion_controller.connect('motion', self.on_motion)
        motion_controller.connect('leave', self.on_leave)
        self.add_controller(motion_controller)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

        click_controller = Gtk.GestureClick.new()
        click_controller.connect('pressed', self.on_click)
        self.add_controller(click_controller)

        self._update_accessible_summary()

    def set_compact_mode(self, compact, width, slot_count=0):
        self.compact = compact
        self.slot_count = slot_count
        self.margin_left = 38 if compact else 45
        self.margin_right = 10 if compact else 15
        self.margin_top = 16 if compact else 20
        self.margin_bottom = 26 if compact else 30
        content_width = get_chart_content_width(width, slot_count)
        self.set_size_request(content_width, self._get_scaled_chart_height(width))
        self.queue_draw()

    def set_prices(self, prices, current_index):
        """
        Updates the price data and current price index for the chart.
        Queues a redraw to reflect the new data.
        """
        previous_times = [price['valid_from'] for price in self.prices]
        selected_time = (
            self.prices[self.selected_index]['valid_from']
            if 0 <= self.selected_index < len(self.prices)
            else None
        )
        self.prices = prices
        self.current_price_index = current_index
        current_times = [price['valid_from'] for price in self.prices]

        if current_times != previous_times:
            self.selected_index = find_price_index_by_start(self.prices, selected_time)
            self.hovered_index = -1
            self.hover_started_at = None
            self.slot_energies = [0.0] * len(self.prices)
        else:
            self._ensure_slot_energies()
            if self.selected_index >= len(self.prices):
                self.selected_index = -1

        self._update_accessible_summary()
        self.queue_draw()

    def set_highlight_range(self, start_time, end_time, label=None):
        """
        Sets the time range to highlight on the chart.
        """
        self.highlight_start_time = start_time
        self.highlight_end_time = end_time
        self.highlight_label = label
        self._update_accessible_summary()
        self.queue_draw()

    def get_bar_start_x(self, index):
        if not self.prices or index < 0 or index >= len(self.prices):
            return None

        width = self.get_width()
        if width <= 0:
            width = self.get_allocated_width()
        if width <= 0:
            return None

        chart_width = width - self.margin_left - self.margin_right
        if chart_width <= 0:
            return None

        return self.margin_left + (index * chart_width) / len(self.prices)

    def _on_destroy(self, *_args):
        if self.animation_source_id:
            GLib.source_remove(self.animation_source_id)
            self.animation_source_id = None

    def _animations_enabled(self):
        settings = Gtk.Settings.get_default()
        return not settings or settings.get_property("gtk-enable-animations")

    def _select_index(self, index):
        if not self.prices:
            return

        index = max(0, min(index, len(self.prices) - 1))
        self.selected_index = index
        self._ensure_slot_energies()
        self.slot_energies[index] = max(self.slot_energies[index], 0.82)
        self._schedule_animation()
        self._update_accessible_summary()
        self.queue_draw()

        parent_window = self.get_ancestor(Gtk.Window)
        if parent_window and hasattr(parent_window, 'on_chart_click'):
            parent_window.on_chart_click(index)

    def _selection_base_index(self):
        if 0 <= self.selected_index < len(self.prices):
            return self.selected_index
        if 0 <= self.hovered_index < len(self.prices):
            return self.hovered_index
        if 0 <= self.current_price_index < len(self.prices):
            return self.current_price_index
        return 0

    def _update_accessible_summary(self):
        properties = [
            Gtk.AccessibleProperty.LABEL,
            Gtk.AccessibleProperty.DESCRIPTION,
            Gtk.AccessibleProperty.ORIENTATION,
        ]
        values = [
            "Future price chart",
            "No price data is loaded.",
            int(Gtk.Orientation.HORIZONTAL),
        ]

        if not self.prices:
            self.update_property(properties, values)
            return

        value_index = self._selection_base_index()
        properties.extend(
            [
                Gtk.AccessibleProperty.VALUE_MIN,
                Gtk.AccessibleProperty.VALUE_MAX,
                Gtk.AccessibleProperty.VALUE_NOW,
                Gtk.AccessibleProperty.VALUE_TEXT,
            ]
        )
        values.extend(
            [
                1.0,
                float(len(self.prices)),
                float(value_index + 1),
                self._build_accessible_slot_summary(value_index),
            ]
        )

        if 0 <= self.selected_index < len(self.prices):
            description = self._build_accessible_slot_summary(self.selected_index)
        else:
            description = (
                "Upcoming electricity prices. Use the left and right arrow keys "
                "to review individual half-hour slots."
            )
            if self.highlight_label:
                description += f" Highlighted range: {self.highlight_label}."

        values[1] = description
        self.update_property(properties, values)

    def _build_accessible_slot_summary(self, index):
        min_index, max_index = self._get_extreme_indices()
        price_data = self.prices[index]
        valid_from = price_data['valid_from'].astimezone().strftime('%H:%M')
        valid_to = price_data['valid_to'].astimezone().strftime('%H:%M')
        price = price_data['price_gbp']
        reason = self._describe_slot(index, price, min_index, max_index)
        return (
            f"{valid_from} to {valid_to}, {format_unit_price_gbp(price)}. "
            f"{reason}. Slot {index + 1} of {len(self.prices)}."
        )

    def _get_extreme_indices(self):
        if not self.prices:
            return -1, -1

        prices_gbp = [p['price_gbp'] for p in self.prices]
        return prices_gbp.index(min(prices_gbp)), prices_gbp.index(max(prices_gbp))

    def _create_text_layout(self, text, scale=1.0, weight=None, max_width=None):
        layout = self.create_pango_layout(text)
        attributes = Pango.AttrList()
        if scale != 1.0:
            attributes.insert(Pango.attr_scale_new(scale))
        if weight is not None:
            attributes.insert(Pango.attr_weight_new(weight))
        layout.set_attributes(attributes)
        if max_width is not None:
            layout.set_width(int(max_width * Pango.SCALE))
            layout.set_ellipsize(Pango.EllipsizeMode.END)
        return layout

    def _layout_size(self, layout):
        _ink_rect, logical_rect = layout.get_pixel_extents()
        return logical_rect.width, logical_rect.height

    def _draw_layout(self, cr, layout, x, y):
        cr.move_to(round(x), round(y))
        PangoCairo.show_layout(cr, layout)

    def _get_scaled_chart_height(self, width):
        base_height = get_chart_height(width)
        sample_layout = self._create_text_layout("00:00", scale=0.9)
        _sample_width, sample_height = self._layout_size(sample_layout)
        return base_height + max(0, sample_height - 14) * 3

    def _ensure_slot_energies(self):
        if len(self.slot_energies) != len(self.prices):
            self.slot_energies = [0.0] * len(self.prices)

    def _schedule_animation(self):
        if not self._animations_enabled():
            self.queue_draw()
            return

        if self.animation_source_id:
            return

        self.animation_source_id = GLib.timeout_add(16, self._animation_tick)

    def _animation_tick(self):
        self._ensure_slot_energies()
        keep_animating = False
        target_energies = []

        for index, energy in enumerate(self.slot_energies):
            if index == self.hovered_index:
                target = 1.0
            elif index == self.selected_index:
                target = 0.65
            else:
                target = 0.0

            if target > energy:
                energy += (target - energy) * 0.28
            else:
                energy *= 0.82

            if abs(target - energy) > 0.01 or (target == 0.0 and energy > 0.01):
                keep_animating = True

            self.slot_energies[index] = energy
            target_energies.append(target)

        self.queue_draw()

        if not keep_animating:
            self.slot_energies = target_energies
            self.animation_source_id = None
            return False

        return True

    def _set_hovered_index(self, new_hovered_index):
        if new_hovered_index == self.hovered_index:
            return

        now = time.monotonic()
        previous_index = self.hovered_index
        dwell_seconds = (
            now - self.hover_started_at
            if self.hover_started_at is not None
            else 0.18
        )
        self.hover_started_at = now
        self.hovered_index = new_hovered_index
        self._ensure_slot_energies()

        if 0 <= new_hovered_index < len(self.slot_energies):
            if previous_index >= 0:
                slot_distance = max(1, abs(new_hovered_index - previous_index))
            else:
                slot_distance = 1
            slots_per_second = slot_distance / max(dwell_seconds, 0.016)
            sweep_strength = min(1.0, max(0.42, slots_per_second / 10.0))
            self.slot_energies[new_hovered_index] = max(
                self.slot_energies[new_hovered_index],
                sweep_strength,
            )

            direction = 1 if previous_index < new_hovered_index else -1
            neighbor_index = new_hovered_index - direction
            if 0 <= neighbor_index < len(self.slot_energies):
                self.slot_energies[neighbor_index] = max(
                    self.slot_energies[neighbor_index],
                    sweep_strength * 0.38,
                )

        self._schedule_animation()
        self.queue_draw()

    def on_key_pressed(self, _controller, keyval, _keycode, _state):
        if not self.prices:
            return False

        base_index = self._selection_base_index()
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left, Gdk.KEY_h):
            self._select_index(base_index - 1)
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right, Gdk.KEY_l):
            self._select_index(base_index + 1)
        elif keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            self._select_index(0)
        elif keyval in (Gdk.KEY_End, Gdk.KEY_KP_End):
            self._select_index(len(self.prices) - 1)
        elif keyval in (Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up):
            self._select_index(base_index - 4)
        elif keyval in (Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Down):
            self._select_index(base_index + 4)
        else:
            return False

        return True

    def on_motion(self, controller, x, y):
        """
        Handles mouse motion events to detect hovering over price slots.
        """
        if not self.prices:
            return

        width = self.get_width()
        chart_width = width - self.margin_left - self.margin_right
        if not (self.margin_left <= x <= width - self.margin_right):
            if self.hovered_index != -1:
                self.on_leave(controller)
            return

        chart_x = x - self.margin_left
        bar_width = chart_width / len(self.prices)
        new_hovered_index = int(chart_x / bar_width)

        if 0 <= new_hovered_index < len(self.prices):
            self._set_hovered_index(new_hovered_index)

    def on_leave(self, controller):
        """
        Handles mouse leaving the widget area, clearing any hover highlights.
        """
        if self.hovered_index != -1:
            self.hovered_index = -1
            self.hover_started_at = None
            self._schedule_animation()
            self.queue_draw()

    def on_click(self, gesture, n_press, x, y):
        """
        Handles click events on the chart.
        """
        if not self.prices:
            return

        width = self.get_width()
        chart_width = width - self.margin_left - self.margin_right
        if not (self.margin_left <= x <= width - self.margin_right):
            return

        chart_x = x - self.margin_left
        bar_width = chart_width / len(self.prices)
        clicked_index = int(chart_x / bar_width)

        if 0 <= clicked_index < len(self.prices):
            self._select_index(clicked_index)

    def on_draw(self, area, cr, width, height):
        """
        The main drawing function for the chart. Optimized for pre-processed data.
        """
        if not self.prices:
            return

        chart_width = width - self.margin_left - self.margin_right
        chart_height = height - self.margin_top - self.margin_bottom

        prices_gbp = [p['price_gbp'] for p in self.prices]
        min_price = min(prices_gbp)
        max_price = max(prices_gbp)
        display_min_price, display_max_price = get_price_axis_bounds(prices_gbp)
        price_range = display_max_price - display_min_price
        chart_zero_y = self.margin_top + chart_height * (display_max_price / price_range)

        # Fetch style context once
        style_context = self.get_style_context()
        fg_color = style_context.get_color()

        # --- Draw Grid Lines and Price Labels ---
        # Aim for about 5 intervals
        ideal_step = price_range / 5
        if ideal_step > 0:
            magnitude = 10 ** math.floor(math.log10(ideal_step))
            normalized_step = ideal_step / magnitude
            if normalized_step < 1.6:
                step = 1 * magnitude
            elif normalized_step < 3.5:
                step = 2 * magnitude
            elif normalized_step < 7.5:
                step = 5 * magnitude
            else:
                step = 10 * magnitude
        else:
            step = 0.1

        # Calculate where to start drawing lines
        current_grid_price = math.ceil(display_min_price / step) * step

        while current_grid_price <= display_max_price + 0.0001:
            line_y = chart_zero_y - (current_grid_price / price_range) * chart_height
            is_zero_line = abs(current_grid_price) < max(0.0001, step / 1000)

            # Zero is the semantic boundary between paying and being paid.
            line_alpha = 0.2 if is_zero_line else 0.1
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, line_alpha)
            cr.set_line_width(1.25 if is_zero_line else 1.0)
            cr.move_to(self.margin_left, round(line_y) + 0.5)
            cr.line_to(self.margin_left + chart_width, round(line_y) + 0.5)
            cr.stroke()

            # Draw label (slightly clearer)
            label = format_gbp(current_grid_price)
            label_layout = self._create_text_layout(label, scale=0.9)
            label_width, label_height = self._layout_size(label_layout)
            label_alpha = 0.65 if is_zero_line else 0.5
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, label_alpha)
            # Center vertically on the line
            label_y = line_y - label_height / 2
            self._draw_layout(cr, label_layout, self.margin_left - label_width - 5, label_y)

            current_grid_price += step

        # --- Draw Chart ---
        highlight_x_start = None
        highlight_x_end = None
        highlighted_indices = []
        points = []
        slot_bounds = []
        min_index = prices_gbp.index(min_price)
        max_index = prices_gbp.index(max_price)

        for i, price_data in enumerate(self.prices):
            price = price_data['price_gbp']
            bar_x_start = self.margin_left + (i * chart_width) / len(self.prices)
            bar_x_end = self.margin_left + ((i + 1) * chart_width) / len(self.prices)
            bar_width = bar_x_end - bar_x_start
            point_x = bar_x_start + bar_width / 2
            point_y = chart_zero_y - (price / price_range) * chart_height
            points.append((point_x, point_y))
            slot_bounds.append((bar_x_start, bar_x_start + bar_width - 1))

            # Highlight the best slot
            if self.highlight_start_time and self.highlight_end_time:
                if self.highlight_start_time <= price_data['valid_from'] < self.highlight_end_time:
                    highlighted_indices.append(i)
                    highlight_x_start = (
                        bar_x_start
                        if highlight_x_start is None
                        else min(highlight_x_start, bar_x_start)
                    )
                    highlight_x_end = (
                        bar_x_start + bar_width - 1
                        if highlight_x_end is None
                        else max(highlight_x_end, bar_x_start + bar_width - 1)
                    )

        day_transitions = [
            (slot_bounds[index][0], label)
            for index, label in get_day_transition_markers(
                [price['valid_from'] for price in self.prices]
            )
        ]

        self._draw_highlight_range(
            cr,
            fg_color,
            highlight_x_start,
            highlight_x_end,
            chart_height,
        )

        for i, price_data in enumerate(self.prices):
            price = price_data['price_gbp']
            bar_x_start, bar_x_end = slot_bounds[i]
            bar_width = bar_x_end - bar_x_start + 1
            _point_x, point_y = points[i]
            base_color = self._get_price_color(style_context, price)
            if self._animations_enabled():
                energy = self.slot_energies[i] if i < len(self.slot_energies) else 0.0
            else:
                energy = 1.0 if i == self.hovered_index else 0.65 if i == self.selected_index else 0.0

            if i in (self.hovered_index, self.selected_index):
                self._draw_active_slot_wash(
                    cr,
                    fg_color,
                    energy,
                    bar_x_start + 0.5,
                    bar_x_start + max(1, bar_width - 1),
                    chart_height,
                )

            fill_alpha = 0.035 + (0.18 * energy)
            if i == self.current_price_index:
                fill_alpha = max(fill_alpha, 0.075)

            self._draw_slot_area_fill(
                cr,
                base_color,
                fill_alpha,
                points,
                i,
                bar_x_start + 0.5,
                bar_x_start + max(1, bar_width - 1),
                chart_zero_y,
            )

        if len(points) > 1:
            cr.save()
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)

            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.18)
            cr.set_line_width(4.6 if not self.compact else 4.0)
            cr.move_to(points[0][0], points[0][1])
            for point_x, point_y in points[1:]:
                cr.line_to(point_x, point_y)
            cr.stroke()

            cr.set_line_width(2.6 if not self.compact else 2.25)
            for i in range(len(points) - 1):
                price = self.prices[i]['price_gbp']
                base_color = self._get_price_color(style_context, price)
                cr.set_source_rgba(base_color[0], base_color[1], base_color[2], 0.92)
                cr.move_to(points[i][0], points[i][1])
                cr.line_to(points[i + 1][0], points[i + 1][1])
                cr.stroke()

            self._draw_highlight_line_ribbon(cr, points, highlighted_indices)
            cr.restore()

        for feature_index, feature_label in ((min_index, "Minimum"), (max_index, "Peak")):
            if feature_index >= len(points):
                continue

            if feature_index == self.current_price_index:
                continue

            if feature_label == "Peak" and min_index == max_index:
                continue

            self._draw_feature_blob(
                cr,
                style_context,
                points[feature_index][0],
                points[feature_index][1],
                self.prices[feature_index]['price_gbp'],
                feature_index in (self.hovered_index, self.selected_index),
            )

        if 0 <= self.current_price_index < len(points):
            current_x, current_y = points[self.current_price_index]
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.26)
            cr.set_line_width(1.0)
            cr.move_to(round(current_x) + 0.5, self.margin_top)
            cr.line_to(round(current_x) + 0.5, self.margin_top + chart_height)
            cr.stroke()
            self._draw_feature_blob(
                cr,
                style_context,
                current_x,
                current_y,
                self.prices[self.current_price_index]['price_gbp'],
                True,
                radius=4.4,
            )

        self._draw_highlight_label(cr, fg_color, highlight_x_start, highlight_x_end, width)

        # --- Draw Day Transition Indicator ---
        for day_transition_x, day_label in day_transitions:
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.2)
            cr.set_line_width(1.0)
            cr.set_dash([4.0, 4.0])
            cr.move_to(day_transition_x, self.margin_top)
            cr.line_to(day_transition_x, self.margin_top + chart_height + 5)
            cr.stroke()
            cr.set_dash([]) # Reset dash

            # Day label
            day_layout = self._create_text_layout(day_label, scale=0.9)
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.5)
            self._draw_layout(cr, day_layout, day_transition_x + 5, self.margin_top + 4)

        # --- Draw Time Labels ---
        cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.5)
        time_label_scale = 0.82 if is_compact_width(width) else 0.9
        label_interval = get_time_label_interval(width, len(self.prices))
        for i in range(0, len(self.prices), label_interval):
            if i < len(self.prices):
                time_str = self.prices[i]['valid_from'].astimezone().strftime('%H:%M')
                time_layout = self._create_text_layout(time_str, scale=time_label_scale)
                time_width, time_height = self._layout_size(time_layout)
                bar_x_center = self.margin_left + ((i + 0.5) * chart_width) / len(self.prices)
                text_x = round(bar_x_center - time_width / 2)
                text_y = height - time_height - 4
                self._draw_layout(cr, time_layout, text_x, text_y)

        # Keep the active detail surface above every chart decoration.
        active_index = self.hovered_index if self.hovered_index != -1 else self.selected_index
        if 0 <= active_index < len(points):
            self._draw_slot_flyout(
                cr,
                fg_color,
                active_index,
                points[active_index],
                min_index,
                max_index,
                chart_width,
                width,
            )

    def _draw_highlight_label(self, cr, fg_color, highlight_x_start, highlight_x_end, width):
        if not self.highlight_label or highlight_x_start is None or highlight_x_end is None:
            return

        cr.save()
        label_layout = self._create_text_layout(self.highlight_label, scale=0.9)
        text_width, text_height = self._layout_size(label_layout)
        padding_x = 6
        padding_y = 3
        label_width = text_width + padding_x * 2
        label_height = text_height + padding_y * 2
        highlight_center = highlight_x_start + (highlight_x_end - highlight_x_start) / 2
        label_x = max(
            self.margin_left,
            min(
                highlight_center - label_width / 2,
                width - self.margin_right - label_width,
            ),
        )
        label_y = self.margin_top + 6

        self._rounded_rectangle(cr, label_x, label_y, label_width, label_height, 7)
        cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.76)
        cr.fill()
        luminance = 0.2126 * fg_color.red + 0.7152 * fg_color.green + 0.0722 * fg_color.blue
        text_color = 0 if luminance > 0.5 else 1
        cr.set_source_rgba(text_color, text_color, text_color, 0.95)
        self._draw_layout(cr, label_layout, label_x + padding_x, label_y + padding_y)
        cr.restore()

    def _draw_highlight_range(self, cr, fg_color, highlight_x_start, highlight_x_end, chart_height):
        if highlight_x_start is None or highlight_x_end is None:
            return

        range_x = highlight_x_start
        range_width = max(1, highlight_x_end - highlight_x_start)
        range_y = self.margin_top + 2
        range_height = max(1, chart_height - 4)

        cr.save()
        self._rounded_rectangle(cr, range_x, range_y, range_width, range_height, 9)
        cr.set_source_rgba(0.92, 0.70, 0.14, 0.10)
        cr.fill_preserve()
        cr.set_source_rgba(0.92, 0.70, 0.14, 0.22)
        cr.set_line_width(1.0)
        cr.stroke()

        cr.set_source_rgba(0.92, 0.70, 0.14, 0.48)
        cr.set_line_width(1.2)
        for boundary_x in (highlight_x_start, highlight_x_end):
            cr.move_to(round(boundary_x) + 0.5, self.margin_top + 4)
            cr.line_to(round(boundary_x) + 0.5, self.margin_top + chart_height - 4)
            cr.stroke()

        cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.07)
        cr.move_to(highlight_x_start, self.margin_top + chart_height - 1.5)
        cr.line_to(highlight_x_end, self.margin_top + chart_height - 1.5)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.restore()

    def _draw_active_slot_wash(self, cr, fg_color, energy, left_x, right_x, chart_height):
        """Draw interaction state across the plot without changing price-area semantics."""
        if energy <= 0.001:
            return

        cr.save()
        cr.rectangle(
            left_x,
            self.margin_top + 2,
            max(1, right_x - left_x),
            max(1, chart_height - 4),
        )
        alpha = 0.025 + 0.045 * energy
        cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, alpha)
        cr.fill()
        cr.restore()

    def _draw_highlight_line_ribbon(self, cr, points, highlighted_indices):
        if not highlighted_indices:
            return

        highlighted = set(highlighted_indices)

        cr.save()
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        drew_segment = False
        cr.set_line_width(7.0 if not self.compact else 6.0)
        cr.set_source_rgba(0.92, 0.70, 0.14, 0.20)
        for index in range(len(points) - 1):
            if index in highlighted and index + 1 in highlighted:
                cr.move_to(points[index][0], points[index][1])
                cr.line_to(points[index + 1][0], points[index + 1][1])
                cr.stroke()
                drew_segment = True

        cr.set_line_width(3.4 if not self.compact else 3.0)
        cr.set_source_rgba(1.0, 0.84, 0.30, 0.70)
        for index in range(len(points) - 1):
            if index in highlighted and index + 1 in highlighted:
                cr.move_to(points[index][0], points[index][1])
                cr.line_to(points[index + 1][0], points[index + 1][1])
                cr.stroke()

        if not drew_segment:
            index = highlighted_indices[0]
            if 0 <= index < len(points):
                cr.arc(points[index][0], points[index][1], 8.0, 0, math.tau)
                cr.set_source_rgba(1.0, 0.84, 0.30, 0.24)
                cr.fill()

        cr.restore()

    def _draw_slot_area_fill(self, cr, base_color, alpha, points, index, left_x, right_x, zero_y):
        if alpha <= 0.001 or not points or not (0 <= index < len(points)):
            return

        left_y = self._interpolated_slot_edge_y(points, index, "left")
        center_x, center_y = points[index]
        right_y = self._interpolated_slot_edge_y(points, index, "right")
        if max(abs(zero_y - left_y), abs(zero_y - center_y), abs(zero_y - right_y)) <= 0.5:
            return

        cr.save()
        cr.move_to(left_x, left_y)
        cr.line_to(center_x, center_y)
        cr.line_to(right_x, right_y)
        cr.line_to(right_x, zero_y)
        cr.line_to(left_x, zero_y)
        cr.close_path()
        cr.clip()

        line_mid_y = (left_y + center_y + right_y) / 3
        gradient_top = min(left_y, center_y, right_y, zero_y)
        gradient_bottom = max(left_y, center_y, right_y, zero_y)
        if abs(gradient_bottom - gradient_top) < 1:
            gradient_bottom = gradient_top + 1

        gradient = cairo.LinearGradient(0, gradient_top, 0, gradient_bottom)
        if line_mid_y < zero_y:
            gradient.add_color_stop_rgba(0, base_color[0], base_color[1], base_color[2], alpha)
            gradient.add_color_stop_rgba(1, base_color[0], base_color[1], base_color[2], alpha * 0.42)
        else:
            gradient.add_color_stop_rgba(0, base_color[0], base_color[1], base_color[2], alpha * 0.42)
            gradient.add_color_stop_rgba(1, base_color[0], base_color[1], base_color[2], alpha)

        cr.set_source(gradient)
        cr.rectangle(left_x, gradient_top, max(1, right_x - left_x), gradient_bottom - gradient_top)
        cr.fill()
        cr.restore()

    def _interpolated_slot_edge_y(self, points, index, edge):
        _x, current_y = points[index]
        if edge == "left":
            if index == 0:
                return current_y
            _previous_x, previous_y = points[index - 1]
            return (previous_y + current_y) / 2

        if index >= len(points) - 1:
            return current_y
        _next_x, next_y = points[index + 1]
        return (current_y + next_y) / 2

    def _get_price_color(self, style_context, price):
        price_band = get_price_band(price)
        if price_band == PRICE_BAND_NEGATIVE:
            success, color = style_context.lookup_color("blue_4")
            return (color.red, color.green, color.blue) if success else (0.2, 0.4, 0.8)
        if price_band == PRICE_BAND_LOW:
            success, color = style_context.lookup_color("green_4")
            return (color.red, color.green, color.blue) if success else (0.2, 0.8, 0.2)
        if price_band == PRICE_BAND_MEDIUM:
            success, color = style_context.lookup_color("orange_3")
            return (color.red, color.green, color.blue) if success else (1.0, 0.6, 0.0)

        assert price_band == PRICE_BAND_HIGH
        success, color = style_context.lookup_color("red_4")
        return (color.red, color.green, color.blue) if success else (0.8, 0.2, 0.2)

    def _draw_feature_blob(self, cr, style_context, x, y, price, active=False, radius=5.8):
        base_color = self._get_price_color(style_context, price)
        blob_radius = radius + (1.4 if active else 0.0)

        cr.save()
        cr.arc(x, y, blob_radius + 5.0, 0, math.tau)
        cr.set_source_rgba(base_color[0], base_color[1], base_color[2], 0.14 if active else 0.09)
        cr.fill()

        cr.arc(x, y, blob_radius, 0, math.tau)
        cr.set_source_rgba(base_color[0], base_color[1], base_color[2], 0.94)
        cr.fill_preserve()

        fg_color = self.get_style_context().get_color()
        cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.35)
        cr.set_line_width(1.4)
        cr.stroke()
        cr.restore()

    def _draw_slot_flyout(
        self,
        cr,
        fg_color,
        index,
        point,
        min_index,
        max_index,
        chart_width,
        width,
    ):
        price_data = self.prices[index]
        valid_from = price_data['valid_from'].astimezone().strftime('%H:%M')
        valid_to = price_data['valid_to'].astimezone().strftime('%H:%M')
        price = price_data['price_gbp']
        reason = self._describe_slot(index, price, min_index, max_index)
        lines = [
            f"{valid_from} - {valid_to}",
            format_unit_price_gbp(price),
            reason,
        ]

        cr.save()
        line_specs = (
            (lines[0], 1.0, Pango.Weight.BOLD),
            (lines[1], 1.0, None),
            (lines[2], 0.9, None),
        )
        line_layouts = [
            self._create_text_layout(line, scale=scale, weight=weight)
            for line, scale, weight in line_specs
        ]
        line_metrics = [self._layout_size(layout) for layout in line_layouts]
        padding_x = 9
        padding_y = 7
        line_gap = 3
        flyout_width = min(
            max(line_width for line_width, _line_height in line_metrics) + padding_x * 2,
            max(150, min(210, chart_width - 12)),
        )
        max_line_width = max(1, flyout_width - padding_x * 2)
        line_layouts = [
            self._create_text_layout(line, scale=scale, weight=weight, max_width=max_line_width)
            for line, scale, weight in line_specs
        ]
        line_metrics = [self._layout_size(layout) for layout in line_layouts]
        text_height = sum(line_height for _line_width, line_height in line_metrics) + line_gap * (len(lines) - 1)
        flyout_height = text_height + padding_y * 2 + 2
        point_x, point_y = point

        if point_x + flyout_width + 18 <= width - self.margin_right:
            flyout_x = point_x + 14
        else:
            flyout_x = point_x - flyout_width - 14
        flyout_x = max(self.margin_left, min(flyout_x, width - self.margin_right - flyout_width))

        preferred_y = point_y - flyout_height - 12
        if preferred_y < self.margin_top + 4:
            flyout_y = point_y + 12
        else:
            flyout_y = preferred_y
        flyout_y = max(self.margin_top + 4, flyout_y)

        cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.32)
        cr.set_line_width(1.0)
        cr.move_to(point_x, point_y)
        anchor_x = flyout_x if point_x < flyout_x else flyout_x + flyout_width
        anchor_y = min(max(point_y, flyout_y + 10), flyout_y + flyout_height - 10)
        cr.line_to(anchor_x, anchor_y)
        cr.stroke()

        self._rounded_rectangle(cr, flyout_x, flyout_y, flyout_width, flyout_height, 7)
        cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.82)
        cr.fill()

        luminance = 0.2126 * fg_color.red + 0.7152 * fg_color.green + 0.0722 * fg_color.blue
        text_color = 0 if luminance > 0.5 else 1
        muted_alpha = 0.72
        text_y = flyout_y + padding_y
        for line_index, (layout, (_line_width, line_height)) in enumerate(zip(line_layouts, line_metrics)):
            alpha = 0.96 if line_index != 2 else muted_alpha
            cr.set_source_rgba(text_color, text_color, text_color, alpha)
            self._draw_layout(cr, layout, flyout_x + padding_x, text_y)
            text_y += line_height + line_gap

        cr.restore()

    def _describe_slot(self, index, price, min_index, max_index):
        in_highlight = False
        if self.highlight_start_time and self.highlight_end_time:
            valid_from = self.prices[index]['valid_from']
            in_highlight = self.highlight_start_time <= valid_from < self.highlight_end_time

        if index == self.current_price_index:
            if in_highlight:
                return self.highlight_label or "Current cheapest slot"
            return "Current slot"
        if min_index == max_index and index == min_index:
            return "Flat visible price"
        if index == min_index:
            if in_highlight:
                return "Minimum in cheapest window"
            return "Minimum visible price"
        if index == max_index:
            if in_highlight:
                return "Peak in cheapest window"
            return "Peak visible price"
        if in_highlight:
            return self.highlight_label or "Cheapest window"
        return f"{get_price_band(price).title()} price"

    def _rounded_rectangle(self, cr, x, y, width, height, radius):
        radius = min(radius, width / 2, height / 2)
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, math.pi * 1.5)
        cr.close_path()
