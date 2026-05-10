import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
import logging
import threading
import time

import requests
from gi.repository import Adw, GLib, Gtk

from ..octopus_api import OctopusApiError, get_json
from ..price_logic import build_region_to_tariffs_map
from ..secrets_manager import clear_api_key, get_api_key, store_api_key
from ..usage_history import get_account_data
from ..utils import CacheManager
from .preferences_window import PreferencesWindow

logger = logging.getLogger(__name__)


class SetupWindow(Adw.Window):
    TARIFF_TYPES = PreferencesWindow.TARIFF_TYPES
    TARIFF_TYPE_CODES = PreferencesWindow.TARIFF_TYPE_CODES
    TARIFF_CODE_TO_NAME = PreferencesWindow.TARIFF_CODE_TO_NAME
    REGION_CODE_TO_NAME = PreferencesWindow.REGION_CODE_TO_NAME

    def __init__(self, settings, parent, on_complete=None, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Set Up Agile Rates")
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_default_size(560, 620)

        self.settings = settings
        self.parent_window = parent
        self.on_complete = on_complete
        self.cache_manager = CacheManager()
        self.all_regions = sorted(self.REGION_CODE_TO_NAME.values())
        self.region_to_tariffs = {}
        self._load_generation = 0

        self.setup_ui()
        self.load_tariffs_and_regions()

    def setup_ui(self):
        root = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        header = Adw.HeaderBar.new()
        self.back_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.back_button.set_tooltip_text("Back")
        self.back_button.add_css_class("flat")
        self.back_button.connect("clicked", self.on_back_clicked)
        header.pack_start(self.back_button)
        root.append(header)

        self.stack = Gtk.Stack.new()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.connect("notify::visible-child-name", self.on_page_changed)
        root.append(self.stack)

        self.stack.add_named(self._build_welcome_page(), "welcome")
        self.stack.add_named(self._build_account_page(), "account")
        self.stack.add_named(self._build_manual_page(), "manual")
        self.stack.add_named(self._build_complete_page(), "complete")
        self.set_content(root)
        self.stack.set_visible_child_name("welcome")
        self.on_page_changed(self.stack, None)

    def _build_page(self, title, subtitle=None):
        clamp = Adw.Clamp.new()
        box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        clamp.set_child(box)

        title_label = Gtk.Label.new(title)
        title_label.add_css_class("title-1")
        title_label.set_wrap(True)
        title_label.set_xalign(0)
        box.append(title_label)

        if subtitle:
            subtitle_label = Gtk.Label.new(subtitle)
            subtitle_label.add_css_class("body")
            subtitle_label.add_css_class("dim-label")
            subtitle_label.set_wrap(True)
            subtitle_label.set_xalign(0)
            box.append(subtitle_label)

        return clamp, box

    def _build_welcome_page(self):
        page, box = self._build_page(
            "Set up your tariff",
            "Use basic setup for prices only, or connect your account for auto-detection, usage history, and accurate historical spend.",
        )
        box.prepend(self._build_setup_artwork())

        full_button = Gtk.Button.new_with_label("Use My Account")
        full_button.add_css_class("suggested-action")
        full_button.connect("clicked", lambda _button: self.stack.set_visible_child_name("account"))
        box.append(full_button)

        manual_button = Gtk.Button.new_with_label("Choose Tariff Manually")
        manual_button.connect("clicked", lambda _button: self.stack.set_visible_child_name("manual"))
        box.append(manual_button)

        details = Gtk.Label.new(
            "Without an API key the app can still show current and upcoming prices. Account setup adds tariff auto-detection, usage history, and historical spend."
        )
        details.set_wrap(True)
        details.set_xalign(0)
        details.add_css_class("dim-label")
        box.append(details)

        return page

    def _build_setup_artwork(self):
        return self._build_resource_artwork(
            "/com/nedrichards/octopusagile/assets/setup-tour-illustration.png",
            190,
        )

    def _build_complete_artwork(self):
        return self._build_resource_artwork(
            "/com/nedrichards/octopusagile/assets/setup-complete-illustration.png",
            180,
        )

    def _build_resource_artwork(self, resource_path, height):
        artwork = Gtk.Picture.new_for_resource(resource_path)
        artwork.set_hexpand(True)
        artwork.set_size_request(-1, height)
        artwork.set_content_fit(Gtk.ContentFit.CONTAIN)
        return artwork

    def _build_account_page(self):
        page, box = self._build_page(
            "Connect your account",
            "Your API key is stored in your desktop password store and is only used for tariff and account API requests.",
        )

        api_box = Gtk.Box.new(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        api_box.add_css_class("card")
        box.append(api_box)

        api_title = Gtk.Label.new("Get an API key")
        api_title.add_css_class("heading")
        api_title.set_xalign(0)
        api_box.append(api_title)

        api_copy = Gtk.Label.new(
            "Open your Octopus dashboard, go to Developer settings, then generate or copy your API key."
        )
        api_copy.set_xalign(0)
        api_copy.set_wrap(True)
        api_copy.add_css_class("dim-label")
        api_box.append(api_copy)

        link = Gtk.LinkButton.new_with_label(
            "https://octopus.energy/dashboard/developer/",
            "Open API Dashboard",
        )
        link.set_halign(Gtk.Align.START)
        link.add_css_class("suggested-action")
        api_box.append(link)

        credentials = Adw.PreferencesGroup.new()
        credentials.set_title("Paste your details")
        box.append(credentials)

        self.api_key_entry = Adw.PasswordEntryRow.new()
        self.api_key_entry.set_title("API Key")
        existing_key = get_api_key()
        if existing_key:
            self.api_key_entry.set_text(existing_key)
        credentials.add(self.api_key_entry)

        self.account_entry = Adw.EntryRow.new()
        self.account_entry.set_title("Account Number")
        self.account_entry.set_text(self.settings.get_string("octopus-account-number"))
        credentials.add(self.account_entry)

        detail_help = Gtk.Label.new("Your account number is shown in your online account and on your bill.")
        detail_help.set_xalign(0)
        detail_help.set_wrap(True)
        detail_help.add_css_class("dim-label")
        box.append(detail_help)

        self.account_status = Gtk.Label.new("")
        self.account_status.set_xalign(0)
        self.account_status.set_wrap(True)
        self.account_status.add_css_class("dim-label")
        box.append(self.account_status)

        button_box = Gtk.Box.new(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        box.append(button_box)

        skip_button = Gtk.Button.new_with_label("Set Up Manually")
        skip_button.connect("clicked", lambda _button: self.stack.set_visible_child_name("manual"))
        button_box.append(skip_button)

        self.validate_button = Gtk.Button.new_with_label("Check Account")
        self.validate_button.add_css_class("suggested-action")
        self.validate_button.connect("clicked", self.on_validate_account_clicked)
        button_box.append(self.validate_button)

        return page

    def _build_manual_page(self):
        page, box = self._build_page(
            "Choose your tariff",
            "Agile and Go can be set up without account access. Intelligent Go needs an API key for its tariff data.",
        )

        group = Adw.PreferencesGroup.new()
        group.set_title("Tariff")
        box.append(group)

        self.tariff_type_model = Gtk.StringList.new(self.TARIFF_TYPES)
        self.tariff_type_row = Adw.ComboRow.new()
        self.tariff_type_row.set_title("Tariff Type")
        self.tariff_type_row.set_model(self.tariff_type_model)
        current_type = self.settings.get_string("selected-tariff-type")
        current_type_name = self.TARIFF_CODE_TO_NAME.get(current_type, "Agile")
        if current_type_name in self.TARIFF_TYPES:
            self.tariff_type_row.set_selected(self.TARIFF_TYPES.index(current_type_name))
        self.tariff_type_row.connect("notify::selected", self.on_tariff_type_selected)
        group.add(self.tariff_type_row)

        self.region_model = Gtk.StringList.new(self.all_regions)
        self.region_row = Adw.ComboRow.new()
        self.region_row.set_title("Region")
        self.region_row.set_model(self.region_model)
        self.region_row.connect("notify::selected", self.on_region_selected)
        group.add(self.region_row)

        self.tariff_model = Gtk.StringList.new(["Loading..."])
        self.tariff_row = Adw.ComboRow.new()
        self.tariff_row.set_title("Tariff")
        self.tariff_row.set_model(self.tariff_model)
        self.tariff_row.connect("notify::selected", self.on_tariff_selected)
        group.add(self.tariff_row)

        self.manual_api_group = Adw.PreferencesGroup.new()
        self.manual_api_group.set_title("API Key for Intelligent Go")
        self.manual_api_group.set_description(
            "Intelligent Go prices are account-specific, so the API requires a key even when you choose the tariff manually."
        )
        box.append(self.manual_api_group)

        manual_api_link = Gtk.LinkButton.new_with_label(
            "https://octopus.energy/dashboard/developer/",
            "Open API Dashboard",
        )
        manual_api_link.set_halign(Gtk.Align.START)
        self.manual_api_group.add(manual_api_link)

        account_setup_button = Gtk.Button.new_with_label("Use Account Setup Instead")
        account_setup_button.connect("clicked", lambda _button: self.stack.set_visible_child_name("account"))
        self.manual_api_group.add(account_setup_button)

        self.manual_api_key_entry = Adw.PasswordEntryRow.new()
        self.manual_api_key_entry.set_title("API Key")
        existing_key = get_api_key()
        if existing_key:
            self.manual_api_key_entry.set_text(existing_key)
        self.manual_api_key_entry.connect("changed", self.on_manual_api_key_changed)
        self.manual_api_group.add(self.manual_api_key_entry)

        self.manual_api_reload_button = Gtk.Button.new_with_label("Load Intelligent Go Tariffs")
        self.manual_api_reload_button.set_margin_top(8)
        self.manual_api_reload_button.connect("clicked", self.on_manual_api_reload_clicked)
        self.manual_api_group.add(self.manual_api_reload_button)

        self.manual_api_status = Gtk.Label.new("")
        self.manual_api_status.set_xalign(0)
        self.manual_api_status.set_wrap(True)
        self.manual_api_status.add_css_class("dim-label")
        self.manual_api_group.add(self.manual_api_status)

        self.manual_status = Gtk.Label.new("")
        self.manual_status.set_xalign(0)
        self.manual_status.set_wrap(True)
        self.manual_status.add_css_class("dim-label")
        box.append(self.manual_status)

        button_box = Gtk.Box.new(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        box.append(button_box)

        self.manual_finish_button = Gtk.Button.new_with_label("Start Using App")
        self.manual_finish_button.add_css_class("suggested-action")
        self.manual_finish_button.connect("clicked", self.on_manual_finish_clicked)
        button_box.append(self.manual_finish_button)

        self._update_manual_api_section()
        return page

    def _build_complete_page(self):
        page, box = self._build_page("Setup complete", "The recommended next step is to close setup and start using the app.")
        box.prepend(self._build_complete_artwork())

        self.complete_summary = Gtk.Label.new("")
        self.complete_summary.set_xalign(0)
        self.complete_summary.set_wrap(True)
        self.complete_summary.add_css_class("dim-label")
        box.append(self.complete_summary)

        self.complete_next_steps = Gtk.Label.new("")
        self.complete_next_steps.set_xalign(0)
        self.complete_next_steps.set_wrap(True)
        box.append(self.complete_next_steps)

        self.finish_button = Gtk.Button.new_with_label("Start Using App")
        self.finish_button.add_css_class("suggested-action")
        self.finish_button.set_hexpand(True)
        self.finish_button.connect("clicked", self.on_finish_clicked)
        box.append(self.finish_button)
        return page

    def on_page_changed(self, stack, _pspec):
        self.back_button.set_visible(stack.get_visible_child_name() not in ("welcome", "complete"))

    def on_back_clicked(self, _button):
        current = self.stack.get_visible_child_name()
        if current in ("account", "manual"):
            self.stack.set_visible_child_name("welcome")
        elif current == "complete":
            self.stack.set_visible_child_name("welcome")

    def on_tariff_type_selected(self, _row, _pspec):
        selected_display_name = self._get_selected_string(self.tariff_type_row)
        selected_type_code = self.TARIFF_TYPE_CODES.get(selected_display_name, "AGILE")
        previous_type_code = self.settings.get_string("selected-tariff-type")
        self.settings.set_string("selected-tariff-type", selected_type_code)
        if selected_type_code != previous_type_code:
            self.settings.set_string("selected-tariff-code", "")
        self._update_manual_api_section()
        self.load_tariffs_and_regions()

    def on_region_selected(self, _row, _pspec):
        selected_region_name = self._get_selected_string(self.region_row)
        selected_region_code = None
        for code, name in self.REGION_CODE_TO_NAME.items():
            if name == selected_region_name:
                selected_region_code = code
                break
        if selected_region_code:
            self.settings.set_string("selected-region-code", selected_region_code)
        self._update_tariff_dropdown()

    def on_tariff_selected(self, _row, _pspec):
        selected_region_code = self.settings.get_string("selected-region-code")
        tariffs = self.region_to_tariffs.get(selected_region_code, [])
        selected_index = self.tariff_row.get_selected()
        if 0 <= selected_index < len(tariffs):
            self.settings.set_string("selected-tariff-code", tariffs[selected_index]["code"])

    def on_manual_api_key_changed(self, entry):
        api_key = entry.get_text().strip()
        if api_key:
            store_api_key(api_key)
            self.manual_api_status.set_label("API key saved. Load Intelligent Go tariffs to continue.")
        else:
            clear_api_key()
            self.manual_api_status.set_label("Enter an API key to load Intelligent Go tariffs.")
        self._update_manual_api_section()

    def on_manual_api_reload_clicked(self, _button):
        self.load_tariffs_and_regions()

    def on_validate_account_clicked(self, _button):
        api_key = self.api_key_entry.get_text().strip()
        account_number = self.account_entry.get_text().strip()
        if not api_key or not account_number:
            self.account_status.set_label("Enter both your API key and account number.")
            return

        store_api_key(api_key)
        self.settings.set_string("octopus-account-number", account_number)
        self.validate_button.set_sensitive(False)
        self.account_status.set_label("Checking account and detecting tariff...")

        thread = threading.Thread(target=self._validate_account, args=(account_number,))
        thread.daemon = True
        thread.start()

    def _validate_account(self, account_number):
        try:
            account_data = get_account_data(account_number)
            tariff_code = self._extract_active_tariff_code(account_data)
            if not tariff_code:
                GLib.idle_add(self._account_validation_failed, "No active electricity tariff was found on this account.")
                return

            inferred_region_code = f"_{tariff_code.split('-')[-1]}" if "-" in tariff_code else ""
            self.settings.set_string("selected-tariff-code", tariff_code)
            if inferred_region_code in self.REGION_CODE_TO_NAME:
                self.settings.set_string("selected-region-code", inferred_region_code)
            self.settings.set_string("selected-tariff-type", self._infer_tariff_type_from_code(tariff_code))
            GLib.idle_add(self._account_validation_complete, tariff_code)
        except OctopusApiError as e:
            GLib.idle_add(self._account_validation_failed, f"{e} Check your API key and account number.")
        except requests.exceptions.RequestException as e:
            GLib.idle_add(self._account_validation_failed, f"Network error: {e}.")
        except Exception as e:
            GLib.idle_add(self._account_validation_failed, f"Could not validate account: {e}.")

    def _account_validation_complete(self, tariff_code):
        self.validate_button.set_sensitive(True)
        self.complete_summary.set_label(
            f"Detected tariff {tariff_code} from your account."
        )
        self.complete_next_steps.set_label(
            "Close setup to load prices now. Usage history and historical spend will refresh in the background."
        )
        self.settings.set_boolean("setup-completed", True)
        self.stack.set_visible_child_name("complete")
        return False

    def _account_validation_failed(self, message):
        self.validate_button.set_sensitive(True)
        self.account_status.set_label(message)
        return False

    def on_manual_finish_clicked(self, _button):
        selected_tariff = self.settings.get_string("selected-tariff-code")
        if not selected_tariff:
            self.manual_status.set_label("Choose a tariff before continuing.")
            return

        if self.settings.get_string("selected-tariff-type") == "INTELLIGENT" and not get_api_key():
            self.manual_status.set_label("Add your API key before using Intelligent Go.")
            return
        if (
            self.settings.get_string("selected-tariff-type") == "INTELLIGENT"
            and self._infer_tariff_type_from_code(selected_tariff) != "INTELLIGENT"
        ):
            self.manual_status.set_label("Load and choose an Intelligent Go tariff before continuing.")
            return

        self.settings.set_boolean("setup-completed", True)
        self.complete_summary.set_label(
            "Your tariff is selected."
        )
        if self.settings.get_string("selected-tariff-type") == "INTELLIGENT":
            self.complete_next_steps.set_label(
                "Close setup to load prices now. Add your account number later from Preferences to enable usage history."
            )
        else:
            self.complete_next_steps.set_label(
                "Close setup to load prices now. You can add an API key later from Preferences to enable usage history."
            )
        self.stack.set_visible_child_name("complete")

    def on_finish_clicked(self, _button):
        if self.on_complete:
            self.on_complete()
        self.close()

    def load_tariffs_and_regions(self):
        self._load_generation += 1
        request_id = self._load_generation
        self._update_manual_api_section()
        if self.settings.get_string("selected-tariff-type") == "INTELLIGENT" and not get_api_key():
            self.region_to_tariffs = {}
            self.settings.set_string("selected-tariff-code", "")
            self.tariff_model = Gtk.StringList.new(["API key required"])
            self.tariff_row.set_model(self.tariff_model)
            self.tariff_row.set_sensitive(False)
            self.manual_finish_button.set_sensitive(False)
            self.manual_status.set_label("Add an API key to load Intelligent Go tariffs, or go back and connect your account.")
            if hasattr(self, "manual_api_status"):
                self.manual_api_status.set_label("Enter an API key, then load Intelligent Go tariffs.")
            return
        self.tariff_row.set_sensitive(False)
        self.manual_status.set_label("Fetching available tariffs...")
        thread = threading.Thread(target=self._fetch_tariffs, args=(request_id,))
        thread.daemon = True
        thread.start()

    def _fetch_tariffs(self, request_id):
        try:
            cache_key = "octopus_products_all"
            url = "https://api.octopus.energy/v1/products/"
            tariff_type = self.settings.get_string("selected-tariff-type")
            cached_data, cache_mtime = self.cache_manager.get(cache_key)
            if cached_data and cache_mtime and (time.time() - cache_mtime) < 86400:
                data = cached_data
            else:
                data = get_json(url, timeout=10)
                self.cache_manager.set(cache_key, data)

            target_product = self._find_target_product(data, tariff_type)
            if not target_product:
                GLib.idle_add(self._show_manual_error, f"No active {tariff_type} tariff found.")
                return

            product_url = f"https://api.octopus.energy/v1/products/{target_product['code']}/"
            product_cache_key = f"octopus_product_{target_product['code']}"
            cached_product_data, product_cache_mtime = self.cache_manager.get(product_cache_key)
            if cached_product_data and product_cache_mtime and (time.time() - product_cache_mtime) < 86400:
                product_details = cached_product_data
            else:
                product_details = get_json(product_url, timeout=10, use_api_key=tariff_type == "INTELLIGENT")
                self.cache_manager.set(product_cache_key, product_details)

            if request_id == self._load_generation:
                region_to_tariffs = build_region_to_tariffs_map(product_details, self.REGION_CODE_TO_NAME)
                GLib.idle_add(self._apply_tariff_data, region_to_tariffs)
        except OctopusApiError as e:
            GLib.idle_add(self._show_manual_error, f"{e} Cannot load tariffs.")
        except requests.exceptions.RequestException as e:
            GLib.idle_add(self._show_manual_error, f"Network error: {e}. Cannot load tariffs.")
        except Exception as e:
            GLib.idle_add(self._show_manual_error, f"Error loading tariffs: {e}.")

    def _apply_tariff_data(self, region_to_tariffs):
        self.region_to_tariffs = region_to_tariffs
        self._update_region_dropdown()
        self._update_tariff_dropdown()
        self.tariff_row.set_sensitive(True)
        self.manual_status.set_label("")
        if self.settings.get_string("selected-tariff-type") == "INTELLIGENT":
            self.manual_api_status.set_label("Intelligent Go tariffs loaded. Choose your region and tariff.")
        self._update_manual_api_section()
        return False

    def _show_manual_error(self, message):
        self.manual_status.set_label(message)
        self.tariff_row.set_sensitive(False)
        self._update_manual_api_section()
        return False

    def _update_region_dropdown(self):
        selected_region_code = self.settings.get_string("selected-region-code")
        selected_region_name = self.REGION_CODE_TO_NAME.get(selected_region_code)
        if not selected_region_name:
            selected_region_code = "_A"
            selected_region_name = self.REGION_CODE_TO_NAME[selected_region_code]
            self.settings.set_string("selected-region-code", selected_region_code)

        if selected_region_name in self.all_regions:
            self.region_row.set_selected(self.all_regions.index(selected_region_name))

    def _update_tariff_dropdown(self):
        selected_region_code = self.settings.get_string("selected-region-code")
        tariffs = self.region_to_tariffs.get(selected_region_code, [])
        if not tariffs:
            self.settings.set_string("selected-tariff-code", "")
            self.tariff_model = Gtk.StringList.new(["No tariffs available"])
            self.tariff_row.set_model(self.tariff_model)
            self.tariff_row.set_sensitive(False)
            self._update_manual_api_section()
            return

        names = [tariff["full_name"] for tariff in tariffs]
        self.tariff_model = Gtk.StringList.new(names)
        self.tariff_row.set_model(self.tariff_model)
        saved_tariff_code = self.settings.get_string("selected-tariff-code")
        selected_index = 0
        for index, tariff in enumerate(tariffs):
            if tariff["code"] == saved_tariff_code:
                selected_index = index
                break
        self.tariff_row.set_selected(selected_index)
        self.settings.set_string("selected-tariff-code", tariffs[selected_index]["code"])
        self.tariff_row.set_sensitive(True)
        self._update_manual_api_section()

    def _update_manual_api_section(self):
        if not hasattr(self, "manual_api_group"):
            return

        is_intelligent = self.settings.get_string("selected-tariff-type") == "INTELLIGENT"
        self.manual_api_group.set_visible(is_intelligent)
        if not hasattr(self, "manual_finish_button"):
            return

        if not is_intelligent:
            self.manual_finish_button.set_sensitive(True)
            return

        has_key = bool(get_api_key())
        self.manual_api_reload_button.set_sensitive(has_key)
        self.manual_finish_button.set_sensitive(has_key and bool(self.settings.get_string("selected-tariff-code")))
        if not has_key and not self.manual_api_status.get_label():
            self.manual_api_status.set_label("Enter an API key to load Intelligent Go tariffs.")

    def _find_target_product(self, data, tariff_type):
        for product in data.get("results", []):
            code = product.get("code", "").upper()
            name = product.get("full_name", "").upper()
            is_go = self._contains_token(code, "GO") or self._contains_token(name, "GO")
            is_intelligent = (
                self._contains_token(code, "INTELLI")
                or self._contains_token(code, "INTELLIGENT")
                or self._contains_token(name, "INTELLI")
                or self._contains_token(name, "INTELLIGENT")
            )
            is_export = (
                self._contains_token(code, "OUTGOING")
                or self._contains_token(code, "EXPORT")
                or self._contains_token(name, "OUTGOING")
                or self._contains_token(name, "EXPORT")
            )

            if tariff_type == "AGILE" and "AGILE" in code and not is_export:
                return product if product.get("available_from") and not product.get("available_to") else None
            if tariff_type == "GO" and is_go and not is_intelligent:
                return product if product.get("available_from") and not product.get("available_to") else None
            if tariff_type == "INTELLIGENT" and is_intelligent:
                return product if product.get("available_from") and not product.get("available_to") else None

        return None

    def _extract_active_tariff_code(self, account_data):
        return PreferencesWindow._extract_active_tariff_code(self, account_data)

    def _infer_tariff_type_from_code(self, tariff_code):
        return PreferencesWindow._infer_tariff_type_from_code(self, tariff_code)

    @staticmethod
    def _contains_token(value, token):
        return PreferencesWindow._contains_token(value, token)

    def _get_selected_string(self, combo_row):
        selected = combo_row.get_selected_item()
        return selected.get_string() if selected else None
