# ComfyUI-PhotoHandler

A custom [ComfyUI](https://github.com/comfyanonymous/ComfyUI) node that fetches
image descriptions from [PhotoHandler](https://github.com/MarceloSaldias) via its
local HTTP agent API.

The node — **PhotoHandler Description** — takes an absolute image path and returns
the description PhotoHandler has stored for that image.

## Requirements

- A running **PhotoHandler** instance exposing its local HTTP agent API
  (default `http://127.0.0.1:17843`).
- No extra Python packages — the node uses only the standard library
  (`urllib`, `json`).

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
   about.
3. The node outputs the stored `description` as a string, ready to feed into a
   prompt, text encoder, or any node that accepts a string.

Under the hood the node issues:

```
GET http://127.0.0.1:17843/api/assets/by-path/description?path=<urlencoded-path>
```

### Behavior

- If the image is **unknown** to PhotoHandler, or it has **no description**, the
  node returns an **empty string** (this is normal, not an error).
- If PhotoHandler is **not reachable**, the node raises a clear `RuntimeError`.
- If PhotoHandler returns a **non-200** status (other than 404), the node raises
  a clear `RuntimeError`.

## Configuration

| Environment variable | Default                  | Description                          |
| -------------------- | ------------------------ | ------------------------------------ |
| `PHOTOHANDLER_URL`   | `http://127.0.0.1:17843` | Base URL of the PhotoHandler agent.  |

Example:

```bash
export PHOTOHANDLER_URL="http://192.168.1.50:17843"
```

## Development

Run the tests (they spin up a fake HTTP server, so no PhotoHandler instance is
needed):

```bash
pytest test_photohandler_node.py
# or, without pytest installed:
python test_photohandler_node.py
```
