# Octopus Agile Energy

This is a modern GNOME application built to track and visualise Octopus Energy's Agile electricity prices in real-time. It fetches current and forecasted half-hourly prices, allowing users to quickly see the best times to use electricity. This is only relevant if you are based in the UK.

* **Current Price Display:** Shows the real-time Agile electricity price (pence/kWh).
* **Price Level Indicators:** Visually indicates whether the current price is low, medium, high, or even negative.
* **Price Forecast Chart:** Displays a bar chart of the next 48 hours of half-hourly price data, helping users plan their energy consumption.
* **Find Cheapest Time:** A built-in calculator to find the cheapest time window for a specific duration (e.g., "find the cheapest 3 hours in the next 24 hours").
* **Region and Tariff Selection:** Allows users to select their specific Octopus Energy region and Agile tariff code through a preferences window. Supports Agile, Go, and Intelligent Octopus Go tariffs. Go and Intelligent tariffs need a user provided API key.

![The application interface, showing the current price and a graph of future prices](data/octopus-agile-screenshot.png "Application screenshot")

## Installation

This application is built for GNOME 50 and can be easily built and run using Flatpak and Flatpak Builder or directly through GNOME Builder.

### Prerequisites

Ensure you have Flatpak and Flatpak Builder installed on your system. Refer to the official Flatpak documentation for installation instructions specific to your distribution.

### Using GNOME Builder

GNOME Builder is the recommended way to work with this project. It provides a convenient development environment that handles Flatpak integration automatically.

1.  **Open GNOME Builder:** Launch GNOME Builder on your system.
2.  **Clone the Project:**
    *   Go to "Clone Repository".
    *   Enter the repository URL (`https://github.com/nedrichards/octopus-agile-energy.git`).
    *   Choose a destination folder and click "Clone".
3.  **Build and Run:**
    *   Once the project is loaded, GNOME Builder will detect the `com.nedrichards.octopusagile.json` manifest.
    *   Click the "Run" button (usually a play icon) in the top bar. Builder will automatically build the Flatpak application and run it.

### Building with Flatpak Builder (CLI)

If you prefer to build the Flatpak from the command line, follow these steps:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/nedrichards/octopus-agile-energy.git
    cd octopus-agile-energy
    ```

2.  **Build the Flatpak:**
    ```bash
    flatpak-builder --force-clean build-dir com.nedrichards.octopusagile.json
    ```

3.  **Install the Flatpak:**
    ```bash
    flatpak-builder --user --install build-dir com.nedrichards.octopusagile.json
    ```

4.  **Run the application:**
    ```bash
    flatpak run com.nedrichards.octopusagile
    ```

## Usage

Upon first launch, the application will attempt to auto-detect your region and tariff. It is recommended to open the Preferences window (accessible from the menu button in the header bar) to explicitly select your region and specific Agile tariff code if auto-detection is incorrect or if you encounter issues.

### Configuration

To change your region or tariff:
1.  Click the menu button (usually three dots or lines) in the top-right corner of the application window.
2.  Select **Preferences**.
3.  Choose your desired region and tariff from the dropdown menus.

The application will automatically refresh the price data when settings are changed.

## License

This project is licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).

---

Co-authored with [Gemini](https://github.com/google-gemini/gemini-cli).
