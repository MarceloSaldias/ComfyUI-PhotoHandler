"""ComfyUI node that fetches an image description from PhotoHandler.

The node calls PhotoHandler's local HTTP agent API (the hybrid local-agent
server, http://127.0.0.1:17843 by default) to look up the description stored
for a given absolute image path. Only the Python standard library is used so
the node has no extra dependencies.

PhotoHandler exposes two description mechanisms:

  * the legacy single ``assets.description`` column, and
  * *typed* descriptions (e.g. "Clothing", "Scene") keyed to named
    ``description_types``.

The API response carries both: a single selected ``description`` (chosen by the
optional ``type`` query param, then the default type, then the legacy column)
and a ``descriptions`` map of every named type -> text.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:17843"

# Server-side error messages (from PhotoHandler's `ensure_readable`) that mean
# "this image is simply not something PhotoHandler can describe" rather than a
# real failure. PhotoHandler maps every error to HTTP 500, so we disambiguate
# on the message text. These are treated as a normal empty result.
_BENIGN_ERROR_FRAGMENTS = (
    "outside the library",
    "no library is open",
)


def _base_url():
    """Return the PhotoHandler base URL, honoring PHOTOHANDLER_URL."""
    return os.environ.get("PHOTOHANDLER_URL", DEFAULT_BASE_URL).rstrip("/")


class PhotoHandlerDescription:
    """Fetch the stored description(s) for an image from PhotoHandler."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "path": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                # Maps to the API's `?type=` param. Selects which named typed
                # description fills the single `description` output. Empty =>
                # PhotoHandler's default type, then the legacy column.
                "description_type": (
                    "STRING",
                    {"default": "", "multiline": False},
                ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("description", "descriptions_json")
    FUNCTION = "get_description"
    CATEGORY = "PhotoHandler"

    def get_description(self, path, description_type=""):
        params = {"path": path}
        if description_type:
            params["type"] = description_type
        query = urllib.parse.urlencode(params)
        url = "{base}/api/assets/by-path/description?{query}".format(
            base=_base_url(), query=query
        )

        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.getcode()
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return self._handle_http_error(exc, url)
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

        return self._parse_success(body)

    def _handle_http_error(self, exc, url):
        """Decide whether an HTTP error is a normal empty result or a failure.

        PhotoHandler reports a path outside the open library (or no library
        open) as HTTP 500 with ``{"error": "..."}``. Those are normal "not in
        scope" outcomes for an arbitrary path fed from ComfyUI, so we return an
        empty result. Anything else (missing/unreadable path, DB failure) is a
        genuine error.
        """
        message = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            if isinstance(payload, dict):
                message = str(payload.get("error", ""))
        except Exception:  # noqa: BLE001 - error body is best-effort only
            message = ""

        lowered = message.lower()
        if any(fragment in lowered for fragment in _BENIGN_ERROR_FRAGMENTS):
            return ("", "{}")

        detail = ": {}".format(message) if message else ""
        raise RuntimeError(
            "PhotoHandler returned HTTP {code} for {url}{detail}".format(
                code=exc.code, url=url, detail=detail
            )
        ) from exc

    @staticmethod
    def _parse_success(body):
        """Extract (description, descriptions_json) from a 200 response.

        The expected body is a JSON object::

            {"path": ..., "description": "<text>",
             "asset_id": <id|null>, "descriptions": {<type>: <text>, ...}}

        Older/simpler shapes (a bare JSON string, or plain text) are handled
        gracefully. A missing or null description is a normal empty result.
        """
        body = body.strip()
        if not body:
            return ("", "{}")

        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            # Not JSON — treat the raw body as the description text.
            return (body, "{}")

        if isinstance(data, str):
            return (data, "{}")

        if isinstance(data, dict):
            value = data.get("description")
            description = value if isinstance(value, str) else ""
            descriptions = data.get("descriptions")
            if not isinstance(descriptions, dict):
                descriptions = {}
            return (description, json.dumps(descriptions))

        return ("", "{}")
