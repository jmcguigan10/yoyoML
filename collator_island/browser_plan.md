## Implementation plan (much more specific)

### Workstream 0: Define the contracts (do this first or enjoy rewriting everything)

#### 0.1 IR schema (versioned, strict)

Implement as:

- Pydantic models in Python (source of truth)
- JSON Schema export generated from Pydantic for the browser

Key rules:

- Every object has `schema_version`
- Every node instance references a `node_type` and `node_type_version`
- Defaults must be explicitly materialized in the canonical compiled config output

Core IR pieces:

- `project`
- `datasets[]`
- `data_profile` (optional cache, not authoritative)
- `graph` (authoritative for UI)
- `pipeline_config` (authoritative for backend execution)
- `validation` metadata (manifest hash, rule set version)

#### 0.2 Node Definition spec (single source of truth)

A `NodeDefinition` JSON structure produced by `mmtool manifest`:

```json
{
  "type": "TabularData",
  "version": "1.0.0",
  "category": "DataSource",
  "ports": {
    "inputs": [],
    "outputs": [
      { "name": "data", "type": "Dataset<tabular>" }
    ]
  },
  "params_schema": { "...json schema..." },
  "defaults": { "...explicit..." },
  "compile": {
    "emits": ["pipeline_config.data"],
    "backend_snippets": ["datasource.tabular.v1"]
  }
}
```

This prevents the UI and backend from drifting into different realities.

#### 0.3 Capability manifest (generated, hashed)

`mmtool manifest` output includes:

- `mmtool_version`
- `manifest_hash`
- `schema_versions_supported`
- `node_definitions[]`
- `rule_definitions[]` (metadata only)
- `backend_capabilities` (models, losses, task types)

Browser refuses to load incompatible manifest. Backend refuses IR from mismatched manifest unless migrated.

---

### Workstream 1: Backend (`mmtool`) foundation

You’re building the “real compiler”. Treat it like one.

#### 1.1 CLI commands (minimum set)

- `mmtool manifest --out manifest.json`
- `mmtool verify --project project.mmui.json`
- `mmtool bind --project project.mmui.json --dataset ds_train /abs/path/to/file`
- `mmtool compile --project project.mmui.json --out compiled_config.json`
- `mmtool generate --project project.mmui.json --out ./pipeline_out`
- `mmtool run --project project.mmui.json` (optional shortcut, calls generate then executes)

#### 1.2 Schema validation + canonicalization

Steps when loading a project:

1. Validate IR schema
2. Validate `manifest_hash` compatibility
3. Load `.mmui.bindings.json`
4. Resolve datasets to paths and confirm fingerprints
5. Validate compiled `pipeline_config` (complete, explicit)
6. Re-run L1/L2 verification in Python (authoritative)

#### 1.3 Snippet registry + codegen (make it boring and deterministic)

Your AST merge idea is doable but risky. The safe version looks like this:

- **A fixed project skeleton template** (folder with `main.py`, `config.json`, `requirements.lock`, etc.)
- Snippets are **small, composable modules** with declared:
  - imports
  - config fragments
  - pipeline hook functions
  - dependencies

- “Merge” is:
  - build a dependency graph of snippets
  - generate `pipeline_components.py` (or similar) in deterministic order
  - generate a single config file with stable ordering

If you insist on AST merge into existing files:

- Use a concrete syntax tree tool (like LibCST) and **only patch at labeled anchors**.
- Ban “search and replace vibes”. Require anchor tokens like:

```python
# [MMTOOL:IMPORTS]
# [MMTOOL:COMPONENTS]
# [MMTOOL:MAIN]
```

Then tests can detect if anchors went missing.

#### 1.4 Reproducibility output

When generating a runnable pipeline, emit:

- `compiled_config.json`
- `dataset_fingerprints.json`
- `env.lock` (pip freeze/uv lock/poetry lock)
- `run_metadata.json` (seed, git commit of mmtool, timestamp, manifest hash)

---

### Workstream 2: Frontend (Browser IDE)

React Flow is a perfectly reasonable choice for the graph canvas. ([React Flow][5])

#### 2.1 App structure (modules)

- `manifest/` loader + validator
- `project/` load/save (IR + UI layout)
- `datasets/` picker + binding UI + fingerprinting
- `profile/` worker-based profiler + cache
- `graph/` editor (React Flow), node palette, inspector
- `rules/` rule engine runner + issues store + fix applier
- `export/` canonical IR writer (and “compiled config preview” UI)

State management:

- Don’t invent a new state system. React Flow already uses Zustand internally and even documents integration patterns. ([React Flow][6])

#### 2.2 Data access: support tiers

Because File System Access API is not universal ([Can I Use][1]), implement tiers:

**Tier 1 (best): File System Access API**

- persistent handles
- directory projects
- OPFS cache

**Tier 2 (fallback): `<input type="file">`**

- can read files this session
- no persistent handles
- require reselect on reload

Be blunt in UI about limitations. Humans hate surprises almost as much as they hate reading.

#### 2.3 Profiling engine (in-browser)

Use DuckDB-WASM as the default profiler for tabular formats:

- It runs in-browser ([DuckDB][3])
- It supports registering file handles ([DuckDB][4])
- DuckDB supports Parquet well in general ([DuckDB][7])

Implementation details:

- Run DuckDB in a Web Worker
- For a selected dataset:
  - register file handle
  - create a DuckDB view/table using `read_csv_auto` / `read_parquet`
  - compute stats with SQL

- Always use **sampling** for expensive computations:
  - correlations on sampled rows
  - duplicates on sampled rows + approximate methods
  - cardinality via `approx_count_distinct`

Profile output should include:

- row count estimate (exact if cheap)
- inferred column types (duckdb types mapped to your type system)
- missingness per column
- distinct counts (approx ok)
- numeric quantiles (approx ok)
- top-k categorical values
- target distribution (if target selected)
- “warnings” from profiler (e.g., huge text blobs)

Caching:

- Store computed profile summaries in **Origin Private File System (OPFS)** so you don’t re-profile constantly. OPFS is broadly supported in modern browsers per MDN. ([MDN Web Docs][8])
  (And yes, it’s sandboxed. That’s fine. It’s a cache, not a source of truth.)

Fingerprinting:

- For big files, don’t hash the whole thing by default.
- Use a practical fingerprint like:
  - file size
  - lastModified
  - hash of first N MB + last N MB
  - format + schema snapshot

- If strict reproducibility is required, offer “full hash” as an explicit slow action.

#### 2.4 Graph editor details (typed DAG, no nonsense)

Graph invariants enforced at edit-time:

- forbid cycles at connect-time (React Flow lets you intercept edge creation)
- ports are typed, edges only connect if types unify
- nodes have stable IDs (UUID v4) so diffs don’t explode

Node UI:

- Palette grouped by category
- Inspector panel generated from `params_schema` (JSON Schema-driven forms)
- Inline warnings on nodes with issues

Layout:

- Provide auto-layout button (dagre/elk)
- Keep user manual positioning, store in `graph.layout`

---

### Workstream 3: Type system + inference (the piece people underbuild and regret)

You can’t do meaningful verification without a real type system. “Typed ports” needs specifics.

#### 3.1 Define a small but expressive type algebra

Examples (keep it simple):

- `Dataset<tabular {columns: ...}>`
- `Dataset<image {H?, W?, C?}>`
- `Tensor<float32 [B, F]>`
- `Model<task=multiclass, in=Tensor[...,F], out=Tensor[...,K]>`
- `Loss<expects=ModelOutput, target=Categorical(K)>`

#### 3.2 Inference algorithm (constraint solving)

At compile time:

1. Topologically sort DAG
2. Assign each port a type expression
3. For each edge, unify src and dst types
4. Introduce type variables for unknown dims (`F?`, `K?`)
5. Solve constraints, error on conflicts
6. Emit resolved types into `pipeline_config` generation

This is exactly what compilers do, except your “program” is a graph and your “types” are tensors and datasets.

---

### Workstream 4: Rule engine (L1/L2/L3) with patch-based fixes

Your three levels are good. Make them mechanically enforceable.

#### 4.1 Issue object (standard)

Each issue includes:

- `id`, `level`, `severity`
- `message` (human readable)
- `location`: `{ node_id?, edge_id?, param_path? }`
- `evidence` (numbers from profile when relevant)
- `fixes[]`: list of JSON Patch ops (RFC 6902-style)

#### 4.2 Execution pipeline

- `normalize(graph)`:
  - fill defaults from node defs
  - expand macros (like “Trainer preset” into multiple nodes) if you support them

- `infer_types(graph, profile)`
- Run L1 rules (hard fail)
- Run L2 rules (fail or strong warn depending on mode)
- Run L3 rules (suggestions)

#### 4.3 Auto-fix mechanism

Fixes should be deterministic patch ops like:

- set param value
- insert node + connect edges
- replace node type

UI displays “Apply fix” and shows the patch preview.

---

### Workstream 5: Compilation (Graph → canonical `pipeline_config`)

This is where you stop being an art project.

Rules:

- Backend must be able to run from `pipeline_config` + dataset bindings.
- Graph is supplementary for UI.
- Compilation must be deterministic and stable.

Implementation:

- Each `NodeDefinition.compile` declares what it emits (config fragment) and how it connects.
- Use a compiler pass that builds intermediate structures:
  - data section
  - transforms chain
  - model section
  - training section
  - eval section

- Explicitly materialize defaults into the emitted config (no silent defaults).

Output:

- `compiled_config.json` (canonical)
- store it inside IR under `pipeline_config` or regenerate on demand (your call, but be consistent)

---

## Testing strategy (because otherwise you’ll ship a liar)

### Backend tests

- **Golden tests**: IR → compiled_config → generated pipeline folder hash
- Rule unit tests: minimal graphs triggering each rule
- Schema migration tests: old IR versions migrate cleanly

### Frontend tests

- Graph invariants tests (no cycles, type mismatch blocks)
- Profiling correctness on fixtures
- Export/import round-trip tests (IR stable)

### End-to-end

- Example projects shipped with repo:
  - tabular binary classification
  - tabular regression
  - image classification (later)

- CI runs: `mmtool verify` and `mmtool generate` for each example

---

## Risk register

1. **Browser support**: FS Access API still not on Safari/Firefox ([Can I Use][1])
   Mitigation: desktop wrapper or explicit Chromium-only positioning.

2. **Large datasets**: profiling can freeze the UI
   Mitigation: DuckDB-WASM in worker + sampling + progress + cancellation ([DuckDB][3])

3. **Registry drift**: UI and backend node definitions diverge
   Mitigation: manifest is generated by backend and treated as source of truth

4. **AST merge complexity**: codegen becomes fragile
   Mitigation: anchor-based patching + deterministic generation + golden tests

5. **“Verified” doesn’t mean correct**: heuristics are not guarantees
   Mitigation: be explicit about what each rule checks and what it cannot check

---

[1]: https://caniuse.com/native-filesystem-api "File System Access API | Can I use... Support tables for HTML5, CSS3, etc"
[2]: https://v2.tauri.app/plugin/file-system/?utm_source=chatgpt.com "File System"
[3]: https://duckdb.org/docs/stable/clients/wasm/overview.html?utm_source=chatgpt.com "DuckDB Wasm"
[4]: https://duckdb.org/docs/stable/clients/wasm/data_ingestion.html?utm_source=chatgpt.com "Data Ingestion"
[5]: https://reactflow.dev/?utm_source=chatgpt.com "React Flow: Node-Based UIs in React"
[6]: https://reactflow.dev/learn/advanced-use/state-management?utm_source=chatgpt.com "Using a State Management Library"
[7]: https://duckdb.org/docs/stable/data/parquet/overview.html?utm_source=chatgpt.com "Reading and Writing Parquet Files"
[8]: https://developer.mozilla.org/en-US/docs/Web/API/File_System_API/Origin_private_file_system?utm_source=chatgpt.com "Origin private file system - Web APIs | MDN"
