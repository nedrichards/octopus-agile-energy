import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from datetime import datetime
import cairo

class PriceChartWidget(Gtk.DrawingArea):
    """
    A custom Gtk.DrawingArea widget for displaying Octopus Agile electricity prices as a bar chart.
    Supports current price highlighting and hover effects for detailed information.
    """
    def __init__(self):
        super().__init__()
        self.prices = []
        self.current_price_index = -1
        self.hovered_index = -1

        # Set a reasonable default size, though the widget will expand/contract with its parent.
        self.set_size_request(600, 200)
        self.set_draw_func(self.on_draw)

        # Set up mouse motion events for hovering over bars.
        motion_controller = Gtk.EventControllerMotion.new()
        motion_controller.connect('motion', self.on_motion)
        motion_controller.connect('leave', self.on_leave)
        self.add_controller(motion_controller)

        # Set up click events (currently mirrors hover info but can be extended).
        click_controller = Gtk.GestureClick.new()
        click_controller.connect('pressed', self.on_click)
        self.add_controller(click_controller)

    def set_prices(self, prices, current_index):
        """
        Updates the price data and current price index for the chart.
        Queues a redraw to reflect the new data.
        """
        self.prices = prices
        self.current_price_index = current_index
        self.queue_draw() # Request a redraw of the widget.

    def on_motion(self, controller, x, y):
        """
        Handles mouse motion events to detect hovering over price bars.
        Updates `hovered_index` and notifies the parent window for detailed display.
        """
        if not self.prices:
            return

        width = self.get_width()
        if len(self.prices) == 0:
            return

        bar_width = width / len(self.prices)
        new_hovered_index = int(x / bar_width)

        if 0 <= new_hovered_index < len(self.prices):
            if new_hovered_index != self.hovered_index:
                self.hovered_index = new_hovered_index
                self.queue_draw() # Redraw to highlight the hovered bar.

                # Notify the parent window about the hover event.
                parent = self.get_parent()
                while parent and not hasattr(parent, 'on_chart_hover'):
                    parent = parent.get_parent()
                if parent:
                    parent.on_chart_hover(self.hovered_index)

    def on_leave(self, controller):
        """
        Handles mouse leaving the widget area, clearing any hover highlights.
        """
        if self.hovered_index != -1:
            self.hovered_index = -1
            self.queue_draw() # Redraw to remove hover highlight.

            # Notify the parent window to clear hover info.
            parent = self.get_parent()
            while parent and not hasattr(parent, 'on_chart_hover'):
                parent = parent.get_parent()
            if parent:
                parent.on_chart_hover(-1)

    def on_click(self, gesture, n_press, x, y):
        """
        Handles click events on the chart. Currently mirrors hover logic but can be expanded.
        """
        if not self.prices:
            return

        width = self.get_width()
        if len(self.prices) == 0:
            return

        bar_width = width / len(self.prices)
        clicked_index = int(x / bar_width)

        if 0 <= clicked_index < len(self.prices):
            # For this simple app, re-using on_chart_hover for click feedback.
            parent = self.get_parent()
            while parent and not hasattr(parent, 'on_chart_click'):
                parent = parent.get_parent()
            if parent:
                parent.on_chart_click(clicked_index) # This can be expanded for specific click actions.

    def on_draw(self, area, cr, width, height):
        """
        The main drawing function for the chart, called by GTK when the widget needs to be redrawn.
        Draws the price bars and time labels. The background is now implicitly handled by GTK4.
        """
        if not self.prices or len(self.prices) == 0:
            return

        # Calculate chart dimensions and bar width.
        margin = 20
        chart_width = width - 2 * margin
        chart_height = height - 2 * margin
        bar_width = chart_width / len(self.prices)

        # Find min and max prices to scale the chart appropriately.
        prices_values = [p['value_inc_vat'] / 100 for p in self.prices] # Convert p/kWh to £/kWh
        min_price = min(prices_values)
        max_price = max(prices_values)
        price_range = max_price - min_price

        if price_range == 0:
            price_range = 1 # Avoid division by zero if all prices are the same.

        # Determine the Y position of the zero price line.
        if min_price < 0:
            # If negative prices exist, the zero line is proportional.
            chart_zero_y = margin + chart_height * (max_price / price_range)
        else:
            # If all prices are positive, the zero line is at the bottom of the chart area.
            chart_zero_y = margin + chart_height

        # Iterate through prices and draw each bar.
        for i, price_data in enumerate(self.prices):
            price = price_data['value_inc_vat'] / 100

            # Calculate bar position and height based on price relative to min/max and zero line.
            bar_x = margin + i * bar_width

            if price >= 0:
                if min_price < 0:
                    bar_height = (price / price_range) * chart_height
                    bar_y = chart_zero_y - bar_height
                else:
                    bar_height = ((price - min_price) / price_range) * chart_height
                    bar_y = margin + chart_height - bar_height
            else: # Negative price
                bar_height = abs(price / price_range) * chart_height
                bar_y = chart_zero_y

            # Define base color based on price level.
            if price < 0:
                base_color = (0.2, 0.4, 0.8) # Blue for negative prices
            elif price < 0.15:
                base_color = (0.2, 0.8, 0.2) # Green for low prices
            elif price < 0.25:
                base_color = (1.0, 0.6, 0.0) # Orange for medium prices
            else:
                base_color = (0.8, 0.2, 0.2) # Red for high prices

            # Adjust color based on current/hovered state.
            if i == self.current_price_index:
                cr.set_source_rgb(base_color[0], base_color[1], base_color[2]) # Full color for current.
                cr.set_line_width(2)
            elif i == self.hovered_index:
                # Lighter color for hovered bars.
                cr.set_source_rgb(
                    min(1.0, base_color[0] + 0.3),
                    min(1.0, base_color[1] + 0.3),
                    min(1.0, base_color[2] + 0.3)
                )
            else:
                # Slightly faded color for normal bars.
                cr.set_source_rgb(
                    base_color[0] * 0.8,
                    base_color[1] * 0.8,
                    base_color[2] * 0.8
                )

            # Draw the filled bar.
            cr.rectangle(bar_x + 1, bar_y, bar_width - 2, bar_height)
            cr.fill()

            # Draw a black outline for the current price bar.
            if i == self.current_price_index:
                cr.set_source_rgb(0, 0, 0)
                cr.set_line_width(2)
                cr.rectangle(bar_x + 1, bar_y, bar_width - 2, bar_height)
                cr.stroke()

        # Draw time labels at intervals (e.g., every 4 hours).
        cr.set_source_rgb(0, 0, 0) # Black text.
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)

        for i in range(0, len(self.prices), 8): # 8 half-hour periods = 4 hours.
            if i < len(self.prices):
                time_str = datetime.fromisoformat(
                    self.prices[i]['valid_from'].replace('Z', '+00:00')
                ).astimezone().strftime('%H:%M')

                text_x = margin + i * bar_width
                text_y = height - 5

                # Center the text below the bar.
                text_extents = cr.text_extents(time_str)
                cr.move_to(text_x - text_extents.width / 2, text_y)
                cr.show_text(time_str)
