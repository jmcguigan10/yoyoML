from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from .contracts import RECOMMENDATION_SCHEMA_VERSION, stable_payload_hash

PRODUCER_NAME = "model_selector_island.heuristic_recommender"
PRODUCER_VERSION = "0.1.0"

COLLATOR_SUPPORTED_FAMILIES = ("mlp", "cnn", "mtl")
CORE_ASSUMPTIONS = ("task_type", "target_column")
OPTIONAL_ASSUMPTIONS = ("split_column", "time_column", "group_column", "objective_metric")


def build_recommendation_bundle(
    diagnostic_bundle: Dict[str, Any],
    *,
    max_candidates: int = 3,
) -> Dict[str, Any]:
    datasets = diagnostic_bundle.get("datasets", [])
    if not isinstance(datasets, list):
        datasets = []

    dataset_recommendations: List[Dict[str, Any]] = []
    ready = degraded = blocked = recommendation_count = 0

    for ds in datasets:
        if not isinstance(ds, dict):
            continue
        rec = _recommend_for_dataset(ds, max_candidates=max_candidates)
        dataset_recommendations.append(rec)
        state = rec.get("decision_state")
        if state == "ready":
            ready += 1
        elif state == "degraded":
            degraded += 1
        else:
            blocked += 1
        recommendation_count += len(rec.get("candidates", []))

    return {
        "schema_version": RECOMMENDATION_SCHEMA_VERSION,
        "run_id": f"rec_{uuid.uuid4().hex[:12]}",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "producer": {
            "name": PRODUCER_NAME,
            "version": PRODUCER_VERSION,
        },
        "input_diagnostic_hash": stable_payload_hash(diagnostic_bundle),
        "summary": {
            "dataset_count": len(dataset_recommendations),
            "ready_count": ready,
            "degraded_count": degraded,
            "blocked_count": blocked,
            "recommendation_count": recommendation_count,
        },
        "datasets": dataset_recommendations,
    }


def _recommend_for_dataset(dataset: Dict[str, Any], *, max_candidates: int) -> Dict[str, Any]:
    assumptions = dataset.get("assumptions", [])
    findings = dataset.get("vital_findings", [])
    if not isinstance(assumptions, list):
        assumptions = []
    if not isinstance(findings, list):
        findings = []

    by_assumption = {
        str(a.get("key")): a
        for a in assumptions
        if isinstance(a, dict) and str(a.get("key", "")).strip()
    }
    by_finding = {
        str(f.get("key")): f
        for f in findings
        if isinstance(f, dict) and str(f.get("key", "")).strip()
    }

    decision_state, state_reasons, required_actions = _decision_state(
        dataset,
        by_assumption,
        by_finding,
    )
    task_type = _infer_task_type(by_assumption, by_finding)
    metric = _recommended_metric(by_assumption, by_finding, task_type)
    validation = _recommended_validation_strategy(by_assumption, by_finding, task_type)
    base_conf = _safe_float(dataset.get("confidence_score"), 0.0)
    confidence_score = _decision_confidence(base_conf, decision_state, required_actions)

    candidates: List[Dict[str, Any]] = []
    if decision_state != "blocked":
        ctx = _feature_context(dataset, by_assumption, by_finding, task_type, metric, validation, confidence_score)
        candidates = _build_candidates(ctx)
        candidates = sorted(candidates, key=lambda x: float(x.get("fit_score", 0.0)), reverse=True)
        candidates = candidates[: max(1, max_candidates)]
        for rank, cand in enumerate(candidates, start=1):
            cand["rank"] = rank
            cand["candidate_id"] = f"{dataset.get('dataset_id', 'ds')}_cand_{rank:02d}"

    blocking_reasons = state_reasons if decision_state == "blocked" else []
    if decision_state != "blocked" and state_reasons:
        required_actions = _dedupe(required_actions + [f"Review: {r}" for r in state_reasons])

    return {
        "dataset_id": str(dataset.get("dataset_id", "")),
        "display_name": str(dataset.get("display_name", "")),
        "decision_state": decision_state,
        "required_user_actions": required_actions,
        "recommended_objective_metric": metric,
        "recommended_validation_strategy": validation,
        "confidence_score": confidence_score,
        "blocking_reasons": blocking_reasons,
        "candidates": candidates,
    }


def _decision_state(
    dataset: Dict[str, Any],
    by_assumption: Dict[str, Dict[str, Any]],
    by_finding: Dict[str, Dict[str, Any]],
) -> Tuple[str, List[str], List[str]]:
    raw_reasons = [str(x) for x in (dataset.get("blocking_reasons") or []) if isinstance(x, str)]
    seed_state = str(dataset.get("readiness_state", ""))
    blocking_reasons: List[str] = raw_reasons if seed_state == "blocked" else []
    seed_degraded_reasons: List[str] = raw_reasons if seed_state == "degraded" else []
    required_actions: List[str] = [
        str(x) for x in (dataset.get("required_user_actions") or []) if isinstance(x, str)
    ]

    core_verify_reasons: List[str] = []
    for key in CORE_ASSUMPTIONS:
        item = by_assumption.get(key)
        if not item:
            blocking_reasons.append(f"Missing core assumption: {key}.")
            required_actions.append(f"Provide {key}.")
            continue
        status = str(item.get("status", "unresolved"))
        value = item.get("value")
        if status == "unresolved" or value is None or value == "":
            blocking_reasons.append(f"Core assumption '{key}' is {status}.")
            required_actions.append(f"Confirm core assumption '{key}'.")
        elif status == "needs_user_verification":
            core_verify_reasons.append(f"Core assumption '{key}' needs user verification.")
            required_actions.append(f"Confirm core assumption '{key}'.")

    for vital_key in ("problem_type", "target_definition"):
        finding = by_finding.get(vital_key)
        if finding is None:
            continue
        status = str((finding or {}).get("status", "needs_input"))
        if status != "supported":
            blocking_reasons.append(f"Vital diagnostic '{vital_key}' is not supported.")
            required_actions.append(f"Resolve vital diagnostic '{vital_key}'.")

    if blocking_reasons:
        return "blocked", _dedupe(blocking_reasons), _dedupe(required_actions)

    degraded_reasons: List[str] = []
    degraded_reasons.extend(seed_degraded_reasons)
    degraded_reasons.extend(core_verify_reasons)
    for key in OPTIONAL_ASSUMPTIONS:
        item = by_assumption.get(key)
        if not item:
            degraded_reasons.append(f"Optional assumption '{key}' is missing.")
            required_actions.append(f"Add optional assumption '{key}' if available.")
            continue
        status = str(item.get("status", "unresolved"))
        if status in {"needs_user_verification", "unresolved"}:
            degraded_reasons.append(f"Optional assumption '{key}' is {status}.")
            required_actions.append(f"Verify optional assumption '{key}'.")

    coverage = dataset.get("coverage", {})
    supported = _safe_int((coverage or {}).get("supported_vital_checks"), 0)
    total = _safe_int((coverage or {}).get("total_vital_checks"), 12)
    if total > 0 and (supported / total) < 0.6:
        degraded_reasons.append("Vital diagnostic coverage is below 60%.")
        required_actions.append("Increase diagnostic coverage before broad model search.")

    if degraded_reasons:
        return "degraded", _dedupe(degraded_reasons), _dedupe(required_actions)

    return "ready", [], _dedupe(required_actions)


def _infer_task_type(
    by_assumption: Dict[str, Dict[str, Any]],
    by_finding: Dict[str, Dict[str, Any]],
) -> str:
    task = (by_assumption.get("task_type") or {}).get("value")
    if isinstance(task, str) and task:
        return task
    problem_ev = (by_finding.get("problem_type") or {}).get("evidence", {})
    if isinstance(problem_ev, dict):
        inferred = problem_ev.get("task_type")
        if isinstance(inferred, str) and inferred:
            return inferred
    return "unknown"


def _recommended_metric(
    by_assumption: Dict[str, Dict[str, Any]],
    by_finding: Dict[str, Dict[str, Any]],
    task_type: str,
) -> str | None:
    m = by_assumption.get("objective_metric")
    if isinstance(m, dict) and m.get("value") not in (None, ""):
        return str(m.get("value"))

    metric_finding = by_finding.get("evaluation_metric", {})
    if isinstance(metric_finding, dict):
        evidence = metric_finding.get("evidence", {})
        if isinstance(evidence, dict):
            rec = evidence.get("recommended_metrics")
            if isinstance(rec, list) and rec:
                return str(rec[0])
            if isinstance(evidence.get("metric"), str):
                return str(evidence["metric"])

    if "binary" in task_type:
        return "roc_auc"
    if "multiclass" in task_type or "multilabel" in task_type:
        return "f1_macro"
    if task_type == "regression":
        return "mae"
    return None


def _recommended_validation_strategy(
    by_assumption: Dict[str, Dict[str, Any]],
    by_finding: Dict[str, Dict[str, Any]],
    task_type: str,
) -> str | None:
    split_col = (by_assumption.get("split_column") or {}).get("value")
    time_col = (by_assumption.get("time_column") or {}).get("value")
    group_col = (by_assumption.get("group_column") or {}).get("value")
    if split_col not in (None, ""):
        return "predefined_split_column"
    if time_col not in (None, ""):
        return "time_series_split"
    if group_col not in (None, ""):
        return "group_kfold"

    problem_ev = (by_finding.get("problem_type") or {}).get("evidence", {})
    if isinstance(problem_ev, dict) and bool(problem_ev.get("temporal")):
        return "time_series_split"

    if any(x in task_type for x in ("binary", "multiclass", "multilabel")):
        return "stratified_kfold"
    if task_type == "regression":
        return "kfold"
    return None


def _feature_context(
    dataset: Dict[str, Any],
    by_assumption: Dict[str, Dict[str, Any]],
    by_finding: Dict[str, Dict[str, Any]],
    task_type: str,
    metric: str | None,
    validation: str | None,
    confidence_score: float,
) -> Dict[str, Any]:
    sample = (by_finding.get("sample_size_vs_feature_dimension") or {}).get("evidence", {})
    sample = sample if isinstance(sample, dict) else {}
    feature = (by_finding.get("feature_types") or {}).get("evidence", {})
    feature = feature if isinstance(feature, dict) else {}
    missing = (by_finding.get("missingness") or {}).get("evidence", {})
    missing = missing if isinstance(missing, dict) else {}
    label = (by_finding.get("label_distribution") or {}).get("evidence", {})
    label = label if isinstance(label, dict) else {}
    noise = (by_finding.get("noise_level") or {}).get("evidence", {})
    noise = noise if isinstance(noise, dict) else {}
    corr = (by_finding.get("correlation_structure") or {}).get("evidence", {})
    corr = corr if isinstance(corr, dict) else {}

    n = _safe_int(sample.get("n_rows_sampled"), _safe_int((dataset.get("dataset_profile") or {}).get("rows_profiled"), 0))
    d = _safe_int(sample.get("d_features"), _safe_int((dataset.get("dataset_profile") or {}).get("columns_profiled"), 0))
    n_over_d = _safe_float(sample.get("n_over_d"), float(n / max(1, d)) if d else 0.0)
    regime = str(sample.get("regime", "unknown"))
    fcounts = feature.get("feature_type_counts", {})
    fcounts = fcounts if isinstance(fcounts, dict) else {}

    return {
        "dataset_id": str(dataset.get("dataset_id", "")),
        "detected_type": str(dataset.get("detected_type", "unknown")),
        "task_type": task_type,
        "metric": metric,
        "validation": validation,
        "dataset_confidence": confidence_score,
        "n": n,
        "d": d,
        "n_over_d": n_over_d,
        "regime": regime,
        "feature_type_counts": fcounts,
        "missing_rate": _safe_float(missing.get("overall_missing_rate"), 0.0),
        "missing_kind": str(missing.get("missingness_kind", "")),
        "rare_event": bool(label.get("rare_event")),
        "imbalance_ratio": _safe_float(label.get("imbalance_ratio"), 1.0),
        "class_count": _safe_int(label.get("classes"), 0),
        "noise_proxy": max(
            _safe_float(noise.get("max_numeric_outlier_rate"), 0.0),
            _safe_float(noise.get("label_conflict_proxy"), 0.0),
        ),
        "high_corr_pair_count": _safe_int(corr.get("high_corr_pair_count"), 0),
    }


def _build_candidates(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    task_type = str(ctx.get("task_type", "unknown"))

    # Candidate 1: MLP baseline for tabular and vectorized inputs.
    candidates.append(_build_mlp_candidate(ctx))

    # Candidate 2: MTL only when the task semantics imply multi-output behavior.
    if task_type in {"multilabel_classification"}:
        candidates.append(_build_mtl_candidate(ctx))

    # Candidate 3: CNN probe for very high-dimensional NPZ vectors that may be flattened images.
    if str(ctx.get("detected_type")) == "npz" and _safe_int(ctx.get("d"), 0) >= 512:
        candidates.append(_build_cnn_probe_candidate(ctx))

    # Keep only collator-supported families.
    return [c for c in candidates if str(c.get("family")) in COLLATOR_SUPPORTED_FAMILIES]


def _build_mlp_candidate(ctx: Dict[str, Any]) -> Dict[str, Any]:
    task_type = str(ctx.get("task_type", "unknown"))
    n_over_d = _safe_float(ctx.get("n_over_d"), 0.0)
    d = _safe_int(ctx.get("d"), 0)
    rare_event = bool(ctx.get("rare_event"))
    imbalance_ratio = _safe_float(ctx.get("imbalance_ratio"), 1.0)
    missing_rate = _safe_float(ctx.get("missing_rate"), 0.0)
    text_features = _safe_int((ctx.get("feature_type_counts") or {}).get("text"), 0)
    sequence_features = _safe_int((ctx.get("feature_type_counts") or {}).get("sequence"), 0)
    noise_proxy = _safe_float(ctx.get("noise_proxy"), 0.0)
    high_corr = _safe_int(ctx.get("high_corr_pair_count"), 0)

    if n_over_d < 5:
        hidden_dim_options = [[64, 32], [128, 64]]
        weight_decay = [1e-4, 3e-4, 1e-3]
    elif n_over_d < 20:
        hidden_dim_options = [[128, 64], [256, 128], [256, 128, 64]]
        weight_decay = [1e-5, 1e-4, 3e-4]
    else:
        hidden_dim_options = [[256, 128], [512, 256], [512, 256, 128]]
        weight_decay = [1e-6, 1e-5, 1e-4]

    task_kind, criterion_kind, out_dim_hint = _collator_task_fields(task_type, class_count=_safe_int(ctx.get("class_count"), 0))

    score = 0.66
    rationale = [
        "MLP is the default robust family for tabular/vectorized inputs in the current collator capabilities."
    ]
    risks = []

    if n_over_d < 5:
        score -= 0.05
        rationale.append("Low n/d ratio detected; constrained network widths and stronger regularization recommended.")
    if missing_rate > 0.15:
        score -= 0.05
        risks.append("Missingness is high; pipeline needs explicit imputation/missing-indicator strategy.")
    if text_features > 0 or sequence_features > 0:
        score -= 0.10
        risks.append("Detected text/sequence fields exceed current collator-native tabular assumptions.")
    if rare_event or imbalance_ratio >= 10:
        rationale.append("Imbalance signal detected; use class-aware objective and threshold-aware metrics.")
    if noise_proxy > 0.2:
        score -= 0.04
        risks.append("Noise proxies are elevated; expected variance across HPO trials may be high.")
    if high_corr > 10:
        rationale.append("Strong collinearity detected; regularization and feature pruning are likely helpful.")

    if d > 0 and d <= 10:
        rationale.append("Feature dimension is small; simpler architectures should be prioritized.")

    fit_score = _clamp(score, 0.10, 0.95)
    confidence = _clamp((0.55 + (0.40 * _safe_float(ctx.get("dataset_confidence"), 0.0))), 0.0, 1.0)

    return {
        "candidate_id": "",
        "rank": 0,
        "family": "mlp",
        "fit_score": round(fit_score, 3),
        "confidence": round(confidence, 3),
        "rationale": rationale,
        "collator_intent": {
            "pipeline_kind": "mlp",
            "pipeline_name_template": f"mlp_{task_kind}",
            "config_fragment": {
                "kind": "mlp",
                "model": {
                    "spec": {
                        "input_dim": "$infer_from_dataset",
                        "out_dim": out_dim_hint,
                        "task_type": task_kind,
                        "hidden_dims": hidden_dim_options[0],
                        "activation": "relu",
                        "use_dropout": True,
                        "dropout_p": 0.1,
                        "use_layer_norm": True
                    }
                },
                "criterion": {"kind": criterion_kind},
                "data": {
                    "dataset_kind": "custom",
                    "modality": "tabular",
                    "module": "$user_supplied",
                    "class_name": "$user_supplied",
                    "init_args": {}
                },
                "optim": {"kind": "adamw", "lr": 0.001, "weight_decay": weight_decay[0]},
                "train": {"max_epochs": 20}
            },
            "unresolved_fields": [
                "model.spec.input_dim",
                "model.spec.out_dim",
                "data.module",
                "data.class_name"
            ]
        },
        "hpo_space": {
            "sampler": "tpe",
            "pruner": "median",
            "max_trials": _trial_budget_from_ratio(n_over_d),
            "search_space": {
                "model.spec.hidden_dims": {"type": "categorical", "choices": hidden_dim_options},
                "model.spec.dropout_p": {"type": "float", "low": 0.0, "high": 0.4},
                "model.spec.use_layer_norm": {"type": "categorical", "choices": [True, False]},
                "optim.lr": {"type": "float", "low": 1e-4, "high": 3e-3, "log": True},
                "optim.weight_decay": {"type": "categorical", "choices": weight_decay},
                "train.max_epochs": {"type": "categorical", "choices": [12, 20, 32]}
            },
            "objective_metric": ctx.get("metric"),
            "validation_strategy": ctx.get("validation")
        },
        "risks": risks,
    }


def _build_mtl_candidate(ctx: Dict[str, Any]) -> Dict[str, Any]:
    task_type = str(ctx.get("task_type", "unknown"))
    score = 0.62
    rationale = [
        "Task semantics indicate multi-output behavior; MTL can share representation and reduce overfitting."
    ]
    risks = [
        "Task-head definitions are unresolved and require explicit target decomposition."
    ]
    if task_type != "multilabel_classification":
        score -= 0.12
        rationale.append("Multi-output evidence is weak for this dataset.")

    return {
        "candidate_id": "",
        "rank": 0,
        "family": "mtl",
        "fit_score": round(_clamp(score, 0.10, 0.95), 3),
        "confidence": round(_clamp(0.45 + (0.35 * _safe_float(ctx.get("dataset_confidence"), 0.0)), 0.0, 1.0), 3),
        "rationale": rationale,
        "collator_intent": {
            "pipeline_kind": "mtl",
            "pipeline_name_template": "mtl_auto",
            "config_fragment": {
                "kind": "mtl",
                "model": {
                    "spec": {
                        "backbone_kind": "mlp",
                        "tasks": "$user_supplied_task_list"
                    }
                },
                "criterion": {
                    "kind": "weighted_mtl",
                    "task_losses": "$user_supplied_loss_map"
                },
                "data": {"dataset_kind": "custom", "modality": "tabular"}
            },
            "unresolved_fields": [
                "model.spec.tasks",
                "criterion.task_losses",
                "data.module",
                "data.class_name"
            ]
        },
        "hpo_space": {
            "sampler": "tpe",
            "pruner": "median",
            "max_trials": 40,
            "search_space": {
                "model.spec.mlp_backbone.hidden_dims": {
                    "type": "categorical",
                    "choices": [[128, 64], [256, 128]]
                },
                "optim.lr": {"type": "float", "low": 1e-4, "high": 2e-3, "log": True},
                "criterion.weights_mode": {
                    "type": "categorical",
                    "choices": ["uniform", "learned_uncertainty"]
                }
            },
            "objective_metric": ctx.get("metric"),
            "validation_strategy": ctx.get("validation")
        },
        "risks": risks,
    }


def _build_cnn_probe_candidate(ctx: Dict[str, Any]) -> Dict[str, Any]:
    task_type = str(ctx.get("task_type", "unknown"))
    task_kind, criterion_kind, _ = _collator_task_fields(task_type, class_count=_safe_int(ctx.get("class_count"), 0))
    return {
        "candidate_id": "",
        "rank": 0,
        "family": "cnn",
        "fit_score": round(_clamp(0.53 + (0.10 * _safe_float(ctx.get("dataset_confidence"), 0.0)), 0.10, 0.95), 3),
        "confidence": round(_clamp(0.40 + (0.30 * _safe_float(ctx.get("dataset_confidence"), 0.0)), 0.0, 1.0), 3),
        "rationale": [
            "NPZ high-dimensional features may encode flattened image-like tensors; a CNN probe is included."
        ],
        "collator_intent": {
            "pipeline_kind": "cnn",
            "pipeline_name_template": f"cnn_probe_{task_kind}",
            "config_fragment": {
                "kind": "cnn",
                "model": {
                    "in_channels": "$infer_or_user_supplied",
                    "task_type": task_kind,
                    "conv_blocks": [
                        {"out_channels": 32, "kernel_size": 3, "pool": "max"},
                        {"out_channels": 64, "kernel_size": 3, "pool": "max"}
                    ]
                },
                "criterion": {"kind": criterion_kind},
                "data": {"dataset_kind": "custom", "modality": "image"}
            },
            "unresolved_fields": [
                "model.in_channels",
                "model.num_classes",
                "data.module",
                "data.class_name"
            ]
        },
        "hpo_space": {
            "sampler": "tpe",
            "pruner": "median",
            "max_trials": 30,
            "search_space": {
                "model.conv_blocks[0].out_channels": {"type": "categorical", "choices": [16, 32, 64]},
                "model.conv_blocks[1].out_channels": {"type": "categorical", "choices": [32, 64, 128]},
                "optim.lr": {"type": "float", "low": 1e-4, "high": 2e-3, "log": True}
            },
            "objective_metric": ctx.get("metric"),
            "validation_strategy": ctx.get("validation")
        },
        "risks": [
            "Feature-to-image reshaping assumptions may be invalid; verify geometry before running CNN trials."
        ],
    }


def _trial_budget_from_ratio(n_over_d: float) -> int:
    if n_over_d < 5:
        return 40
    if n_over_d < 20:
        return 60
    return 80


def _collator_task_fields(task_type: str, *, class_count: int) -> Tuple[str, str, Any]:
    if task_type == "binary_classification":
        return "binary", "bce_with_logits", 1
    if task_type == "multiclass_classification":
        out_dim = class_count if class_count > 1 else "$infer_class_count"
        return "multiclass", "cross_entropy", out_dim
    if task_type == "multilabel_classification":
        out_dim = class_count if class_count > 1 else "$infer_label_count"
        return "multiclass", "bce_with_logits", out_dim
    if task_type == "regression":
        return "regression", "mse", 1
    return "regression", "mse", "$infer_target_dim"


def _decision_confidence(base_conf: float, state: str, required_actions: List[str]) -> float:
    score = base_conf
    if state == "blocked":
        score *= 0.4
    elif state == "degraded":
        score *= 0.75
    if required_actions:
        score *= max(0.4, 1.0 - (0.05 * len(required_actions)))
    return round(_clamp(score, 0.0, 1.0), 3)


def _safe_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
