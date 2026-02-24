from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

# Keep these strings aligned with generated code snippets.
ActivationName = Literal["relu", "leaky_relu", "gelu", "silu", "tanh", "sigmoid", "none"]
NormName = Literal["batch", "group", "instance", "none"]
PoolName = Literal["max", "avg", "none"]

PipelineKind = Literal["cnn", "mlp", "mtl"]
TaskKind = Literal["binary", "multiclass", "regression"]
DataModality = Literal["image", "tabular", "auto"]
OptimizerKind = Literal["adam", "adamw", "sgd"]


@dataclass(frozen=True)
class CNNConvBlockConfig:
    out_channels: int
    kernel_size: int = 3
    stride: int = 1
    padding: str | int = "same"  # "same" | "valid" | int
    dilation: int = 1
    groups: int = 1
    bias: Optional[bool] = None

    norm: NormName = "batch"
    num_groups: int = 32
    activation: ActivationName = "relu"

    use_dropout: bool = False
    dropout_p: float = 0.0

    pool: PoolName = "none"
    pool_kernel: int = 2
    pool_stride: Optional[int] = None


@dataclass(frozen=True)
class CNNHeadConfig:
    kind: Literal["linear", "mlp", "identity"] = "linear"
    hidden_dims: List[int] = field(default_factory=list)
    use_dropout: bool = False
    dropout_p: float = 0.0
    activation: ActivationName = "relu"
    use_global_pool: bool = True
    global_pool: Literal["avg", "max"] = "avg"


@dataclass(frozen=True)
class CNNModelConfig:
    in_channels: int
    num_classes: Optional[int] = None
    conv_blocks: List[CNNConvBlockConfig] = field(default_factory=list)
    head: CNNHeadConfig = field(default_factory=CNNHeadConfig)
    dropout2d: bool = True
    image_size: int = 64
    task_type: TaskKind = "multiclass"


@dataclass(frozen=True)
class MLPModelConfig:
    input_dim: int
    out_dim: int
    hidden_dims: List[int] = field(default_factory=list)
    activation: ActivationName = "relu"

    use_dropout: bool = False
    dropout_p: float = 0.0
    use_layer_norm: bool = False
    use_batch_norm: bool = False
    modality: DataModality = "tabular"
    task_type: TaskKind = "regression"


@dataclass(frozen=True)
class MTLTaskConfig:
    name: str
    kind: TaskKind
    out_dim: Optional[int] = None  # if None, inferred from kind
    hidden_dims: List[int] = field(default_factory=list)


@dataclass(frozen=True)
class MTLBackboneConfig:
    kind: Literal["mlp", "cnn"]
    mlp: Optional[MLPModelConfig] = None
    cnn: Optional[CNNModelConfig] = None
    image_size: int = 64


@dataclass(frozen=True)
class MTLModelConfig:
    backbone: MTLBackboneConfig
    tasks: List[MTLTaskConfig]

    # shared/head regularization options
    shared_use_layer_norm: bool = False
    shared_use_batch_norm: bool = False
    shared_use_dropout: bool = False
    shared_dropout_p: float = 0.0

    head_use_layer_norm: bool = False
    head_use_batch_norm: bool = False
    head_use_dropout: bool = False
    head_dropout_p: float = 0.0

    activation: ActivationName = "relu"


@dataclass(frozen=True)
class DataConfig:
    dataset_kind: Literal["demo", "custom"] = "demo"
    modality: DataModality = "auto"  # auto -> infer from model kind; prefer explicit
    module: Optional[str] = None
    class_name: Optional[str] = None
    init_args: Dict[str, Any] = field(default_factory=dict)

    # used by demo datasets / resizing
    image_size: int = 64

    batch_size: int = 32
    num_workers: int = 0
    shuffle: bool = True
    pin_memory: bool = False
    drop_last: bool = False

    collate_module: Optional[str] = None
    collate_fn: Optional[str] = None
    train_split: float = 0.8
    val_split: float = 0.1
    test_split: float = 0.1
    split_seed: int = 42


@dataclass(frozen=True)
class CriterionConfig:
    kind: str
    # Single-task
    label_smoothing: float = 0.0
    pos_weight: Optional[float] = None  # BCEWithLogits

    # MTL
    weights: Dict[str, float] = field(default_factory=dict)
    task_losses: Dict[str, str] = field(default_factory=dict)  # task -> loss kind


@dataclass(frozen=True)
class OptimizerConfig:
    kind: OptimizerKind = "adamw"
    lr: float = 1e-3
    weight_decay: float = 0.0
    momentum: float = 0.9  # for sgd
    betas: Tuple[float, float] = (0.9, 0.999)  # for adam/adamw


@dataclass(frozen=True)
class TrainConfig:
    max_epochs: int = 3
    log_every: int = 10
    val_every: int = 1
    max_grad_norm: Optional[float] = None

    early_stop_patience: Optional[int] = None
    early_stop_min_delta: float = 0.0
    early_stop_monitor: Literal["val_loss"] = "val_loss"


@dataclass(frozen=True)
class PipelineConfig:
    name: str
    kind: PipelineKind
    enabled: bool = True

    model: CNNModelConfig | MLPModelConfig | MTLModelConfig | None = None
    criterion: CriterionConfig = field(default_factory=lambda: CriterionConfig(kind="cross_entropy"))
    data: DataConfig = field(default_factory=DataConfig)
    optim: "OptimizerConfig" = field(default_factory=lambda: OptimizerConfig())
    train: "TrainConfig" = field(default_factory=lambda: TrainConfig())


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    pipelines: List[PipelineConfig]
