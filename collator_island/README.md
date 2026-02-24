# mm_protv2

A **config-driven model/pipeline generator** prototype.

It does two mildly questionable things:

1. stores code snippets in plain `.txt` files, each with **<= 1 top-level function**,
2. indexes those snippet files in **sqlite**, then assembles final `.py` files using an AST-based merge.

## What you get

- CNN pipelines (image)
- MLP pipelines (tabular / vectors)
- MTL pipelines (multi-task) with either an MLP backbone or a CNN backbone
- Model classes contain **only architecture + forward**; criteria are in **separate files**
- Each generated pipeline contains its own `config/pipeline.toml` (default)
- Data loading is configurable via the `data` block (demo or custom datasets); every pipeline ships with `src/data.py`
- Explicit structural hints: specify task type (`binary|multiclass|regression`), modality (`image|tabular`), and image size up front to avoid inference surprises.

## Quick start

From this repo root:

```bash
# 1) Build the snippet registry
python3 -m mmtool.cli init-db --txt-store txt_store --db snippet_db/snippets.sqlite

# 2) Generate pipelines from TOML (recommended)
python3 -m mmtool.cli generate \
  --project examples/project.toml \
  --txt-store txt_store \
  --db snippet_db/snippets.sqlite \
  --out dist

# YAML is still supported if you enjoy indentation-related suffering:
#   --project examples/project.yaml
```

Now you have folders like:

```
dist/
  cnn_demo/
    config/pipeline.toml
    src/model.py
    src/criterion.py
    src/config.py
    src/run_demo.py
    src/train.py
```

Try:

```bash
python3 dist/cnn_demo/src/run_demo.py
python3 dist/cnn_demo/src/train.py
```

### Configuring datasets

Each pipeline accepts a `data` block, e.g. (TOML):

```toml
[data]
dataset_kind = "demo"       # or "custom"
modality = "image"          # image | tabular | auto
module = "my_pkg.data"      # required when dataset_kind=custom
class_name = "MyDataset"    # required when dataset_kind=custom
init_args = { root = "/data/images" }
batch_size = 16
num_workers = 4
shuffle = true
pin_memory = true
image_size = 64             # used for demo datasets / resizing

# For single-task CNN pipelines also set the task type
[model]
task_type = "multiclass"    # or binary (MLP uses model.spec.task_type)
```

Generated `src/data.py` exposes `make_dataset(cfg, split)` and `make_dataloader(cfg, split)` which are used by the demo/train scripts. Demo datasets emit synthetic data matching each pipeline type (CNN, MLP, MTL).

## Notes

- `notes/` contains the original reference markdown for CNN + MTL.
- This is a prototype. It intentionally prioritizes "it works" over "it’s a pristine framework".

## Probe runner adapter

This island now includes a feedback-loop adapter for probe execution contracts:

- input contract: `probe_request_bundle.v1`
- output contract: `probe_result_bundle.v1`
- runner: `run_collator_probes.py`

Example:

```bash
python3 run_collator_probes.py \
  --probe-request-in ../tmp/probe_request.round1.json \
  --probe-result-out ../tmp/probe_result.round1.json
```

The current runner is deterministic and simulation-based (contract adapter), designed to unblock loop integration while full collator/HPO execution plumbing is finalized.
