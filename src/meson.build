pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'octopusagile'
localedir = get_option('prefix') / get_option('localedir')
gnome = import('gnome')
python = import('python')

py_install = python.find_installation('python3')

conf = configuration_data()
conf.set('PYTHON', py_install.path())
conf.set('VERSION', meson.project_version())
conf.set('pkgdatadir', pkgdatadir)
conf.set('localedir', localedir)

configure_file(
  input: 'octopusagile.in',
  output: 'com.nedrichards.octopusagile',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir')
)

gnome.compile_resources('octopusagile',
  'octopusagile.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

install_data(
  [
    '__init__.py',
    'main.py',
    'utils.py',
  ],
  install_dir: moduledir
)

install_data(
  [
    'ui/__init__.py',
    'ui/main_window.py',
    'ui/preferences_window.py',
    'ui/price_chart.py',
    'ui/styles.py',
    'ui/custom_spin_button.py',
  ],
  install_dir: moduledir / 'ui'
)

install_data(
  'gtk/help-overlay.ui',
  install_dir: moduledir / 'gtk'
)
