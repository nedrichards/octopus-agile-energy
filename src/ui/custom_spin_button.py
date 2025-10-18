import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GObject

class CustomSpinButton(Gtk.Box):
    __gsignals__ = {
        'value-changed': (GObject.SignalFlags.RUN_FIRST, None, ())
    }

    def __init__(self, min_val=1, max_val=24, step=1):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self._value = min_val

        self.add_css_class('linked')

        self.label = Gtk.Label()
        self.label.set_width_chars(4)
        self.label.set_xalign(0.5)
        self.label.set_valign(Gtk.Align.CENTER)
        self.append(self.label)

        self.minus_button = Gtk.Button.new_from_icon_name("list-remove-symbolic")
        self.minus_button.add_css_class('circular')
        self.minus_button.set_valign(Gtk.Align.CENTER)
        self.minus_button.connect("clicked", self.on_minus_clicked)
        self.append(self.minus_button)

        self.plus_button = Gtk.Button.new_from_icon_name("list-add-symbolic")
        self.plus_button.add_css_class('circular')
        self.plus_button.set_valign(Gtk.Align.CENTER)
        self.plus_button.connect("clicked", self.on_plus_clicked)
        self.append(self.plus_button)

        self.update_label()

    def on_minus_clicked(self, button):
        if self._value > self.min_val:
            self._value -= self.step
            self.update_label()
            self.emit('value-changed')

    def on_plus_clicked(self, button):
        if self._value < self.max_val:
            self._value += self.step
            self.update_label()
            self.emit('value-changed')

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
        self.label.set_text(str(self._value) + "h")
