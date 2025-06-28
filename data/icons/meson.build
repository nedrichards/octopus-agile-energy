application_id = 'com.nedrichards.octopusagile'

foreach size : ['16x16', '24x24', '32x32', '48x48', '64x64', '128x128', '256x256', '512x512']
  basedir = 'hicolor' / size / 'apps'
  install_data(
    basedir / ('@0@.png').format(application_id),
    install_dir: get_option('datadir') / 'icons' / basedir
  )
endforeach

scalable_dir = 'hicolor' / 'scalable' / 'apps'
install_data(
  scalable_dir / ('@0@.svg').format(application_id),
  install_dir: get_option('datadir') / 'icons' / scalable_dir
)

symbolic_dir = 'hicolor' / 'symbolic' / 'apps'
install_data(
  symbolic_dir / ('@0@-symbolic.svg').format(application_id),
  install_dir: get_option('datadir') / 'icons' / symbolic_dir
)
