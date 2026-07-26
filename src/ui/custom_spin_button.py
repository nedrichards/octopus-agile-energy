from typing import ClassVar

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, GObject, Gtk


class CustomSpinButton(Gtk.Box):
    __gsignals__: ClassVar[dict[str, tuple]] = {
        'value-changed': (GObject.SignalFlags.RUN_FIRST, None, ())
    }

    def __init__(self, min_val=1, max_val=24, step=1, accessible_label="Duration"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self._value = min_val
        self.accessible_label = accessible_label

        self.add_css_class('linked')
        self.set_accessible_role(Gtk.AccessibleRole.SPIN_BUTTON)
        self.set_focusable(True)

        self.label = Gtk.Label()
        self.label.set_width_chars(6)
        self.label.set_xalign(0.5)
        self.label.set_valign(Gtk.Align.CENTER)
        self.append(self.label)

        self.minus_button = Gtk.Button.new_from_icon_name("list-remove-symbolic")
        self.minus_button.add_css_class('circular')
        self.minus_button.set_tooltip_text(f"Decrease {accessible_label.lower()}")
        self.minus_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Decrease {accessible_label.lower()}"],
        )
        self.minus_button.set_valign(Gtk.Align.CENTER)
        self.minus_button.connect("clicked", self.on_minus_clicked)
        self.append(self.minus_button)

        self.plus_button = Gtk.Button.new_from_icon_name("list-add-symbolic")
        self.plus_button.add_css_class('circular')
        self.plus_button.set_tooltip_text(f"Increase {accessible_label.lower()}")
        self.plus_button.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"Increase {accessible_label.lower()}"],
        )
        self.plus_button.set_valign(Gtk.Align.CENTER)
        self.plus_button.connect("clicked", self.on_plus_clicked)
        self.append(self.plus_button)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

        self.update_label()

    def on_minus_clicked(self, button):
        self.decrement()

    def on_plus_clicked(self, button):
        self.increment()

    def increment(self):
        previous_value = self._value
        if self._value < self.max_val:
            self._value = min(self.max_val, self._value + self.step)
        self._emit_if_changed(previous_value)

    def decrement(self):
        previous_value = self._value
        if self._value > self.min_val:
            self._value = max(self.min_val, self._value - self.step)
        self._emit_if_changed(previous_value)

    def _emit_if_changed(self, previous_value):
        if self._value != previous_value:
            self.update_label()
            self.emit('value-changed')

    def on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up, Gdk.KEY_Right, Gdk.KEY_KP_Right):
            self.increment()
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down, Gdk.KEY_Left, Gdk.KEY_KP_Left):
            self.decrement()
        elif keyval in (Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up):
            previous_value = self._value
            self._value = min(self.max_val, self._value + self.step * 2)
            self._emit_if_changed(previous_value)
        elif keyval in (Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Down):
            previous_value = self._value
            self._value = max(self.min_val, self._value - self.step * 2)
            self._emit_if_changed(previous_value)
        elif keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            previous_value = self._value
            self._value = self.min_val
            self._emit_if_changed(previous_value)
        elif keyval in (Gdk.KEY_End, Gdk.KEY_KP_End):
            previous_value = self._value
            self._value = self.max_val
            self._emit_if_changed(previous_value)
        else:
            return False

        return True

    def get_value(self):
        return self._value

    def get_value_as_int(self):
        return int(self._value)

    def set_value(self, value):
        if self.min_val <= value <= self.max_val:
            self._value = value
            self.update_label()
            self.emit('value-changed')

    def update_label(self):
        hours = int(self._value)
        minutes = round((self._value - hours) * 60)
        if minutes == 0:
            value_text = f"{hours}h"
        else:
            value_text = f"{hours}h {minutes}m"

        self.label.set_text(value_text)
        self.update_property(
            [
                Gtk.AccessibleProperty.LABEL,
                Gtk.AccessibleProperty.VALUE_MIN,
                Gtk.AccessibleProperty.VALUE_MAX,
                Gtk.AccessibleProperty.VALUE_NOW,
                Gtk.AccessibleProperty.VALUE_TEXT,
            ],
            [
                self.accessible_label,
                float(self.min_val),
                float(self.max_val),
                float(self._value),
                value_text,
            ],
        )
