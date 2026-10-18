#!/usr/bin/env bash
# Build and install from the normal manifest, retaining only reusable Builder state.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
case "${1:-development}" in
  production) manifest=com.nedrichards.octopusagile.json; app=com.nedrichards.octopusagile; remote=octopusagile-origin ;;
  development) manifest=com.nedrichards.octopusagile.Devel.json; app=com.nedrichards.octopusagile.Devel; remote=devel1-origin ;;
  -h|--help) echo "Usage: $0 [production|development]"; exit 0 ;;
  *) echo "Usage: $0 [production|development]" >&2; exit 2 ;;
esac
if (( $# > 1 )); then
  echo "Usage: $0 [production|development]" >&2
  exit 2
fi
state="$root/.flatpak-builder"
staging="$state/staging"
repo="$root/flatpak-repo"
mkdir -p "$state"
exec 9>"$state/local-build.lock"
flock -n 9 || { echo "Another local Flatpak build is running in $root" >&2; exit 1; }
# Builder removes module directories normally; also clean interrupted builds and
# staging on exit. Keep downloads, cache, logs and the separate export repository.
cleanup() {
  local status=$?
  trap - EXIT
  rm -rf -- "$state/build" "$staging" || { (( status != 0 )) || status=1; }
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
flatpak-builder --user --disable-rofiles-fuse --force-clean \
  --delete-build-dirs --install-deps-from=flathub --default-branch=master \
  --state-dir="$state" --repo="$repo" "$staging" "$manifest" \
  > >(tee "$state/local-build.log") 2>&1
# Only change the update source after the build, tests and export succeed.
flatpak remote-add --user --if-not-exists --no-gpg-verify "$remote" "$repo"
flatpak remote-modify --user --no-gpg-verify --url="file://$repo" "$remote"
flatpak install --user --noninteractive --or-update "$remote" "$app//master"
echo "Installed $app from $repo. Quit and reopen the app to use this build."
