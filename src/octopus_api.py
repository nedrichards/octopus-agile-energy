import logging
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.auth import HTTPBasicAuth

from .secrets_manager import get_api_key

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10
OCTOPUS_API_HOST = "api.octopus.energy"


class OctopusApiError(Exception):
    """Raised when the tariff API returns an error response."""


def _validate_authenticated_url(url: str) -> None:
    """Prevent API credentials being sent to an API-supplied pagination host."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (AttributeError, TypeError, ValueError) as exc:
        raise OctopusApiError("Refusing to send account credentials to an invalid API URL.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != OCTOPUS_API_HOST
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OctopusApiError("Refusing to send account credentials to an untrusted API URL.")


def _build_auth(use_api_key: bool):
    if not use_api_key:
        return None

    api_key = get_api_key()
    if not api_key:
        raise OctopusApiError("Missing API key.")

    return HTTPBasicAuth(api_key, "")


def get_json(
    url: str,
    *,
    use_api_key: bool = False,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """
    Fetches JSON data from a tariff API endpoint.

    Raises:
        OctopusApiError: If authentication is missing or response is not successful.
        requests.exceptions.RequestException: For network-level failures.
    """
    if use_api_key:
        _validate_authenticated_url(url)

    auth = _build_auth(use_api_key)
    request_client = session or requests
    response = request_client.get(url, timeout=timeout, auth=auth)

    if response.status_code == 401:
        logger.warning("Octopus API authentication failed")
        raise OctopusApiError("Authentication failed for the API.")

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        logger.error("Octopus API HTTP error: status=%s", response.status_code)
        detail = _extract_error_detail(response)
        message = f"API request failed with status {response.status_code}."
        if detail:
            message = f"{message} {detail}"
        raise OctopusApiError(message) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise OctopusApiError("The API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise OctopusApiError("The API returned an unexpected response shape.")
    return payload


def _extract_error_detail(response):
    try:
        payload = response.json()
    except ValueError:
        return ""

    if not isinstance(payload, dict):
        return ""
    detail = payload.get("detail")
    return detail if isinstance(detail, str) else ""
