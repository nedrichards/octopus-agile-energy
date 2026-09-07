import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gi.repository import Gtk
from src.ui.paid_rate_chart import PaidRateChart


class PaidRateScrubbingTests(unittest.TestCase):
    def chart(self):
        chart = SimpleNamespace(points=list(range(11)), selected=0, area=Mock(), _describe=Mock())
        chart.area.get_width.return_value = 168
        chart._select_at_x = lambda x: PaidRateChart._select_at_x(chart, x)
        chart._drag_cancel = lambda gesture, sequence: PaidRateChart._drag_cancel(chart, gesture, sequence)
        PaidRateChart._drag_begin(chart, None, 52, 0)
        return chart

    def test_horizontal_drag_tracks_pointer_and_clamps_edges(self):
        chart, gesture = self.chart(), Mock()
        PaidRateChart._drag_update(chart, gesture, 50, 1)
        self.assertEqual(chart.selected, 5)
        gesture.set_state.assert_called_once_with(Gtk.EventSequenceState.CLAIMED)
        PaidRateChart._drag_update(chart, gesture, 500, 1)
        self.assertEqual(chart.selected, 10)
        PaidRateChart._drag_end(chart, gesture, -100, 0)
        self.assertEqual(chart.selected, 0)
        self.assertIsNone(chart._drag_start_x)

    def test_vertical_motion_yields_to_scrolling(self):
        chart, gesture = self.chart(), Mock()
        PaidRateChart._drag_update(chart, gesture, 1, 50)
        gesture.set_state.assert_called_once_with(Gtk.EventSequenceState.DENIED)
        PaidRateChart._drag_update(chart, gesture, 50, 1)
        self.assertEqual(chart.selected, 0)

    def test_small_motion_and_cancel_do_not_scrub(self):
        chart, gesture = self.chart(), Mock()
        PaidRateChart._drag_update(chart, gesture, 3, 1)
        gesture.set_state.assert_not_called()
        PaidRateChart._drag_cancel(chart, gesture, None)
        PaidRateChart._drag_update(chart, gesture, 50, 1)
        chart._describe.assert_not_called()
