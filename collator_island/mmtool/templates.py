from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol


@dataclass(frozen=True)
class FileTemplate:
    out_relpath: str
    snippet_keys: List[str]


class PipelineTemplate(Protocol):
    def build(self, pipe_cfg: dict) -> List[FileTemplate]:
        ...


def get_templates_for_pipeline(kind: str, pipe_cfg: dict) -> List[FileTemplate]:
    kind = kind.lower()
    try:
        builder = _TEMPLATES[kind]
    except KeyError:
        return []
    return builder.build(pipe_cfg)


def _dataset_kind(pipe_cfg: dict) -> str:
    data = pipe_cfg.get("data") or {}
    if not isinstance(data, dict):
        return "demo"
    return str(data.get("dataset_kind", "demo")).lower()


def _data_modality(pipe_cfg: dict, *, default: str) -> str:
    data = pipe_cfg.get("data") or {}
    if not isinstance(data, dict):
        return default
    return str(data.get("modality", default)).lower()


def _mtl_backbone_kind(pipe_cfg: dict) -> str:
    model = pipe_cfg.get("model") or {}
    if not isinstance(model, dict):
        return "mlp"
    spec = model.get("spec") or {}
    if not isinstance(spec, dict):
        return "mlp"
    return str(spec.get("backbone_kind", "mlp")).lower()


class CNNTemplates:
    def build(self, pipe_cfg: dict) -> List[FileTemplate]:
        dataset_kind = _dataset_kind(pipe_cfg)

        data_snips = [
            "common.future_annotations",
            "data.imports",
        ]
        if dataset_kind == "demo":
            data_snips.append("data.demo_datasets_image")
        data_snips += [
            "data.import_object",
            "data.make_dataset_cnn",
            "data.make_dataloader",
        ]

        return [
            FileTemplate(
                out_relpath="src/model.py",
                snippet_keys=[
                    "common.future_annotations",
                    "common.imports_torch",
                    "common.type_aliases",
                    "cnn.conv_block_spec",
                    "cnn.head_spec",
                    "common.make_activation",
                    "cnn.safe_num_groups",
                    "cnn.make_norm",
                    "cnn.make_pool",
                    "cnn.build_head",
                    "cnn.vanilla_cnn",
                ],
            ),
            FileTemplate(out_relpath="src/criterion.py", snippet_keys=[]),
            FileTemplate(out_relpath="src/data.py", snippet_keys=data_snips),
            FileTemplate(
                out_relpath="src/config.py",
                snippet_keys=[
                    "common.future_annotations",
                    "config.imports",
                    "config.from_dict",
                    "config.find_pipeline_config",
                    "config.load_config",
                    "config.optim_train",
                    "config.data_common",
                    "config.cnn_pipeline",
                ],
            ),
            FileTemplate(
                out_relpath="src/run_demo.py",
                snippet_keys=[
                    "scripts.run_demo_main_cnn",
                ],
            ),
            FileTemplate(
                out_relpath="src/train.py",
                snippet_keys=[
                    "scripts.train_cnn",
                ],
            ),
        ]


class MLPTemplates:
    def build(self, pipe_cfg: dict) -> List[FileTemplate]:
        dataset_kind = _dataset_kind(pipe_cfg)
        modality = _data_modality(pipe_cfg, default="tabular")
        if modality == "auto":
            modality = "tabular"

        data_snips = [
            "common.future_annotations",
            "data.imports",
        ]
        if dataset_kind == "demo":
            if modality == "image":
                data_snips.append("data.demo_datasets_image")
            else:
                data_snips.append("data.demo_datasets_tabular")
        data_snips += [
            "data.import_object",
            "data.infer_task",
            "data.make_dataset_mlp",
            "data.make_dataloader",
        ]

        return [
            FileTemplate(
                out_relpath="src/model.py",
                snippet_keys=[
                    "common.future_annotations",
                    "common.imports_torch",
                    "common.type_aliases",
                    "common.make_activation",
                    "mlp.mlp_spec",
                    "mlp.vanilla_mlp",
                ],
            ),
            FileTemplate(out_relpath="src/criterion.py", snippet_keys=[]),
            FileTemplate(out_relpath="src/data.py", snippet_keys=data_snips),
            FileTemplate(
                out_relpath="src/config.py",
                snippet_keys=[
                    "common.future_annotations",
                    "config.imports",
                    "config.from_dict",
                    "config.find_pipeline_config",
                    "config.load_config",
                    "config.optim_train",
                    "config.data_common",
                    "config.mlp_pipeline",
                ],
            ),
            FileTemplate(
                out_relpath="src/run_demo.py",
                snippet_keys=[
                    "scripts.run_demo_main_mlp",
                ],
            ),
            FileTemplate(
                out_relpath="src/train.py",
                snippet_keys=[
                    "scripts.train_mlp",
                ],
            ),
        ]


class MTLTemplates:
    def build(self, pipe_cfg: dict) -> List[FileTemplate]:
        dataset_kind = _dataset_kind(pipe_cfg)
        backbone = _mtl_backbone_kind(pipe_cfg)

        # data.py is mostly shared; demo dataset only when requested.
        data_snips = [
            "common.future_annotations",
            "data.imports",
        ]
        if dataset_kind == "demo":
            data_snips.append("data.demo_datasets_mtl")
        data_snips += [
            "data.import_object",
            "data.make_dataset_mtl",
            "data.make_dataloader",
        ]

        # model.py is pruned hard based on backbone kind.
        model_snips = [
            "common.future_annotations",
            "common.imports_torch",
            "common.type_aliases",
            "common.make_activation",
            "mtl.task_spec",
            "mtl.build_mlp_lazy",
        ]
        if backbone == "cnn":
            model_snips += [
                "cnn.conv_block_spec",
                "cnn.safe_num_groups",
                "cnn.make_norm",
                "cnn.make_pool",
                "mtl.backbone_cnn",
                "mtl.vanilla_mtl_cnn",
            ]
        else:
            model_snips += [
                "mtl.backbone_mlp",
                "mtl.vanilla_mtl_mlp",
            ]

        return [
            FileTemplate(out_relpath="src/model.py", snippet_keys=model_snips),
            FileTemplate(out_relpath="src/criterion.py", snippet_keys=[]),
            FileTemplate(out_relpath="src/data.py", snippet_keys=data_snips),
            FileTemplate(
                out_relpath="src/config.py",
                snippet_keys=[
                    "common.future_annotations",
                    "config.imports",
                    "config.from_dict",
                    "config.find_pipeline_config",
                    "config.load_config",
                    "config.optim_train",
                    "config.data_common",
                    "config.mtl_pipeline",
                ],
            ),
            FileTemplate(
                out_relpath="src/run_demo.py",
                snippet_keys=[
                    "scripts.run_demo_main_mtl",
                ],
            ),
            FileTemplate(
                out_relpath="src/train.py",
                snippet_keys=[
                    "scripts.train_main_mtl",
                ],
            ),
        ]


_TEMPLATES: Dict[str, PipelineTemplate] = {
    "cnn": CNNTemplates(),
    "mlp": MLPTemplates(),
    "mtl": MTLTemplates(),
}
