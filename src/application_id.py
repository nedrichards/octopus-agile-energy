import os

DEFAULT_APPLICATION_ID = "com.nedrichards.octopusagile"


def get_application_id(environ=None):
    """Return the application ID assigned by Flatpak, or the production ID."""
    environment = os.environ if environ is None else environ
    return environment.get("FLATPAK_ID") or DEFAULT_APPLICATION_ID
