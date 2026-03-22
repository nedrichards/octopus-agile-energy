import gi

gi.require_version('Gtk', '4.0')
import math

import cairo
from gi.repository import Gtk

from .adaptive_layout import (
    get_chart_content_width,
    get_chart_height,
    get_time_label_interval,
    is_compact_width,
)


class PriceChartWidget(Gtk.DrawingArea):
    """
    A custom Gtk.DrawingArea widget for displaying Octopus Agile electricity prices as a bar chart.
    This version is optimized to work with pre-processed data for better performance.
    """
    def __init__(self):
        super().__init__()
        self.prices = []
        self.current_price_index = -1
        self.hovered_index = -1
        self.compact = False
        # Margins for labels and chart area
        self.margin_left = 45
        self.margin_right = 15
        self.margin_top = 20
        self.margin_bottom = 30
        self.highlight_start_time = None
        self.highlight_end_time = None
        self.slot_count = 0

        self.set_size_request(-1, get_chart_height(0))
        self.set_draw_func(self.on_draw)

        motion_controller = Gtk.EventControllerMotion.new()
        motion_controller.connect('motion', self.on_motion)
        motion_controller.connect('leave', self.on_leave)
        self.add_controller(motion_controller)

        click_controller = Gtk.GestureClick.new()
        click_controller.connect('pressed', self.on_click)
        self.add_controller(click_controller)

        self.set_has_tooltip(True)
        self.connect("query-tooltip", self.on_query_tooltip)

    def set_compact_mode(self, compact, width, slot_count=0):
        self.compact = compact
        self.slot_count = slot_count
        self.margin_left = 38 if compact else 45
        self.margin_right = 10 if compact else 15
        self.margin_top = 16 if compact else 20
        self.margin_bottom = 26 if compact else 30
        content_width = get_chart_content_width(width, slot_count)
        self.set_size_request(content_width, get_chart_height(width))
        self.queue_draw()

    def set_prices(self, prices, current_index):
        """
        Updates the price data and current price index for the chart.
        Queues a redraw to reflect the new data.
        """
        self.prices = prices
        self.current_price_index = current_index
        self.queue_draw()

    def set_highlight_range(self, start_time, end_time):
        """
        Sets the time range to highlight on the chart.
        """
        self.highlight_start_time = start_time
        self.highlight_end_time = end_time
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

    def on_motion(self, controller, x, y):
        """
        Handles mouse motion events to detect hovering over price bars.
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

        if 0 <= new_hovered_index < len(self.prices) and new_hovered_index != self.hovered_index:
            self.hovered_index = new_hovered_index
            self.queue_draw()

    def on_leave(self, controller):
        """
        Handles mouse leaving the widget area, clearing any hover highlights.
        """
        if self.hovered_index != -1:
            self.hovered_index = -1
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
            parent_window = self.get_ancestor(Gtk.Window)
            if parent_window and hasattr(parent_window, 'on_chart_click'):
                parent_window.on_chart_click(clicked_index)

    def on_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        if not self.prices:
            return False

        width = self.get_width()
        chart_width = width - self.margin_left - self.margin_right

        if not (self.margin_left <= x <= width - self.margin_right):
            return False

        chart_x = x - self.margin_left
        bar_width = chart_width / len(self.prices)
        hover_index = int(chart_x / bar_width)

        if 0 <= hover_index < len(self.prices):
            price_data = self.prices[hover_index]
            price_gbp = price_data['price_gbp']
            valid_from = price_data['valid_from'].astimezone().strftime('%H:%M')
            valid_to = price_data['valid_to'].astimezone().strftime('%H:%M')

            tooltip.set_markup(f"<b>{valid_from} - {valid_to}</b>\n£{price_gbp:.2f}/kWh")
            return True

        return False

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
        display_min_price = 0 if min_price >= 0 else min_price
        price_range = max_price - display_min_price
        if price_range <= 0:
            price_range = 0.01

        chart_zero_y = self.margin_top + chart_height * (max_price / price_range) if display_min_price < 0 else self.margin_top + chart_height

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

        cr.set_font_size(10)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

        while current_grid_price <= max_price + 0.0001:
            line_y = chart_zero_y - (current_grid_price / price_range) * chart_height

            # Draw line (subtle)
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.1)
            cr.set_line_width(1.0)
            cr.move_to(self.margin_left, round(line_y) + 0.5)
            cr.line_to(self.margin_left + chart_width, round(line_y) + 0.5)
            cr.stroke()

            # Draw label (slightly clearer)
            label = f"£{current_grid_price:.2f}"
            extents = cr.text_extents(label)
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.5)
            # Center vertically on the line
            label_y = line_y - (extents.height / 2 + extents.y_bearing)
            cr.move_to(self.margin_left - extents.width - 5, label_y)
            cr.show_text(label)

            current_grid_price += step

        # --- Draw Bars ---
        last_date = None
        day_transition_x = None

        for i, price_data in enumerate(self.prices):
            price = price_data['price_gbp']
            bar_x_start = self.margin_left + (i * chart_width) / len(self.prices)
            bar_x_end = self.margin_left + ((i + 1) * chart_width) / len(self.prices)
            bar_x = round(bar_x_start)
            bar_width = round(bar_x_end) - bar_x

            # Check for day transition
            current_date = price_data['valid_from'].astimezone().date()
            if last_date and current_date != last_date:
                day_transition_x = bar_x
            last_date = current_date

            if price >= 0:
                bar_height = (price / price_range) * chart_height
                bar_y = chart_zero_y - bar_height
            else:
                bar_height = abs(price / price_range) * chart_height
                bar_y = chart_zero_y

            # Determine bar color
            if price < 0:
                success, color = style_context.lookup_color("blue_4")
                base_color = (color.red, color.green, color.blue) if success else (0.2, 0.4, 0.8)
            elif price < 0.15:
                success, color = style_context.lookup_color("green_4")
                base_color = (color.red, color.green, color.blue) if success else (0.2, 0.8, 0.2)
            elif price < 0.25:
                success, color = style_context.lookup_color("orange_3")
                base_color = (color.red, color.green, color.blue) if success else (1.0, 0.6, 0.0)
            else:
                success, color = style_context.lookup_color("red_4")
                base_color = (color.red, color.green, color.blue) if success else (0.8, 0.2, 0.2)

            if i == self.hovered_index:
                cr.set_source_rgb(min(1.0, base_color[0] + 0.3), min(1.0, base_color[1] + 0.3), min(1.0, base_color[2] + 0.3))
            else:
                cr.set_source_rgb(base_color[0] * 0.8, base_color[1] * 0.8, base_color[2] * 0.8)

            cr.rectangle(bar_x, bar_y, bar_width - 1, bar_height)
            cr.fill()

            # Highlight the best slot
            if self.highlight_start_time and self.highlight_end_time:
                if self.highlight_start_time <= price_data['valid_from'] < self.highlight_end_time:
                    cr.set_source_rgba(0.9, 0.9, 0.2, 0.3)  # Semi-transparent yellow
                    cr.rectangle(bar_x, self.margin_top, bar_width - 1, chart_height)
                    cr.fill()

            if i == self.current_price_index:
                cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, fg_color.alpha)
                cr.set_line_width(2)
                # Draw only 3 sides to avoid the "heavy" baseline look
                if price >= 0:
                    # Top and sides
                    cr.move_to(bar_x, chart_zero_y)
                    cr.line_to(bar_x, bar_y)
                    cr.line_to(bar_x + bar_width - 1, bar_y)
                    cr.line_to(bar_x + bar_width - 1, chart_zero_y)
                else:
                    # Bottom and sides
                    cr.move_to(bar_x, chart_zero_y)
                    cr.line_to(bar_x, bar_y + bar_height)
                    cr.line_to(bar_x + bar_width - 1, bar_y + bar_height)
                    cr.line_to(bar_x + bar_width - 1, chart_zero_y)
                cr.stroke()

        # --- Draw Day Transition Indicator ---
        if day_transition_x:
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.2)
            cr.set_line_width(1.0)
            cr.set_dash([4.0, 4.0])
            cr.move_to(day_transition_x, self.margin_top)
            cr.line_to(day_transition_x, self.margin_top + chart_height + 5)
            cr.stroke()
            cr.set_dash([]) # Reset dash

            # Day label
            cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.5)
            cr.move_to(day_transition_x + 5, self.margin_top + 10)
            cr.show_text("Tomorrow")

        # --- Draw Time Labels ---
        cr.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, 0.5)
        cr.set_font_size(9 if is_compact_width(width) else 10)
        label_interval = get_time_label_interval(width, len(self.prices))
        for i in range(0, len(self.prices), label_interval):
            if i < len(self.prices):
                time_str = self.prices[i]['valid_from'].astimezone().strftime('%H:%M')
                text_extents = cr.text_extents(time_str)
                bar_x_center = self.margin_left + ((i + 0.5) * chart_width) / len(self.prices)
                text_x = round(bar_x_center - text_extents.width / 2)
                text_y = height - 10
                cr.move_to(text_x, text_y)
                cr.show_text(time_str)
