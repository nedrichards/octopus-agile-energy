import os

DEFAULT_APPLICATION_ID = "com.nedrichards.octopusagile"
DEVELOPMENT_APPLICATION_ID_SUFFIX = ".Devel"


def get_application_id(environ=None):
    """Return the application ID assigned by Flatpak, or the production ID."""
    environment = os.environ if environ is None else environ
    return environment.get("FLATPAK_ID") or DEFAULT_APPLICATION_ID


def is_development_build(environ=None):
    """Return whether the current application ID is a development build."""
    return get_application_id(environ).endswith(DEVELOPMENT_APPLICATION_ID_SUFFIX)
