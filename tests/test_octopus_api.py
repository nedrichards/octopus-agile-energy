import unittest
from unittest.mock import Mock, patch

from src.octopus_api import OctopusApiError, get_json


class OctopusApiTests(unittest.TestCase):
    @patch("src.octopus_api.requests.get")
    @patch("src.octopus_api.get_api_key", return_value="secret-key")
    def test_authenticated_requests_reject_untrusted_pagination_hosts(self, _get_api_key, request_get):
        with self.assertRaisesRegex(OctopusApiError, "untrusted API URL"):
            get_json("https://example.test/page-2", use_api_key=True)

        request_get.assert_not_called()

    @patch("src.octopus_api.requests.get")
    @patch("src.octopus_api.get_api_key", return_value="secret-key")
    def test_authenticated_requests_accept_the_octopus_api_origin(self, _get_api_key, request_get):
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"results": []}
        request_get.return_value = response

        self.assertEqual(
            get_json("https://api.octopus.energy/v1/products/", use_api_key=True),
            {"results": []},
        )

    @patch("src.octopus_api.requests.get")
    def test_invalid_json_is_reported_as_an_api_error(self, request_get):
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("bad json")
        request_get.return_value = response

        with self.assertRaisesRegex(OctopusApiError, "invalid JSON"):
            get_json("https://api.octopus.energy/v1/products/")

    @patch("src.octopus_api.requests.get")
    def test_http_error_logs_do_not_include_sensitive_url_paths(self, request_get):
        response = Mock(status_code=404)
        response.raise_for_status.side_effect = __import__("requests").exceptions.HTTPError()
        response.json.return_value = {"detail": "Not found"}
        request_get.return_value = response
        sensitive_url = "https://api.octopus.energy/v1/accounts/A-SECRET/"

        with self.assertLogs("src.octopus_api", level="ERROR") as logs, self.assertRaises(OctopusApiError):
            get_json(sensitive_url)

        self.assertNotIn("A-SECRET", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
