# Agent Codebase Summary: octopus-agile-energy

This document provides a summary of the octopus-agile-energy codebase to assist with future development and maintenance.

## Project Overview

This is a GNOME application for UK Octopus Energy customers. It displays current and forecast electricity prices, supports multiple Octopus tariffs, highlights the current price, and can calculate the cheapest time window. The application uses the Octopus Energy API to fetch price data.

## Key Features

*   **Adaptive Price Chart:** Displays upcoming Octopus electricity prices with adaptive horizontal grid lines, price labels, and a wider forecast horizon on larger windows.
*   **Visual Enhancements:** Features a day transition indicator for "Tomorrow" and a three-sided highlight for the current price slot to maintain a clean baseline.
*   **Find Cheapest Time:** A feature to find the cheapest time to use electricity based on a given duration and time window.
*   **Tariff Support:** Supports Agile, Go, and Intelligent Octopus Go tariffs with an adaptive preferences window.
*   **Average Price Calculation:** Displays average prices for selected periods.

## Accessibility

We are committed to providing good accessibility for all users. The application includes the following keyboard shortcuts:

*   **`<Primary>q`**: Quit the application.
*   **`<Primary>comma`**: Open the preferences window.
*   **`<Primary>r`**: Refresh the price data.
*   **`<Primary>f`**: Open the "Find Cheapest Time" feature and focus the duration input.

## Technologies Used

*   **Language:** Python
*   **UI Framework:** GTK4 with LibAdwaita (Targeting GNOME 50)
*   **Build System:** Meson
*   **Packaging:** Flatpak

## Project Structure

*   `src/`: Contains the main application source code.
    *   `main.py`: The main entry point of the application.
    *   `ui/`: Contains the UI-related files.
        *   `main_window.py`: The main application window.
        *   `price_chart.py`: A custom widget for displaying the price chart.
        *   `preferences_window.py`: The preferences window.
        *   `styles.py`: CSS styles for the application.
    *   `utils.py`: Contains utility functions, such as the `CacheManager`.
*   `data/`: Contains the application's data files, such as the desktop entry, icons, and GSettings schema.
*   `po/`: Contains the localization files.
*   `meson.build`: The build configuration file.
*   `com.nedrichards.octopusagile.Devel.json`: The local development Flatpak manifest. This builds from the checkout and runs tests inside the GNOME SDK.
*   `com.nedrichards.octopusagile.json`: The production-style Flatpak manifest. This builds from a pinned upstream Git commit.

## Key Files

*   `src/ui/main_window.py`: This is the main application window. It is responsible for the overall layout of the application, and it contains the logic for fetching the price data from the Octopus Energy API.
*   `src/ui/price_chart.py`: This is a custom GTK widget that draws the price chart. It uses the Cairo graphics library to draw the chart.
*   `src/ui/styles.py`: This file contains the CSS styles for the application. It is used to style the widgets in the application.
*   `meson.build`: This is the build configuration file for the project. It specifies how the application is built and installed.
*   `com.nedrichards.octopusagile.Devel.json`: This is the primary manifest for active development and agent verification.
*   `com.nedrichards.octopusagile.json`: This is the pinned production-style manifest used for release-style packaging.

## How to Build, Test, and Run

The authoritative development loop uses the local development Flatpak manifest. It builds from the checkout and runs the Meson test suite inside the GNOME SDK sandbox:

```bash
flatpak-builder --user --install --force-clean build-dir com.nedrichards.octopusagile.Devel.json
flatpak run com.nedrichards.octopusagile.Devel
```

The `octopusagile` module in `com.nedrichards.octopusagile.Devel.json` has `run-tests` enabled, so the Flatpak build fails if `meson test` fails in the SDK environment.

If `rofiles-fuse` fails in the agent environment, rerun the build with Flatpak Builder's fallback flag:

```bash
flatpak-builder --disable-rofiles-fuse --user --install --force-clean build-dir com.nedrichards.octopusagile.Devel.json
```

For an interactive debug shell in the built sandbox:

```bash
flatpak-builder --run build-dir com.nedrichards.octopusagile.Devel.json sh
meson test -C /run/build/octopusagile/_flatpak_build --print-errorlogs
G_MESSAGES_DEBUG=all com.nedrichards.octopusagile
```

For installed-app logs and first-run settings debugging:

```bash
journalctl --user -f
flatpak run com.nedrichards.octopusagile.Devel
flatpak run --command=sh com.nedrichards.octopusagile.Devel
gsettings reset-recursively com.nedrichards.octopusagile
```

Host-side checks are optional fast paths for pure Python changes:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
python3 -m ruff check src tests
```

Use `build` for host Meson checks and `build-dir` for Flatpak Builder output.

## Dependencies

The application has the following dependencies:

*   Python 3
*   GTK4
*   LibAdwaita
*   requests
*   pycairo
*   PyGObject

## Development Environment

Agents should prefer the Flatpak development manifest for build and test verification because it provides the GNOME SDK environment used by the application. Use host-side pytest or Ruff only as a faster supplemental check for logic-only changes.

## AI Assistance

Development of this project has been assisted by a variety of AI coding tools.

## Flathub Releases

The following files need to be updated for each new release:

*   `data/com.nedrichards.octopusagile.metainfo.xml.in`:
    *   `<release version="..." date="..."/>`: This field should be updated with the new version number and release date.
    *   `<description>`: The description should be updated to reflect any changes in the new release.
*   `meson.build`:
    *   The `version` field should be updated to match the new version number.
*   `com.nedrichards.octopusagile.json`:
    *   The `commit` field should be updated to the latest commit hash.
*   `src/ui/main_window.py`:
    *   The `version` field in the `AboutWindow` should be updated to match the new version number.
