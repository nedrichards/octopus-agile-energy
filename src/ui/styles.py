def get_css():
    return """
    /* Styling for Adw.StatusPage based on price level */
    .price-high {
        color: @error_color; /* Uses LibAdwaita's error color */
    }
    .price-medium {
        color: @warning_color; /* Uses LibAdwaita's warning color */
    }
    .price-low {
        color: @success_color; /* Uses LibAdwaita's success color */
    }
    .price-negative {
        color: @accent_color; /* Uses LibAdwaita's accent color for negative prices */
    }

    /* Styling for the persistent status label for errors */
    .error {
        color: @error_color;
        font-weight: bold;
    }

    /* Style for Gtk.Frame to make it look like a card */
    .card {
        border-radius: 12px; /* Rounded corners */
        background-color: @card_background_color; /* Use Adwaita card background color */
        border-width: 1px;
        border-style: solid;
        border-color: @border_color; /* Use Adwaita border color */
    }
    .card label.title {
        font-weight: bold;
        padding-top: 10px;
        padding-bottom: 5px;
        padding-left: 10px;
    }
    """
