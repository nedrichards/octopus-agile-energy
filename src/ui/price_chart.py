import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk
from datetime import datetime
import cairo

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
        self.margin = 20
        self.highlight_start_time = None
        self.highlight_end_time = None

        self.set_size_request(600, 200)
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

    def on_motion(self, controller, x, y):
        """
        Handles mouse motion events to detect hovering over price bars.
        """
        if not self.prices:
            return

        width = self.get_width()
        chart_width = width - 2 * self.margin
        if not (self.margin <= x <= width - self.margin):
            if self.hovered_index != -1:
                self.on_leave(controller)
            return

        chart_x = x - self.margin
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
        chart_width = width - 2 * self.margin
        if not (self.margin <= x <= width - self.margin):
            return

        chart_x = x - self.margin
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
        chart_width = width - 2 * self.margin
        
        if not (self.margin <= x <= width - self.margin):
            return False
            
        chart_x = x - self.margin
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

        chart_width = width - 2 * self.margin
        chart_height = height - 2 * self.margin

        prices_gbp = [p['price_gbp'] for p in self.prices]
        min_price = min(prices_gbp)
        max_price = max(prices_gbp)
        display_min_price = 0 if min_price >= 0 else min_price
        price_range = max_price - display_min_price
        if price_range == 0:
            price_range = 1

        chart_zero_y = self.margin + chart_height * (max_price / price_range) if min_price < 0 else self.margin + chart_height

        # Fetch style context once for the loop
        style_context = self.get_style_context()

        for i, price_data in enumerate(self.prices):
            price = price_data['price_gbp']
            bar_x_start = self.margin + (i * chart_width) / len(self.prices)
            bar_x_end = self.margin + ((i + 1) * chart_width) / len(self.prices)
            bar_x = round(bar_x_start)
            bar_width = round(bar_x_end) - bar_x

            if price >= 0:
                bar_height = (price / price_range) * chart_height
                bar_y = chart_zero_y - bar_height
            else:
                bar_height = abs(price / price_range) * chart_height
                bar_y = chart_zero_y

            if price < 0:
                # Use theme accent colors for varied states
                # Fetching standard error color for negative prices
                success, color = style_context.lookup_color("blue_4")
                if success:
                    base_color = (color.red, color.green, color.blue)
                else:
                    base_color = (0.2, 0.4, 0.8)
            elif price < 0.15:
                success, color = style_context.lookup_color("green_4")
                if success:
                    base_color = (color.red, color.green, color.blue)
                else:
                    base_color = (0.2, 0.8, 0.2)
            elif price < 0.25:
                success, color = style_context.lookup_color("orange_3")
                if success:
                    base_color = (color.red, color.green, color.blue)
                else:
                    base_color = (1.0, 0.6, 0.0)
            else:
                success, color = style_context.lookup_color("red_4")
                if success:
                    base_color = (color.red, color.green, color.blue)
                else:
                    base_color = (0.8, 0.2, 0.2)

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
                    cr.rectangle(bar_x, self.margin, bar_width - 1, chart_height)
                    cr.fill()

            if i == self.current_price_index:
                style_context = self.get_style_context()
                color = style_context.get_color()
                cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
                cr.set_line_width(2)
                cr.rectangle(bar_x, bar_y, bar_width - 1, bar_height)
                cr.stroke()

        style_context = self.get_style_context()
        color = style_context.get_color()
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)

        for i in range(0, len(self.prices), 8):
            if i < len(self.prices):
                time_str = self.prices[i]['valid_from'].astimezone().strftime('%H:%M')
                text_extents = cr.text_extents(time_str)
                bar_x_center = self.margin + ((i + 0.5) * chart_width) / len(self.prices)
                text_x = round(bar_x_center - text_extents.width / 2)
                text_y = height - 5
                cr.move_to(text_x, text_y)
                cr.show_text(time_str)