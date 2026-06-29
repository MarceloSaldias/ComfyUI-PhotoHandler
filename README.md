# ComfyUI-PhotoHandler

A custom [ComfyUI](https://github.com/comfyanonymous/ComfyUI) node that fetches
image descriptions from [PhotoHandler](https://github.com/MarceloSaldias) via its
local HTTP agent API.

Two nodes are provided:

- **PhotoHandler Description** — takes an absolute image **path** and returns the
  description PhotoHandler stored for that image.
- **PhotoHandler Description (Image)** — takes an **image** (upload widget) and
  looks the description up by the file's **SHA-256**. Use this when ComfyUI
  doesn't have PhotoHandler's original path — e.g. an image dragged into ComfyUI
  is copied into `ComfyUI/input/`, so its path differs but its bytes (and hash)
  are identical to PhotoHandler's stored `file_hash`.

## Requirements

- A running **PhotoHandler** instance with its **local HTTP agent** enabled
  (default `http://127.0.0.1:17843`).
- No extra Python packages — the node uses only the standard library
  (`urllib`, `json`).

> **Note on the PhotoHandler dependency.** PhotoHandler is a Tauri desktop app.
> The HTTP agent this node talks to is provided by the *hybrid local-agent
> server* (PhotoHandler PR #48, `feat: hybrid local-agent HTTP server
> scaffold`). The agent binds `127.0.0.1` only and requires a library to be
> open in PhotoHandler. Until that work is merged and shipped, run a
> PhotoHandler build from that branch.

## Installation

Clone this repository into your ComfyUI `custom_nodes` directory:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/MarceloSaldias/ComfyUI-PhotoHandler.git
```

Then restart ComfyUI. The node appears under the **PhotoHandler** category as
**PhotoHandler Description**.

## Usage

### PhotoHandler Description (by path)

1. Add the node (right-click → *Add Node* → *PhotoHandler* → *PhotoHandler
   Description*).
2. Set `path` to the **absolute path** of an image PhotoHandler knows about (it
   must live inside the library currently open in PhotoHandler).
3. Optionally set `description_type` to pick a specific *typed* description.
4. Read the `description` / `descriptions_json` outputs (see below).

Under the hood:

```
GET http://127.0.0.1:17843/api/assets/by-path/description?path=<urlencoded-path>[&type=<name>]
```

### PhotoHandler Description (Image) (by SHA-256)

1. Add the **PhotoHandler Description (Image)** node.
2. Drop an image onto its `image` widget (or pick one already in `input/`).
3. Optionally set `description_type`.
4. Read its outputs. In addition to `description` / `descriptions_json`, this
   node also outputs the decoded **`image`** (IMAGE) and **`mask`** (MASK) — just
   like the built-in *Load Image* node — so you can feed the picture straight
   into the rest of your graph. This makes it a drop-in image loader that also
   returns the PhotoHandler description.

The node hashes the file's bytes (SHA-256, matching PhotoHandler's scanner) and
looks up by hash — so it works even when the image was copied into ComfyUI's
`input/` and the original library path is gone:

```
GET http://127.0.0.1:17843/api/assets/by-hash/description?hash=<sha256>[&type=<name>]
```

> **The by-hash route is not in PhotoHandler yet.** It's a small addition to the
> hybrid agent; the exact server-side change is specced in
> [`docs/server-by-hash-endpoint.md`](docs/server-by-hash-endpoint.md). Until it
> lands, the by-path node works but the image node will error.

> **Hash the file, not the pixels.** The match relies on the *original file
> bytes*. The image widget resolves to the verbatim upload in `input/`, so the
> hash matches. Re-encoding or saving the image elsewhere changes the bytes and
> the hash won't match.

### Inputs

| Input              | Node           | Type   | Required | Description                                                               |
| ------------------ | -------------- | ------ | -------- | ------------------------------------------------------------------------- |
| `path`             | Description    | STRING | yes      | Absolute on-disk path, inside PhotoHandler's open library.                |
| `image`            | Description (Image) | IMAGE upload | yes | Image file; hashed and looked up by SHA-256.                       |
| `description_type` | both           | STRING | no       | Named typed description to select (e.g. `Clothing`). Empty → default type.|

### Outputs

| Output              | Node                | Type   | Description                                                                  |
| ------------------- | ------------------- | ------ | ---------------------------------------------------------------------------- |
| `image`             | Description (Image) | IMAGE  | The decoded image (same format as *Load Image*), for chaining downstream.    |
| `mask`              | Description (Image) | MASK   | Alpha-derived mask (zeros when the image has no alpha).                       |
| `description`       | both                | STRING | Selected description: the `description_type` one, else the default, else the legacy single description. Empty string when none. |
| `descriptions_json` | both                | STRING | JSON map of all named typed descriptions (`{}` when none).                   |

### Typed vs. legacy descriptions

PhotoHandler stores descriptions two ways:

- a **legacy** single description per image, and
- **typed** descriptions keyed to named types such as `Clothing` or `Scene`.

The API returns both. The `description` output is the single "selected" value:
the `description_type` you requested → otherwise PhotoHandler's default type →
otherwise the legacy single description. The `descriptions_json` output always
gives you the full typed map so you can route on it downstream.

### Behavior

- If the image is **inside the library but not indexed**, or has **no
  description**, the node returns an **empty string** (this is normal).
- If the path is **outside PhotoHandler's open library**, or **no library is
  open**, the node also returns an **empty string** — PhotoHandler simply can't
  describe it. (PhotoHandler reports these as HTTP 500; the node recognizes the
  message and treats them as a normal empty result.)
- If PhotoHandler is **not reachable**, the node raises a clear `RuntimeError`.
- If the path is **missing/unreadable**, or PhotoHandler returns any other
  error, the node raises a clear `RuntimeError` (surfacing the server message).

## Configuration

| Environment variable | Default                  | Description                          |
| -------------------- | ------------------------ | ------------------------------------ |
| `PHOTOHANDLER_URL`   | `http://127.0.0.1:17843` | Base URL of the PhotoHandler agent.  |

Example:

```bash
export PHOTOHANDLER_URL="http://192.168.1.50:17843"
```

> On the PhotoHandler side, the agent's listening port is set with
> `PHOTOHANDLER_HTTP_PORT` (default `17843`). Point `PHOTOHANDLER_URL` at
> whatever host/port the agent actually binds.

## Development

Run the tests (they spin up a fake HTTP server, so no PhotoHandler instance is
needed):

```bash
pytest test_photohandler_node.py
# or, without pytest installed:
python test_photohandler_node.py
```
