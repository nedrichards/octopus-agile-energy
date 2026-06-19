import logging
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from .secrets_manager import get_api_key

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10


class OctopusApiError(Exception):
    """Raised when the tariff API returns an error response."""


def _build_auth(use_api_key: bool):
    if not use_api_key:
        return None

    api_key = get_api_key()
    if not api_key:
        raise OctopusApiError("Missing API key.")

    return HTTPBasicAuth(api_key, "")


def get_json(url: str, *, use_api_key: bool = False, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """
    Fetches JSON data from a tariff API endpoint.

    Raises:
        OctopusApiError: If authentication is missing or response is not successful.
        requests.exceptions.RequestException: For network-level failures.
    """
    auth = _build_auth(use_api_key)
    response = requests.get(url, timeout=timeout, auth=auth)

    if response.status_code == 401:
        logger.warning("Octopus API authentication failed for URL: %s", url)
        raise OctopusApiError("Authentication failed for the API.")

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        logger.error("Octopus API HTTP error for URL %s: status=%s", url, response.status_code)
        detail = _extract_error_detail(response)
        message = f"API request failed with status {response.status_code}."
        if detail:
            message = f"{message} {detail}"
        raise OctopusApiError(message) from exc

    return response.json()


def _extract_error_detail(response):
    try:
        payload = response.json()
    except ValueError:
        return ""

    detail = payload.get("detail")
    return detail if isinstance(detail, str) else ""
