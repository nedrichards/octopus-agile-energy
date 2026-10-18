# Local Flatpak builds and updates

From the checkout root:

```sh
./scripts/local-flatpak.sh
```

The default is `development`: build the local checkout with `com.nedrichards.octopusagile.Devel.json`,
run the manifest's existing checks, export and install `com.nedrichards.octopusagile.Devel`.
Quit and reopen the app after updating. Application data is preserved.
The production profile is explicit:

```sh
./scripts/local-flatpak.sh production
```

Production uses `com.nedrichards.octopusagile.json` exactly as written.
It builds the pinned upstream source, rather than uncommitted local changes.
Do not repin it for ordinary development or storage maintenance.

Both profiles share `.flatpak-builder/staging` and `.flatpak-builder/` for
Builder state. A checkout lock prevents overlapping script runs. Do not run
GNOME Builder or raw Builder commands in this checkout at the same time.
The script uses `--force-clean --delete-build-dirs` and an exit trap to remove
module working directories and staging after success, failure or an ordinary
interrupt. SIGKILL and power loss can leave working files; the next run uses
the same paths and cleans them on exit. Downloads and reusable Builder cache
remain. The latest build log is `.flatpak-builder/local-build.log`.

`flatpak-repo/` is the durable update repository. Keep it when cleaning Builder
state; source-directory copies explicitly exclude it and generated artifacts.
Production uses remote `octopusagile-origin`; development uses `devel1-origin`.
The script configures the selected remote only after a successful export.
Existing installed app, locale and debug commits have been preserved when
moving cache-backed remotes to this repository. Historical experiment refs
are preserved as snapshots; they do not acquire new builds automatically.

For installed-app diagnostics, use
`flatpak run --user --command=sh com.nedrichards.octopusagile.Devel` or the app's own test options. Staging is deliberately
removed. Never re-export installed desktop files: let the normal
manifest-driven build finish and export its own staging tree.

GNOME Builder's managed storage is unchanged. There is no enforced storage
budget and no change to compilation profiles. Use the canonical script for
automated builds; do not create additional per-task validation trees.
