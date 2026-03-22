def get_css():
    """
    Returns the application's custom CSS as a string.
    This allows styles to be loaded dynamically at runtime.
    """
    return """
    /* Price level styles now target title and description labels for color */
    .price-negative .regular-price-title,
    .price-negative .regular-price-description,
    .price-negative .compact-price-title,
    .price-negative .compact-price-description {
        color: @blue_4;
    }

    .price-low .regular-price-title,
    .price-low .regular-price-description,
    .price-low .compact-price-title,
    .price-low .compact-price-description {
        color: @green_4;
    }

    .price-medium .regular-price-title,
    .price-medium .regular-price-description,
    .price-medium .compact-price-title,
    .price-medium .compact-price-description {
        color: @orange_3;
    }

    .price-high .regular-price-title,
    .price-high .regular-price-description,
    .price-high .compact-price-title,
    .price-high .compact-price-description {
        color: @red_4;
    }

    .regular-price-card {
        padding: 20px 0 10px 0;
    }

    .regular-price-title {
        font-size: 2.8rem;
        font-weight: 700;
    }

    .regular-price-description {
        opacity: 0.8;
    }

    .compact-price-card {
        padding: 8px 0 2px 0;
    }

    .compact-price-title {
        font-weight: 700;
    }

    .compact-price-description {
        opacity: 0.7;
    }

    .card {
        background-color: @window_bg_color;
        border: 1px solid @window_border_color;
        border-radius: 12px;
        padding: 12px;
    }

    .error {
        color: @error_fg_color; /* Use Adwaita's standard error color */
    }

    /* Style for the chart background, giving it a subtle off-white color and border */
    .chart-background {
        background-color: alpha(currentColor, 0.05);
        border: 1px solid alpha(currentColor, 0.1);
        border-radius: 6px; /* Slightly rounded corners for the chart area */
    }

    .circular {
        border-radius: 9999px;
        min-height: 32px;
        min-width: 32px;
        padding: 0;
        border: none;
    }
    """
