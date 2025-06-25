pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'octopusagile'
gnome = import('gnome')

gnome.compile_resources('octopusagile',
  'octopusagile.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)
