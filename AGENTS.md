# AGENTS.md

## Scope

This is the repository-level guide for coding agents. Keep it practical and
specific to this checkout; place narrower guidance in a nested `AGENTS.md` if a
subtree develops distinct requirements.

Read `README.md` before build, packaging, or runtime work. Inspect the current
working tree before editing, and preserve unrelated user changes.

## Project map

- `src/` contains the Python application. `main.py` starts the app;
  `ui/main_window.py` owns the main UI; `ui/price_chart.py` draws the forecast
  chart; pure pricing, time, formatting, usage, and presentation logic lives
  in the other modules.
- `data/` contains GSettings, desktop, D-Bus, AppStream, icons, and screenshots.
- `tests/` contains the Python unit suite and tariff fixtures.
- `com.nedrichards.octopusagile.Devel.json` builds the local checkout and runs
  Meson tests. Use it for development and verification.
- `com.nedrichards.octopusagile.json` is the production-style manifest. It
  builds a pinned Git commit and is only changed as part of an explicit release.

## Working conventions

- Make the smallest change that solves the requested problem and follow the
  surrounding Python and GTK/libadwaita style.
- Keep non-UI calculations in testable helpers. Add or update focused tests for
  changed price, date, time, or formatting behaviour.
- Electricity prices and usage are half-hourly. Do not change interval,
  timezone, day-boundary, or cheapest-window semantics without regression
  coverage for the relevant boundary case.
- Preserve adaptive layouts, keyboard access, accessible labels, and reduced
  motion behaviour when changing the UI or either chart.
- Treat API keys, account numbers, cached account data, and local settings as
  sensitive. Do not add them to fixtures, logs, screenshots, commits, or docs.
- Do not edit generated Flatpak output, `build/`, `build-dir/`, `repo/`, or
  `.flatpak-builder/`.

## Validation

Start with the narrowest relevant check, then run the full Python checks for a
normal source change:

```bash
python3 -m compileall -q src tests
python3 -m ruff check src tests
python3 -m pytest
```

The development Flatpak build is the authoritative environment for application,
GTK, schema, resource, packaging, or release changes:

```bash
./scripts/local-flatpak.sh
flatpak run com.nedrichards.octopusagile.Devel
```

For focused checks:

```bash
meson test -C build --print-errorlogs
glib-compile-schemas --strict --dry-run data
appstreamcli validate --no-net --explain data/com.nedrichards.octopusagile.metainfo.xml.in
```

Use a configured host `build/` directory only for host Meson checks. The
development Flatpak build has `run-tests` enabled; do not treat a host-only test
run as proof of a packaging or GTK change.

## Packaging and releases

- Do not create a release, tag, or update release metadata unless explicitly
  requested.
- A release updates the version in `meson.build`, the About dialog in
  `src/ui/main_window.py`, and the new release entry in
  `data/com.nedrichards.octopusagile.metainfo.xml.in`.
- Tag the release commit before changing the production manifest. Then set the
  `commit` in `com.nedrichards.octopusagile.json` to the exact tag commit.
- Validate the development build for source changes and the production manifest
  for a release-style package build.

## Git and handoff

- Review `git status` and the diff before staging. Stage explicit paths; never
  fold unrelated changes into a commit.
- Use concise, behaviour-based commits. Commit, push, open a pull request,
  tag, or publish only when the user asks for that action.
- Report the files changed, validation actually run, and any remaining
  environment-dependent verification.

## Code Review Rules

Flag changes that:

- alter half-hour pricing, date/time boundaries, tariff matching, or cheapest
  window behaviour without a boundary-focused test;
- degrade keyboard navigation, screen-reader labels, adaptive layout, or
  reduced-motion handling;
- put secrets, account data, or generated output under version control;
- change the production manifest pin outside an explicit release; or
- claim Flatpak or UI verification when only host-side checks were run.

## Local Flatpak build storage

Use `./scripts/local-flatpak.sh` (defaults to development) for local checkout
builds and updates. Use `./scripts/local-flatpak.sh production` only when the
production manifest is intended. See `docs/local-flatpak.md`.
Use the normal manifests and keep their test gates enabled.

- Keep the durable update repository at `flatpak-repo/`. Never place it under
  `.flatpak-builder/` or another disposable build/cache directory.
- Use `.flatpak-builder/` for Builder state and `.flatpak-builder/staging` as
  the single staging location for both profiles. Build sequentially. Do not
  create per-task, per-validation or timestamped build/state/repository trees.
- Use `--delete-build-dirs` and clean module working directories and staging
  after success, failure and ordinary interruption, as the script does. Keep
  the reusable cache and downloads. Do not use `--keep-build-dirs` for routine
  automated builds. Debug retention needs an explicit task-specific reason
  and cleanup when finished.
- Do not run GNOME Builder or raw Builder commands concurrently with the
  script. Interactive GNOME Builder development remains supported via the
  `.Devel` manifest; prefer the script for automated validation and deployment.
- Keep directory-source `skip` lists excluding generated build directories,
  `target`, `.flatpak-builder*` and `flatpak-repo`, so artifacts are not copied
  into subsequent builds.
- Verify the installed app and its update origin after deployment. Never
  re-export an installed `export/` directory.

There is no enforced storage budget. Do not change Rust incremental/debug
settings as part of storage housekeeping without a separate request.
