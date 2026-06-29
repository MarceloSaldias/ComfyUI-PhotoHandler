# Server spec: description lookup by SHA-256

This node ships a **PhotoHandler Description (Image)** node that looks up an
asset by the SHA-256 of its file bytes. PhotoHandler does not expose that route
yet — this document is the precise server-side change to add to the hybrid
local-agent server (PhotoHandler PR #48,
`feat/issue-13-hybrid-http-scaffold`).

## Why

When an image is dragged into ComfyUI it is copied into `ComfyUI/input/`. The
**path** differs from PhotoHandler's library path (so `by-path` reports "outside
the library"), but the **bytes are identical**, so the SHA-256 matches the
`file_hash` PhotoHandler already stores.

PhotoHandler already:

- hashes the full file with SHA-256 — `python/operations/scanner.py::_get_file_hash`;
- matches assets by that hash — `asset_repo::find_import_target`
  (`SELECT id FROM assets WHERE file_hash = ?1`).

So the data and query pattern exist; only an HTTP route is missing.

## Route

```
GET /api/assets/by-hash/description?hash=<sha256-hex>[&type=<name>]
```

Response — identical shape to the existing `by-path` route:

```json
{ "path": "<abs|''>", "description": "<text>", "asset_id": <id|null>,
  "descriptions": { "<TypeName>": "<text>", ... } }
```

- Read-only; never generates a description.
- Unknown hash (not in the library) → `200` with `description: ""`,
  `asset_id: null`, `descriptions: {}`.
- **No `ensure_readable` gate** — a hash is not a filesystem path, so there is
  nothing to canonicalize or confine to the library root. (This is the one
  behavioural difference from `by-path`.) The library-open check still applies:
  with no library open, return the empty result (or the existing
  "No library is open" error — the node treats that message as empty too).
- `hash` should be compared case-insensitively (store/compare lowercased hex).

## Changes

### 1. `src-tauri/src/db/asset_repo.rs` — `get_by_hash`

Mirror `get_by_path`, keyed on `file_hash`:

```rust
/// Look up a single asset by its SHA-256 file hash. Returns None if no asset
/// with that hash is indexed.
pub fn get_by_hash(conn: &Connection, file_hash: &str) -> Result<Option<Asset>, AppError> {
    let mut stmt = conn.prepare(
        "SELECT id, path, filename, folder, file_hash, file_size, width, height, \
         date_taken, description, thumbnail_path, asset_type \
         FROM assets WHERE file_hash = ?1 COLLATE NOCASE LIMIT 1",
    )?;
    let mut rows = stmt.query_map(params![file_hash], map_asset_row)?;
    match rows.next() {
        Some(row) => Ok(Some(row?)),
        None => Ok(None),
    }
}
```

(Reuse whatever row-mapping helper `get_by_path` uses; shown above as
`map_asset_row`.)

### 2. `src-tauri/src/commands/asset.rs` — `get_asset_description_by_hash_inner`

Transport-agnostic, mirrors `get_asset_description_by_path_inner` but takes a
hash and skips `ensure_readable`:

```rust
/// Look up an asset's description(s) by SHA-256 file hash. Read-only; never
/// generates. A missing asset yields an empty `DescriptionByPath`-shaped result.
pub fn get_asset_description_by_hash_inner(
    state: &AppState,
    file_hash: &str,
    type_name: Option<&str>,
) -> Result<DescriptionByPathResult, AppError> {
    let guard = state.library.read().unwrap();
    let lib = match guard.as_ref() {
        Some(lib) => lib,
        None => return Ok(DescriptionByPathResult::empty()),
    };
    let conn = lib.db.connect()?;

    let asset = match crate::db::asset_repo::get_by_hash(&conn, file_hash)? {
        Some(asset) => asset,
        None => return Ok(DescriptionByPathResult::empty()),
    };

    // Identical to the by-path path from here on: pull named typed descriptions,
    // resolve the single `description` (type_name -> default -> legacy column),
    // build the `descriptions` map (empties dropped), hydrate `path` to absolute.
    let named = crate::db::description_repo::get_named_for_asset(&conn, asset.id)?;
    let description = match type_name {
        Some(name) => named.iter()
            .find(|d| d.type_name.eq_ignore_ascii_case(name) && !d.description.is_empty())
            .map(|d| d.description.clone())
            .unwrap_or_default(),
        None => named.iter()
            .find(|d| d.is_default && !d.description.is_empty())
            .map(|d| d.description.clone())
            .unwrap_or_else(|| asset.description.clone()),
    };
    let descriptions = named.into_iter()
        .filter(|d| !d.description.is_empty())
        .map(|d| (d.type_name, d.description))
        .collect();

    Ok(DescriptionByPathResult {
        path: asset.path,          // already absolute in the DB
        description,
        asset_id: Some(asset.id),
        descriptions,
    })
}
```

Factor the shared "assemble result from an `Asset` + conn" block out of the
by-path inner fn if you want to avoid the duplication.

### 3. `src-tauri/src/http_server.rs` — route + handler

```rust
// in spawn()'s Router:
.route(
    "/api/assets/by-hash/description",
    get(http_get_asset_description_by_hash),
)

#[derive(serde::Deserialize)]
struct ByHashQuery {
    hash: String,
    #[serde(rename = "type")]
    type_name: Option<String>,
}

async fn http_get_asset_description_by_hash(
    State(state): State<Arc<AppState>>,
    Query(q): Query<ByHashQuery>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let result = crate::commands::asset::get_asset_description_by_hash_inner(
        &state,
        &q.hash,
        q.type_name.as_deref(),
    )
    .map_err(map_err)?;
    Ok(Json(json!(result)))
}
```

Add `/api/assets/by-hash/description` to the startup log line listing routes.

### 4. Tests (`asset_repo`)

Mirror the `get_by_path` unit tests for `get_by_hash`: found / missing /
case-insensitive match.

### 5. Docs

Add the route to `docs/HYBRID_ARCHITECTURE.md` next to the by-path entry, with a
curl recipe:

```
curl --get http://127.0.0.1:17843/api/assets/by-hash/description \
  --data-urlencode 'hash=<sha256hex>'
```

## Node compatibility

The node computes the hash exactly as the scanner does (SHA-256 over the full
file, streamed in chunks) and sends it lowercased-hex via `?hash=`. No node
change is needed once this route lands.
