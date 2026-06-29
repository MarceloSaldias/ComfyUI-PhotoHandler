"""ComfyUI nodes that fetch image descriptions from PhotoHandler.

Two nodes are provided, both backed by PhotoHandler's local HTTP agent (the
hybrid local-agent server, http://127.0.0.1:17843 by default):

  * ``PhotoHandlerDescription`` — look up by **absolute path** (the image must
    live inside PhotoHandler's open library).
  * ``PhotoHandlerDescriptionByImage`` — look up by **SHA-256 of the file**.
    Useful when the path is not PhotoHandler's library path (e.g. an image
    dragged into ComfyUI, which is copied verbatim into ``input/``). The bytes
    are identical, so the hash matches PhotoHandler's stored ``file_hash``.

Both report the single selected ``description`` plus the full ``descriptions``
map of named typed descriptions. Only the Python standard library is used.
"""

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:17843"

# Server-side error messages (from PhotoHandler's `ensure_readable` / library
# checks) that mean "this image is simply not something PhotoHandler can
# describe" rather than a real failure. PhotoHandler maps every error to HTTP
# 500, so we disambiguate on the message text and treat these as a normal
# empty result.
_BENIGN_ERROR_FRAGMENTS = (
    "outside the library",
    "no library is open",
)


def _base_url():
    """Return the PhotoHandler base URL, honoring PHOTOHANDLER_URL."""
    return os.environ.get("PHOTOHANDLER_URL", DEFAULT_BASE_URL).rstrip("/")


def _fetch_description(lookup, params):
    """GET a description from PhotoHandler and return (description, json_map).

    ``lookup`` is the route segment, ``"by-path"`` or ``"by-hash"``. ``params``
    is the query dict (e.g. ``{"path": ...}`` or ``{"hash": ...}``, plus an
    optional ``"type"``).

    Returns a 2-tuple ``(description, descriptions_json)``. A missing asset or
    an out-of-scope path yields ``("", "{}")`` — a normal result, not an error.
    Raises ``RuntimeError`` when PhotoHandler is unreachable or returns a
    genuine error.
    """
    query = urllib.parse.urlencode(params)
    url = "{base}/api/assets/{lookup}/description?{query}".format(
        base=_base_url(), lookup=lookup, query=query
    )

    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return _handle_http_error(exc, url)
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

    return _parse_success(body)


def _handle_http_error(exc, url):
    """Decide whether an HTTP error is a normal empty result or a failure.

    PhotoHandler reports a path outside the open library (or no library open)
    as HTTP 500 with ``{"error": "..."}``. Those are normal "not in scope"
    outcomes, so we return an empty result. Anything else (missing/unreadable
    path, DB failure, unknown route) is a genuine error.
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


def _sha256_file(path):
    """Return the SHA-256 hexdigest of a file's bytes.

    Matches PhotoHandler's scanner (``python/operations/scanner.py``), which
    hashes the full file in chunks.
    """
    sha256 = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _resolve_image_path(image):
    """Resolve a ComfyUI image-widget value to an on-disk path.

    Inside ComfyUI, ``image`` is a filename in the input directory; we resolve
    it via ``folder_paths``. Outside ComfyUI (e.g. tests), ``image`` is treated
    as a direct filesystem path.
    """
    try:
        import folder_paths

        return folder_paths.get_annotated_filepath(image)
    except Exception:  # noqa: BLE001 - folder_paths only exists inside ComfyUI
        return image


def _load_image_tensor(path):
    """Load an image file into ComfyUI's (IMAGE, MASK) tensors.

    Replicates the core of ComfyUI's built-in ``LoadImage`` (EXIF transpose,
    multi-frame handling, alpha -> mask). ``torch`` / ``numpy`` / ``PIL`` are
    imported lazily — they are always present inside ComfyUI but not required
    just to import this module or to do a description-only lookup.
    """
    import numpy as np
    import torch
    from PIL import Image, ImageOps, ImageSequence

    try:
        import node_helpers  # ComfyUI helper; tolerates odd image files

        def _pillow(fn, *args):
            return node_helpers.pillow(fn, *args)
    except Exception:  # noqa: BLE001 - not running inside ComfyUI
        def _pillow(fn, *args):
            return fn(*args)

    img = _pillow(Image.open, path)

    output_images = []
    output_masks = []
    width, height = None, None
    excluded_formats = ["MPO"]

    for frame in ImageSequence.Iterator(img):
        frame = _pillow(ImageOps.exif_transpose, frame)

        if frame.mode == "I":
            frame = frame.point(lambda px: px * (1 / 255))
        rgb = frame.convert("RGB")

        if len(output_images) == 0:
            width, height = rgb.size
        if rgb.size != (width, height):
            continue

        arr = np.array(rgb).astype(np.float32) / 255.0
        output_images.append(torch.from_numpy(arr)[None,])

        if "A" in frame.getbands():
            mask = np.array(frame.getchannel("A")).astype(np.float32) / 255.0
            mask = 1.0 - torch.from_numpy(mask)
        elif frame.mode == "P" and "transparency" in frame.info:
            alpha = frame.convert("RGBA").getchannel("A")
            mask = np.array(alpha).astype(np.float32) / 255.0
            mask = 1.0 - torch.from_numpy(mask)
        else:
            mask = torch.zeros((64, 64), dtype=torch.float32, device="cpu")
        output_masks.append(mask.unsqueeze(0))

    if len(output_images) > 1 and img.format not in excluded_formats:
        image = torch.cat(output_images, dim=0)
        mask = torch.cat(output_masks, dim=0)
    else:
        image = output_images[0]
        mask = output_masks[0]

    return (image, mask)


def _optional_description_type():
    return {"description_type": ("STRING", {"default": "", "multiline": False})}


class PhotoHandlerDescription:
    """Fetch an image's description from PhotoHandler, by absolute path."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "path": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": _optional_description_type(),
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("description", "descriptions_json")
    FUNCTION = "get_description"
    CATEGORY = "PhotoHandler"

    def get_description(self, path, description_type=""):
        params = {"path": path}
        if description_type:
            params["type"] = description_type
        return _fetch_description("by-path", params)


class PhotoHandlerDescriptionByImage:
    """Fetch an image's description from PhotoHandler, by SHA-256 of the file.

    Takes a ComfyUI image input (upload widget). The file's bytes are hashed
    and looked up against PhotoHandler's stored ``file_hash`` — so it works even
    when ComfyUI has copied the image to its own ``input/`` directory and the
    original library path is unavailable.
    """

    @classmethod
    def INPUT_TYPES(cls):
        image_input = ("STRING", {"default": "", "multiline": False})
        try:
            import folder_paths

            input_dir = folder_paths.get_input_directory()
            files = [
                f
                for f in os.listdir(input_dir)
                if os.path.isfile(os.path.join(input_dir, f))
            ]
            image_input = (sorted(files), {"image_upload": True})
        except Exception:  # noqa: BLE001 - only available inside ComfyUI
            pass

        return {
            "required": {"image": image_input},
            "optional": _optional_description_type(),
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING")
    RETURN_NAMES = ("image", "mask", "description", "descriptions_json")
    FUNCTION = "get_description"
    CATEGORY = "PhotoHandler"

    @classmethod
    def IS_CHANGED(cls, image, description_type=""):
        # Re-run when the file's bytes change (ComfyUI otherwise caches outputs
        # keyed on the unchanged filename).
        path = _resolve_image_path(image)
        try:
            return _sha256_file(path)
        except OSError:
            return float("nan")

    def get_description(self, image, description_type=""):
        path = _resolve_image_path(image)
        try:
            file_hash = _sha256_file(path)
        except OSError as exc:
            raise RuntimeError(
                "Could not read image file '{path}': {err}".format(
                    path=path, err=exc
                )
            ) from exc

        image_tensor, mask_tensor = _load_image_tensor(path)

        params = {"hash": file_hash}
        if description_type:
            params["type"] = description_type
        description, descriptions_json = _fetch_description("by-hash", params)

        return (image_tensor, mask_tensor, description, descriptions_json)
