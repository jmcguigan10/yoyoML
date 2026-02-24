# mmtool Configuration Guide (TOML)

This repo generates **runnable ML pipeline folders** from a single project config file.

The goal of this guide is to make it easy to translate:

> “I want *this* model, trained *this* way, on *this* dataset”

into:

> “Here is the TOML mmtool needs.”

---

## 1) Two config layers: project config vs pipeline config

### A) Project config (input to the generator)
You write a **project config** (TOML or YAML) with a list of pipelines.

You then run:

```bash
python -m mmtool.cli generate \
  --project examples/project.toml \
  --txt-store txt_store \
  --db snippet_db/snippets.sqlite \
  --out dist \
  --force
```

That creates:

```
dist/<pipeline_name>/
  config/pipeline.toml
  src/model.py
  src/criterion.py
  src/data.py
  src/train.py
  src/run_demo.py
```

### B) Pipeline config (what the generated code reads)
Each generated pipeline writes out **its own config** into `dist/<name>/config/pipeline.toml`.

You can edit that file and re-run `train.py` without regenerating the entire pipeline.

---

## 2) TOML syntax you need for this repo

This repo expects the project config to have:

- a top-level `project` table (optional)
- a top-level `pipelines` list (required)

In TOML, **lists of objects** are written as **arrays of tables**:

```toml
[[pipelines]]
name = "cnn_demo"
kind = "cnn"
enabled = true

[[pipelines]]
name = "mlp_demo"
kind = "mlp"
enabled = true
```

### Nested tables attach to “the current pipeline”
After `[[pipelines]]`, any `[pipelines.*]` table attaches to the most recent pipeline entry.

Example:

```toml
[[pipelines]]
name = "mlp_demo"
kind = "mlp"

[pipelines.model.spec]
input_dim = 20
out_dim = 1
hidden_dims = [64, 64]
```

### Lists of objects inside a pipeline
Some fields are “list of specs”, like CNN `conv_blocks` or MTL `tasks`.

Those become arrays of tables:

```toml
[[pipelines.model.conv_blocks]]
out_channels = 32
kernel_size = 3

[[pipelines.model.conv_blocks]]
out_channels = 64
kernel_size = 3
```

---

## 3) Project config shape (cheat sheet)

Every pipeline entry is the same at the top level:

```toml
[[pipelines]]
name = "some_name"
kind = "cnn"   # "cnn" | "mlp" | "mtl"
enabled = true
```

And then each pipeline typically has these sections:

- `pipelines.model` (or `pipelines.model.spec`)
- `pipelines.criterion`
- `pipelines.data`
- `pipelines.optim`
- `pipelines.train`

### Model section depends on pipeline kind

| kind | model section lives at |
|---|---|
| `cnn` | `[pipelines.model]` |
| `mlp` | `[pipelines.model.spec]` |
| `mtl` | `[pipelines.model.spec]` |

This is not negotiable. If you put MLP fields directly under `model` instead of `model.spec`, the generated dataclass loader will not find them.

---

## 4) CNN pipelines (image convnet)

CNN pipelines are for images (or “image-like tensors” shaped like NCHW).

### 4.1 Minimal CNN classifier

```toml
[[pipelines]]
name = "cnn_small"
kind = "cnn"
enabled = true

[pipelines.model]
in_channels = 3
num_classes = 10
task_type = "multiclass"
image_size = 64

[[pipelines.model.conv_blocks]]
out_channels = 32
kernel_size = 3
norm = "batch"
activation = "relu"
pool = "max"

[[pipelines.model.conv_blocks]]
out_channels = 64
kernel_size = 3
norm = "batch"
activation = "relu"
pool = "max"

[pipelines.model.head]
kind = "linear"          # "linear" | "mlp" | "identity"
use_global_pool = true
global_pool = "avg"      # "avg" | "max"

[pipelines.criterion]
kind = "cross_entropy"   # alias: "ce"

[pipelines.data]
dataset_kind = "demo"    # "demo" | "custom"
modality = "image"
batch_size = 16
num_workers = 0
image_size = 64
```

### 4.2 How to design a CNN in this config

Think in three parts:

1) **Conv stack** (`conv_blocks`)
2) **Pooling choice** (inside blocks, and/or global pool)
3) **Head** (`head`)

#### Conv blocks (`[[pipelines.model.conv_blocks]]`)
Each block supports:

- `out_channels` (required)
- `kernel_size`, `stride`, `padding` (default `"same"`), `dilation`, `groups`
- `norm`: `"batch" | "group" | "instance" | "none"`
- `activation`: `"relu" | "gelu" | "silu" | ...`
- `pool`: `"max" | "avg" | "none"`
- dropout inside the block: `use_dropout`, `dropout_p`

Rule of thumb:
- use pooling (`pool="max"` or `"avg"`) when you want spatial downsampling
- use block dropout when you overfit

#### Head (`[pipelines.model.head]`)
The head supports:

- `kind = "linear"`: simplest classifier/regressor head
- `kind = "mlp"` with `hidden_dims = [...]`: for more capacity after pooling
- `use_global_pool` + `global_pool`: reduces `(C,H,W)` to `(C,)` before the head

### 4.3 Binary classification CNN

Binary classification is still a “CNN pipeline”, but:

- set `task_type = "binary"`
- set `num_classes` (often 1 is used with logits, but this pipeline structure expects `num_classes` optional)
- use BCE criterion

Example:

```toml
[[pipelines]]
name = "cnn_binary"
kind = "cnn"
enabled = true

[pipelines.model]
in_channels = 3
task_type = "binary"
image_size = 64

[[pipelines.model.conv_blocks]]
out_channels = 32
pool = "max"

[pipelines.criterion]
kind = "bce_with_logits"
pos_weight = 2.0

[pipelines.data]
dataset_kind = "demo"
modality = "image"
batch_size = 16
image_size = 64
```

---

## 5) MLP pipelines (tabular / vector)

MLP pipelines store model parameters under `model.spec`.

### 5.1 Minimal regression MLP

```toml
[[pipelines]]
name = "mlp_reg"
kind = "mlp"
enabled = true

[pipelines.model.spec]
input_dim = 20
out_dim = 1
task_type = "regression"
hidden_dims = [128, 64]
activation = "gelu"
use_dropout = true
dropout_p = 0.1
use_layer_norm = true

[pipelines.criterion]
kind = "mse"

[pipelines.data]
dataset_kind = "demo"
modality = "tabular"
batch_size = 64
```

### 5.2 Binary classification MLP

```toml
[[pipelines]]
name = "mlp_binary"
kind = "mlp"
enabled = true

[pipelines.model.spec]
input_dim = 20
out_dim = 1
task_type = "binary"
hidden_dims = [128, 64]
activation = "relu"

[pipelines.criterion]
kind = "bce_with_logits"
pos_weight = 1.0

[pipelines.data]
dataset_kind = "demo"
modality = "tabular"
batch_size = 64
```

### 5.3 Notes on `modality`
MLP supports `modality = "tabular" | "image" | "auto"` in the *data config*.

- Use `"tabular"` for vectors.
- Use `"image"` only if your dataset yields images but you intend to flatten them into vectors (your custom dataset can do that).
- `"auto"` is allowed, but explicit is safer.

---

## 6) MTL pipelines (multi-task learning)

MTL in this repo means:

- one shared backbone (`mlp` or `cnn`)
- multiple task heads
- separate task losses combined by a criterion (currently weighted sum)

MTL parameters live under `model.spec`.

### 6.1 MTL spec structure

At minimum, you must set:

- `backbone_kind = "mlp"` or `"cnn"`
- the matching `mlp_backbone` or `cnn_backbone`
- `[[...tasks]]` with at least 1 task

### 6.2 MTL with MLP backbone (mixed tasks)

```toml
[[pipelines]]
name = "mtl_mlp_mixed"
kind = "mtl"
enabled = true

[pipelines.model.spec]
backbone_kind = "mlp"
activation = "relu"
head_use_dropout = true
head_dropout_p = 0.1

[pipelines.model.spec.mlp_backbone]
input_dim = 16
hidden_dims = [128, 64]
activation = "relu"
use_layer_norm = true
use_dropout = true
dropout_p = 0.1

[[pipelines.model.spec.tasks]]
name = "is_fraud"
kind = "binary"
hidden_dims = [32]

[[pipelines.model.spec.tasks]]
name = "bucket"
kind = "multiclass"
out_dim = 5
hidden_dims = []

[[pipelines.model.spec.tasks]]
name = "amount"
kind = "regression"
hidden_dims = [32, 16]

[pipelines.criterion]
kind = "weighted_mtl"

[pipelines.criterion.task_losses]
is_fraud = "bce_with_logits"
bucket = "cross_entropy"
amount = "mse"

[pipelines.criterion.weights]
is_fraud = 1.0
bucket = 1.0
amount = 0.5

[pipelines.data]
dataset_kind = "demo"
modality = "image"
batch_size = 16
image_size = 64
```

#### MTL task rules that matter
- If `kind = "binary"` or `"regression"` and `out_dim` is omitted, it defaults to 1.
- If `kind = "multiclass"`, you must set `out_dim` (number of classes). If you don’t, the model constructor will throw.

### 6.3 MTL with CNN backbone

```toml
[[pipelines]]
name = "mtl_cnn_backbone"
kind = "mtl"
enabled = true

[pipelines.model.spec]
backbone_kind = "cnn"
activation = "relu"

[pipelines.model.spec.cnn_backbone]
in_channels = 3
use_global_pool = true
global_pool = "avg"
image_size = 64

[[pipelines.model.spec.cnn_backbone.conv_blocks]]
out_channels = 32
kernel_size = 3
norm = "batch"
activation = "relu"
pool = "max"

[[pipelines.model.spec.cnn_backbone.conv_blocks]]
out_channels = 64
kernel_size = 3
norm = "batch"
activation = "relu"
pool = "max"

[[pipelines.model.spec.tasks]]
name = "class"
kind = "multiclass"
out_dim = 10

[pipelines.criterion]
kind = "weighted_mtl"

[pipelines.criterion.task_losses]
class = "cross_entropy"

[pipelines.criterion.weights]
class = 1.0

[pipelines.data]
dataset_kind = "demo"
modality = "image"
batch_size = 16
image_size = 64
```

---

## 7) Data configuration (demo vs custom)

Every pipeline supports a `data` block:

```toml
[pipelines.data]
dataset_kind = "demo"  # or "custom"
modality = "auto"
batch_size = 32
num_workers = 0
shuffle = true
pin_memory = false
drop_last = false
train_split = 0.8
val_split = 0.1
test_split = 0.1
split_seed = 42
```

### 7.1 Demo datasets
If `dataset_kind = "demo"`, the generated pipeline uses synthetic datasets that match the model type.

### 7.2 Custom datasets
If `dataset_kind = "custom"`, you must specify:

```toml
[pipelines.data]
dataset_kind = "custom"
module = "my_pkg.data"
class_name = "MyDataset"
init_args = { root = "/data", split = "train" }
```

Your dataset class should behave like a PyTorch Dataset:
- `__len__`
- `__getitem__`

And should return:
- (x, y) for single-task CNN/MLP
- (x, y_dict) for MTL, where `y_dict` maps task name to target tensor

---

## 8) Criterion (loss) configuration

### 8.1 Single-task CNN/MLP
Use:
- `cross_entropy` / `ce`
- `bce_with_logits` / `bce` (optional `pos_weight`)
- `mse` / `l2`

Example:

```toml
[pipelines.criterion]
kind = "cross_entropy"
label_smoothing = 0.0
```

### 8.2 MTL
Current supported kind is `weighted_mtl`, and you must provide:
- `task_losses` table
- (optional) `weights` table

```toml
[pipelines.criterion]
kind = "weighted_mtl"

[pipelines.criterion.task_losses]
task_a = "mse"
task_b = "bce_with_logits"

[pipelines.criterion.weights]
task_a = 1.0
task_b = 0.5
```

---

## 9) Optimizer configuration

```toml
[pipelines.optim]
kind = "adamw"       # "adamw" | "adam" | "sgd"
lr = 0.001
weight_decay = 0.0001
momentum = 0.9       # only used for sgd
betas = [0.9, 0.999] # adam/adamw
```

---

## 10) Train configuration

```toml
[pipelines.train]
max_epochs = 3
log_every = 10
val_every = 1
max_grad_norm = 1.0

early_stop_patience = 2
early_stop_min_delta = 0.0
early_stop_monitor = "val_loss"
```

---

## 11) Common mistakes (a.k.a. why your config “doesn’t work”)

1) **Wrong nesting**:
   - MLP and MTL require `model.spec`.
   - CNN uses `model` directly.

2) **Forgetting `out_dim` for multiclass MTL tasks**:
   - `kind="multiclass"` requires `out_dim`.

3) **TOML arrays-of-tables syntax**:
   - Lists of objects must use `[[...]]`.

4) **Running on Python < 3.11 without tomli**:
   - TOML parsing needs `tomllib` (3.11+) or `tomli`.

---

## 12) Full working example

See `examples/project.toml` for a complete multi-pipeline project file that mirrors `examples/project.yaml`.
