import gi
gi.require_version('Secret', '1')
from gi.repository import Secret, GLib
import logging

logger = logging.getLogger(__name__)

# Define the schema for our API key
# The org.freedesktop.Secret.Generic schema is standard for simple passwords/keys
SECRET_SCHEMA = Secret.Schema.new("org.freedesktop.Secret.Generic",
    Secret.SchemaFlags.NONE,
    {
        "application": Secret.SchemaAttributeType.STRING,
    }
)

SECRET_ATTRIBUTES = {
    "application": "com.nedrichards.octopusagile"
}

def store_api_key(api_key: str) -> bool:
    """
    Securely stores the Octopus Energy API key in the system keyring.
    """
    try:
        Secret.password_store_sync(
            SECRET_SCHEMA,
            SECRET_ATTRIBUTES,
            Secret.COLLECTION_DEFAULT,
            "Octopus Energy API Key",
            api_key,
            None
        )
        logger.info("Successfully stored API key in secret service")
        return True
    except GLib.Error as e:
        logger.error(f"Failed to store API key in secret service: {e}")
        return False

def get_api_key() -> str | None:
    """
    Retrieves the Octopus Energy API key from the system keyring.
    """
    try:
        password = Secret.password_lookup_sync(
            SECRET_SCHEMA,
            SECRET_ATTRIBUTES,
            None
        )
        return password
    except GLib.Error as e:
        logger.error(f"Failed to lookup API key from secret service: {e}")
        return None

def clear_api_key() -> bool:
    """
    Removes the Octopus Energy API key from the system keyring.
    """
    try:
        Secret.password_clear_sync(
            SECRET_SCHEMA,
            SECRET_ATTRIBUTES,
            None
        )
        logger.info("Successfully cleared API key from secret service")
        return True
    except GLib.Error as e:
        logger.error(f"Failed to clear API key from secret service: {e}")
        return False
