  for size in 16 24 32 48 64 128 256 512; do
    out="hicolor/${size}x${size}/apps/com.nedrichards.octopusagile.png"
    flatpak run org.inkscape.Inkscape \
      "hicolor/scalable/apps/com.nedrichards.octopusagile.svg" \
      --export-type=png \
      --export-width="$size" \
      --export-height="$size" \
      --export-filename="$out"
  done
