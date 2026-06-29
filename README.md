# ComfyUI-PhotoHandler

A custom [ComfyUI](https://github.com/comfyanonymous/ComfyUI) node that fetches
image descriptions from [PhotoHandler](https://github.com/MarceloSaldias) via its
local HTTP agent API.

The node — **PhotoHandler Description** — takes an absolute image path and returns
the description PhotoHandler has stored for that image.

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

1. Add the **PhotoHandler Description** node to your graph
   (right-click → *Add Node* → *PhotoHandler* → *PhotoHandler Description*).
2. Set the `path` input to the **absolute path** of an image PhotoHandler knows
   about (it must live inside the library currently open in PhotoHandler).
3. Optionally set `description_type` to pick a specific *typed* description.
4. Read the outputs:
   - **`description`** — the single selected description string.
   - **`descriptions_json`** — a JSON object string of every named description
     type → text (e.g. `{"Clothing": "...", "Scene": "..."}`).

Under the hood the node issues:

```
GET http://127.0.0.1:17843/api/assets/by-path/description?path=<urlencoded-path>[&type=<name>]
```

### Inputs

| Input              | Type   | Required | Description                                                                 |
| ------------------ | ------ | -------- | --------------------------------------------------------------------------- |
| `path`             | STRING | yes      | Absolute on-disk path of the image, inside PhotoHandler's open library.     |
| `description_type` | STRING | no       | Named typed description to select (e.g. `Clothing`). Empty → default type.  |

### Outputs

| Output              | Type   | Description                                                                  |
| ------------------- | ------ | ---------------------------------------------------------------------------- |
| `description`       | STRING | Selected description: the `description_type` one, else the default, else the legacy single description. Empty string when none. |
| `descriptions_json` | STRING | JSON map of all named typed descriptions (`{}` when none).                   |

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
