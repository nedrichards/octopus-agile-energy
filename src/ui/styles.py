def get_css():
    """
    Returns the application's custom CSS as a string.
    This allows styles to be loaded dynamically at runtime.
    """
    return """
    /* Price level styles now target title and description labels for color */
    .price-negative .title,
    .price-negative .description {
        color: #5294e2; /* A pleasant blue for negative prices */
    }

    .price-low .title,
    .price-low .description {
        color: #87cf7d; /* A calm green for low prices */
    }

    .price-medium .title,
    .price-medium .description {
        color: #f9a856; /* A warm orange for medium prices */
    }

    .price-high .title,
    .price-high .description {
        color: #e06a5c; /* A soft red for high prices */
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
    """
