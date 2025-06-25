# Octopus Agile Energy

This is a simple application for GNOME built to track and visualise Octopus Energy's Agile electricity prices in real-time. It fetches current and forecasted half-hourly prices, allowing users to quickly see the best times to use electricity. This is only relevant if you are based in the UK.

* Current Price Display: Shows the real-time Agile electricity price (pence/kWh).
* Price Level Indicators: Visually indicates whether the current price is low, medium, high, or even negative.
* 24-Hour Price Forecast Chart: Displays a bar chart of the next 24 hours of half-hourly price data, helping users plan their energy consumption.
* Region and Tariff Selection: Allows users to select their specific Octopus Energy region and Agile tariff code through a preferences window.

![The application interface, showing the current price and a graph of future prices](/data/octopus-agile-screenshot.png?raw=true "Application screenshot")

## Installation

This application can be easily built and run using Flatpak and Flatpak Builder or directly through GNOME Builder.

Prerequisites

Ensure you have Flatpak and Flatpak Builder installed on your system. Refer to the official Flatpak documentation for installation instructions specific to your distribution.

### Using GNOME Builder

GNOME Builder is the recommended way to work with this project. It provides a convenient development environment that handles Flatpak integration automatically.

    Open GNOME Builder: Launch GNOME Builder on your system.
    Clone the Project:
        Go to "Clone Repository".
        Enter the repository URL (https://github.com/nedrichards/octopus-agile-energy.git).
        Choose a destination folder and click "Clone".
    Build and Run:
        Once the project is loaded, GNOME Builder will detect the com.nedrichards.octopusagile.json manifest.
        Click the "Run" button (usually a play icon) in the top bar. Builder will automatically build the Flatpak application and run it.

### Building with Flatpak Builder (CLI)

If you prefer to build the Flatpak from the command line, follow these steps:

    Clone the repository (or download the project files):

    git clone https://github.com/nedrichards/octopus-agile-energy.git
    cd octopus-agile-energy

Build the Flatpak:

    flatpak-builder --force-clean build-dir com.nedrichards.octopusagile.json

This command will build the application and its dependencies into the build-dir directory.

Install the Flatpak:

    flatpak-builder --user --install build-dir com.nedrichards.octopusagile.json

This command installs the built Flatpak application for the current user.

Run the application:

    flatpak run com.nedrichards.octopusagile

## Usage

Upon first launch, the application will attempt to auto-detect your region and tariff. It is recommended to open the Preferences window (accessible from the menu button in the header bar) to explicitly select your region and specific Agile tariff code if auto-detection is incorrect or if you encounter issues.
Configuration

To change your region or tariff:

    Click the menu button (usually three dots or lines) in the top-right corner of the application window.
    Select "Preferences".
    Choose your desired region and tariff from the dropdown menus.

The application will automatically refresh the price data when settings are changed.

## License

This project is licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
