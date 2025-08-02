# Gemini Codebase Summary: octopus-agile-energy

This document provides a summary of the octopus-agile-energy codebase to assist with future development and maintenance.

## Project Overview

This is a GTK desktop application that displays Octopus Agile electricity prices. It provides a chart showing the price for the next 48 hours, and it highlights the current price. The application uses the Octopus Energy API to fetch the price data.

## Technologies Used

*   **Language:** Python
*   **UI Framework:** GTK4 with LibAdwaita
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
*   `com.nedrichards.octopusagile.json`: The Flatpak manifest file.

## Key Files

*   `src/ui/main_window.py`: This is the main application window. It is responsible for the overall layout of the application, and it contains the logic for fetching the price data from the Octopus Energy API.
*   `src/ui/price_chart.py`: This is a custom GTK widget that draws the price chart. It uses the Cairo graphics library to draw the chart.
*   `src/ui/styles.py`: This file contains the CSS styles for the application. It is used to style the widgets in the application.
*   `meson.build`: This is the build configuration file for the project. It specifies how the application is built and installed.
*   `com.nedrichards.octopusagile.json`: This is the Flatpak manifest file. It is used to build the Flatpak bundle for the application.

## How to Build and Run

The application is built and run using Flatpak. The following commands can be used to build and run the application:

```bash
flatpak-builder --force-clean build-dir com.nedrichards.octopusagile.json
flatpak-builder --run build-dir com.nedrichards.octopusagile.json octopusagile
```

## Dependencies

The application has the following dependencies:

*   Python 3
*   GTK4
*   LibAdwaita
*   requests
*   pycairo
*   PyGObject

## Development Environment

I am running in a containerized environment and do not have access to a graphical user interface. Therefore, I am unable to build or test the application myself. The user is responsible for building and testing the application, and for providing debug information or screenshots as required.

## Flathub Releases

The following files need to be updated for each new release:

*   `data/com.nedrichards.octopusagile.metainfo.xml.in`:
    *   `<release version="..." date="..."/>`: This field should be updated with the new version number and release date.
    *   `<description>`: The description should be updated to reflect any changes in the new release.
*   `meson.build`:
    *   The `version` field should be updated to match the new version number.
*   `com.nedrichards.octopusagile.json`:
    *   The `commit` field should be updated to the latest commit hash.
