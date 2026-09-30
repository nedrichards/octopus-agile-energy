python = import('python')
py_install = python.find_installation('python3')

test(
  'unit-tests',
  py_install,
  args: ['-m', 'unittest', 'discover', '-s', meson.current_source_dir()],
  env: [
    'PYTHONPATH=' + meson.project_source_root() / 'src',
  ],
)

# This is a required gate in the GNOME SDK, where Broadway is bundled.
if find_program('gtk4-broadwayd', required: false).found()
  test(
    'gtk-startup',
    find_program('dbus-run-session'),
    args: [py_install.full_path(), meson.current_source_dir() / 'smoke_startup.py',
           meson.project_build_root() / 'src/octopusagile.gresource'],
    timeout: 30,
  )
elif get_option('prefix') == '/app'
  error('The Flatpak SDK must provide gtk4-broadwayd for the GTK startup gate')
endif
