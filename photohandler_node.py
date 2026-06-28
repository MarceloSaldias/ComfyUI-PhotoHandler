"""ComfyUI node that fetches an image description from PhotoHandler.

The node calls PhotoHandler's local HTTP agent API to look up the description
stored for a given absolute image path. Only the Python standard library is
used so the node has no extra dependencies.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:17843"


def _base_url():
    """Return the PhotoHandler base URL, honoring PHOTOHANDLER_URL."""
    return os.environ.get("PHOTOHANDLER_URL", DEFAULT_BASE_URL).rstrip("/")


class PhotoHandlerDescription:
    """Fetch the stored description for an image from PhotoHandler."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "path": ("STRING", {"default": "", "multiline": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("description",)
    FUNCTION = "get_description"
    CATEGORY = "PhotoHandler"

    def get_description(self, path):
        query = urllib.parse.urlencode({"path": path})
        url = "{base}/api/assets/by-path/description?{query}".format(
            base=_base_url(), query=query
        )

        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.getcode()
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # 404 means the asset (or its description) is not known to
            # PhotoHandler. That is a normal outcome, not an error.
            if exc.code == 404:
                return ("",)
            raise RuntimeError(
                "PhotoHandler returned HTTP {code} for {url}: {reason}".format(
                    code=exc.code, url=url, reason=exc.reason
                )
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Could not reach PhotoHandler at {base}. Is it running? "
                "({reason})".format(base=_base_url(), reason=exc.reason)
            ) from exc

        if status != 200:
            raise RuntimeError(
                "PhotoHandler returned unexpected HTTP {code} for {url}".format(
                    code=status, url=url
                )
            )

        description = self._extract_description(body)
        return (description,)

    @staticmethod
    def _extract_description(body):
        """Pull the description out of the API response.

        The API may return a bare JSON string, a JSON object with a
        "description" field, or plain text. A missing or null description is
        treated as an empty string (a normal "not found" result).
        """
        body = body.strip()
        if not body:
            return ""

        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            # Not JSON — treat the raw body as the description text.
            return body

        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            value = data.get("description")
            return value if isinstance(value, str) else ""
        return ""
