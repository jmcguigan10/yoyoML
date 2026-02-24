from __future__ import annotations

import math
import re
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .base import DiagnosticFinding
from ..core.context import InspectionContext
from ..core.tabular_profile import TabularProfile

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore


VITAL_TITLES: List[Tuple[str, str]] = [
    ("problem_type", "Problem Type"),
    ("target_definition", "Target Definition"),
    ("data_splitting_structure", "Data Splitting Structure"),
    ("sample_size_vs_feature_dimension", "Sample Size vs Feature Dimension"),
    ("feature_types", "Feature Types"),
    ("missingness", "Missingness"),
    ("label_distribution", "Label Distribution"),
    ("noise_level", "Noise Level"),
    ("feature_scale", "Feature Scale"),
    ("correlation_structure", "Correlation Structure"),
    ("distribution_shift_risk", "Distribution Shift Risk"),
    ("evaluation_metric", "Evaluation Metric"),
]


@dataclass
class ResolvedSemantics:
    target_col: Optional[str]
    time_col: Optional[str]
    group_col: Optional[str]
    split_col: Optional[str]
    id_cols: List[str]


@dataclass
class TaskInference:
    task_type: str
    confidence: float
    target_col: Optional[str]
    temporal: bool
    multi_task: bool
    source: str

    def is_classification(self) -> bool:
        return self.task_type in {"binary_classification", "multiclass_classification", "multilabel_classification"}

    def is_regression(self) -> bool:
        return self.task_type == "regression"


class VitalDiagnostics:
    """Heuristic ML-readiness diagnostics for tabular data profiles."""

    TARGET_CANDIDATES = (
        "target",
        "label",
        "y",
        "class",
        "outcome",
        "response",
        "dependent",
        "status",
        "unstable",
    )
    TIME_CANDIDATES = ("timestamp", "datetime", "date", "time", "event_time", "created_at", "ts")
    SPLIT_CANDIDATES = ("split", "dataset_split", "set", "fold")
    GROUP_CANDIDATES = ("group", "entity_id", "user_id", "customer_id", "account_id", "session_id")

    def run(self, profile: TabularProfile, ctx: InspectionContext) -> List[DiagnosticFinding]:
        if pd is None:
            return self._all_needs_input("pandas unavailable; diagnostics disabled.")

        df = profile.dataframe
        if df is None or df.empty:
            return self._all_needs_input("No tabular rows available for diagnostics.")

        semantics = self._resolve_semantics(df, ctx)
        task = self._infer_task(df, semantics, ctx)

        findings = [
            self._check_problem_type(df, semantics, task, ctx),
            self._check_target_definition(df, semantics, task),
            self._check_data_splitting_structure(df, semantics, task),
            self._check_sample_size_vs_feature_dimension(df, semantics),
            self._check_feature_types(df, semantics),
            self._check_missingness(df, semantics, task),
            self._check_label_distribution(df, semantics, task),
            self._check_noise_level(df, semantics, task),
            self._check_feature_scale(df, semantics, task),
            self._check_correlation_structure(df, semantics, task),
            self._check_distribution_shift_risk(df, semantics, task),
            self._check_evaluation_metric(df, semantics, task, ctx),
        ]
        return findings

    # -------------------------
    # Vital checks
    # -------------------------
    def _check_problem_type(
        self,
        df,
        semantics: ResolvedSemantics,
        task: TaskInference,
        ctx: InspectionContext,
    ) -> DiagnosticFinding:
        if task.task_type == "unknown":
            return DiagnosticFinding(
                key="problem_type",
                title="Problem Type",
                status="needs_input",
                confidence=0.0,
                summary="Unable to infer problem type without target/task hints.",
                evidence={"target_column": semantics.target_col},
                warnings=["Pass --target-col and optionally --task-hint to lock this down."],
            )

        shape = "temporal" if task.temporal else "static"
        scope = "multi-task" if task.multi_task else "single-task"
        return DiagnosticFinding(
            key="problem_type",
            title="Problem Type",
            status="supported",
            confidence=task.confidence,
            summary=f"Inferred {task.task_type} ({scope}, {shape}).",
            evidence={
                "task_type": task.task_type,
                "target_column": task.target_col,
                "temporal": task.temporal,
                "inference_source": task.source,
            },
        )

    def _check_target_definition(
        self,
        df,
        semantics: ResolvedSemantics,
        task: TaskInference,
    ) -> DiagnosticFinding:
        target = semantics.target_col
        if not target or target not in df.columns:
            return DiagnosticFinding(
                key="target_definition",
                title="Target Definition",
                status="needs_input",
                confidence=0.0,
                summary="Target is not defined for diagnostics.",
                warnings=["Pass --target-col to enable deterministic/noisy/leakage heuristics."],
            )

        feature_cols = [c for c in df.columns if c != target and c not in semantics.id_cols]
        collision_noise = None
        repeated_keys = 0
        conflicting_keys = 0
        if feature_cols:
            repeated_keys, conflicting_keys, collision_noise = self._conflicting_duplicate_rate(df, target, feature_cols[:20])

        target_name = self._norm(target)
        leakage_markers = []
        for c in feature_cols:
            cn = self._norm(c)
            if target_name and target_name in cn and cn != target_name:
                leakage_markers.append(c)
            if any(tok in cn for tok in ("future", "next_", "lead_", "t_plus", "label", "target")):
                leakage_markers.append(c)
        leakage_markers = sorted(set(leakage_markers))

        aggregated_hint = any(tok in target_name for tok in ("avg", "mean", "sum", "count", "rate", "rolling"))
        deterministic = collision_noise is not None and collision_noise < 0.05

        warnings: List[str] = []
        if leakage_markers:
            warnings.append("Possible target leakage markers found in feature names.")
        if collision_noise is not None and collision_noise > 0.20:
            warnings.append("Repeated feature signatures map to multiple target values in sample.")

        confidence = 0.7 if len(df) >= 200 else 0.55
        return DiagnosticFinding(
            key="target_definition",
            title="Target Definition",
            status="supported",
            confidence=confidence,
            summary=(
                "Target diagnostics computed from sampled data. "
                f"Deterministic proxy={deterministic}, leakage_markers={len(leakage_markers)}."
            ),
            evidence={
                "target_column": target,
                "deterministic_proxy": deterministic,
                "aggregated_target_name_hint": aggregated_hint,
                "repeated_signatures": repeated_keys,
                "conflicting_signatures": conflicting_keys,
                "collision_noise_rate": collision_noise,
                "possible_leakage_columns": leakage_markers[:10],
            },
            warnings=warnings,
        )

    def _check_data_splitting_structure(
        self,
        df,
        semantics: ResolvedSemantics,
        task: TaskInference,
    ) -> DiagnosticFinding:
        split_col = semantics.split_col
        group_col = semantics.group_col
        time_col = semantics.time_col

        duplicate_rate = float(df.duplicated().mean()) if len(df) else 0.0
        structure = "iid_assumed"
        split_values = []
        if split_col and split_col in df.columns:
            split_values = [str(v) for v in df[split_col].dropna().astype(str).unique().tolist()[:10]]
            structure = "explicit_split_column"
        elif time_col and time_col in df.columns:
            structure = "temporal_order_detected"

        leakage_fraction = None
        if split_col and group_col and split_col in df.columns and group_col in df.columns:
            leakage_fraction = self._group_leakage_fraction(df, split_col, group_col)

        drift_signal = None
        if time_col and time_col in df.columns:
            drift_signal = self._time_drift_signal(df, time_col)

        warnings: List[str] = []
        if duplicate_rate > 0.05:
            warnings.append("Duplicate row rate is high in sampled data.")
        if leakage_fraction is not None and leakage_fraction > 0:
            warnings.append("Group/entity overlap detected across split buckets.")

        confidence = 0.8 if split_col else (0.7 if time_col else 0.55)
        return DiagnosticFinding(
            key="data_splitting_structure",
            title="Data Splitting Structure",
            status="supported",
            confidence=confidence,
            summary=f"Split structure assessed as {structure}; duplicate_rate={duplicate_rate:.3f}.",
            evidence={
                "structure": structure,
                "split_column": split_col,
                "group_column": group_col,
                "time_column": time_col,
                "split_values_sample": split_values,
                "duplicate_row_rate": round(duplicate_rate, 4),
                "group_leakage_fraction": leakage_fraction,
                "time_drift_signal": drift_signal,
            },
            warnings=warnings,
        )

    def _check_sample_size_vs_feature_dimension(self, df, semantics: ResolvedSemantics) -> DiagnosticFinding:
        target = semantics.target_col
        feature_cols = [c for c in df.columns if c != target]
        n = int(len(df))
        d = int(len(feature_cols))
        ratio = float(n / max(1, d))

        if ratio < 5:
            regime = "low_data_high_d"
            regularization = "mandatory"
        elif ratio < 20:
            regime = "moderate_data_medium_d"
            regularization = "recommended"
        else:
            regime = "data_adequate_for_many_models"
            regularization = "task_dependent"

        return DiagnosticFinding(
            key="sample_size_vs_feature_dimension",
            title="Sample Size vs Feature Dimension",
            status="supported",
            confidence=0.9,
            summary=f"n={n}, d={d}, n/d={ratio:.2f} ({regime}).",
            evidence={
                "n_rows_sampled": n,
                "d_features": d,
                "n_over_d": round(ratio, 4),
                "regime": regime,
                "regularization": regularization,
            },
        )

    def _check_feature_types(self, df, semantics: ResolvedSemantics) -> DiagnosticFinding:
        feature_cols = [c for c in df.columns if c != semantics.target_col]
        type_by_col: Dict[str, str] = {}
        counts: Dict[str, int] = {}
        for col in feature_cols:
            t = self._infer_feature_type(df[col])
            type_by_col[col] = t
            counts[t] = counts.get(t, 0) + 1

        return DiagnosticFinding(
            key="feature_types",
            title="Feature Types",
            status="supported",
            confidence=0.85,
            summary=f"Inferred feature type map for {len(feature_cols)} feature columns.",
            evidence={
                "feature_type_counts": counts,
                "feature_types_by_column": type_by_col,
            },
        )

    def _check_missingness(self, df, semantics: ResolvedSemantics, task: TaskInference) -> DiagnosticFinding:
        masks = {c: self._missing_mask(df[c]) for c in df.columns}
        rates = {c: float(m.mean()) for c, m in masks.items()}
        overall_rate = float(sum(m.sum() for m in masks.values()) / max(1, len(df) * max(1, len(df.columns))))

        missing_cols = [c for c, r in rates.items() if r > 0]
        if not missing_cols:
            return DiagnosticFinding(
                key="missingness",
                title="Missingness",
                status="supported",
                confidence=0.9,
                summary="No missing values detected in sampled rows.",
                evidence={"overall_missing_rate": 0.0, "missing_columns": []},
            )

        indicator_corr = self._max_missing_indicator_corr(masks)
        informative_signal = None
        if semantics.target_col and semantics.target_col in df.columns:
            informative_signal = self._target_missingness_signal(df, semantics.target_col, masks, task)

        missingness_kind = "mostly_mcar_like"
        if indicator_corr is not None and indicator_corr > 0.2:
            missingness_kind = "structured_missingness_likely"
        if informative_signal is not None and informative_signal > 0.1:
            missingness_kind = "possibly_informative_missingness"

        return DiagnosticFinding(
            key="missingness",
            title="Missingness",
            status="supported",
            confidence=0.8 if len(df) >= 100 else 0.65,
            summary=f"Missingness assessed as {missingness_kind}; overall_rate={overall_rate:.3f}.",
            evidence={
                "overall_missing_rate": round(overall_rate, 6),
                "missing_columns": sorted(missing_cols),
                "missing_rate_by_column": {k: round(v, 6) for k, v in sorted(rates.items(), key=lambda kv: kv[1], reverse=True)},
                "max_missing_indicator_corr": indicator_corr,
                "target_missingness_signal": informative_signal,
                "missingness_kind": missingness_kind,
            },
        )

    def _check_label_distribution(self, df, semantics: ResolvedSemantics, task: TaskInference) -> DiagnosticFinding:
        target = semantics.target_col
        if not target or target not in df.columns:
            return DiagnosticFinding(
                key="label_distribution",
                title="Label Distribution",
                status="needs_input",
                confidence=0.0,
                summary="No target column set; cannot evaluate label distribution.",
            )

        y = df[target].dropna()
        if y.empty:
            return DiagnosticFinding(
                key="label_distribution",
                title="Label Distribution",
                status="needs_input",
                confidence=0.0,
                summary="Target is empty in sampled rows.",
            )

        if task.is_classification():
            counts = y.astype(str).value_counts(dropna=False)
            total = int(counts.sum())
            minority = int(counts.min()) if not counts.empty else 0
            minority_rate = float(minority / max(1, total))
            imbalance_ratio = float(counts.max() / max(1, minority)) if not counts.empty else 1.0
            long_tail = bool(len(counts) >= 10 and float(counts.iloc[0] / max(1, total)) < 0.5)
            return DiagnosticFinding(
                key="label_distribution",
                title="Label Distribution",
                status="supported",
                confidence=0.85,
                summary=f"Classification label distribution computed across {len(counts)} classes.",
                evidence={
                    "classes": len(counts),
                    "counts": {str(k): int(v) for k, v in counts.to_dict().items()},
                    "minority_rate": round(minority_rate, 6),
                    "imbalance_ratio": round(imbalance_ratio, 6),
                    "rare_event": minority_rate < 0.05,
                    "long_tail": long_tail,
                },
            )

        y_num = pd.to_numeric(y, errors="coerce").dropna()
        if y_num.empty:
            return DiagnosticFinding(
                key="label_distribution",
                title="Label Distribution",
                status="needs_input",
                confidence=0.0,
                summary="Target values are not analyzable as numeric or classes.",
            )

        q = y_num.quantile([0.01, 0.5, 0.99]).to_dict()
        skew = float(y_num.skew()) if len(y_num) > 2 else 0.0
        return DiagnosticFinding(
            key="label_distribution",
            title="Label Distribution",
            status="supported",
            confidence=0.8,
            summary="Regression target distribution summarized.",
            evidence={
                "count": int(len(y_num)),
                "mean": float(y_num.mean()),
                "std": float(y_num.std(ddof=0)) if len(y_num) > 1 else 0.0,
                "q01": float(q.get(0.01, y_num.min())),
                "q50": float(q.get(0.5, y_num.median())),
                "q99": float(q.get(0.99, y_num.max())),
                "skew": skew,
            },
        )

    def _check_noise_level(self, df, semantics: ResolvedSemantics, task: TaskInference) -> DiagnosticFinding:
        numeric_cols = [c for c in df.columns if self._is_numeric_series(df[c]) and c != semantics.target_col]
        outlier_rates = {}
        for c in numeric_cols[:50]:
            rate = self._iqr_outlier_rate(pd.to_numeric(df[c], errors="coerce").dropna())
            if rate is not None:
                outlier_rates[c] = rate

        measurement_noise_proxy = max(outlier_rates.values()) if outlier_rates else None

        label_conflict_proxy = None
        if semantics.target_col and semantics.target_col in df.columns:
            feature_cols = [c for c in df.columns if c != semantics.target_col and c not in semantics.id_cols]
            if feature_cols:
                _, _, label_conflict_proxy = self._conflicting_duplicate_rate(
                    df,
                    semantics.target_col,
                    feature_cols[:20],
                )

        if measurement_noise_proxy is None and label_conflict_proxy is None:
            return DiagnosticFinding(
                key="noise_level",
                title="Noise Level",
                status="needs_input",
                confidence=0.0,
                summary="Insufficient numeric/target evidence for noise heuristics.",
                warnings=["Noise floor requires richer labels or repeated measurements."],
            )

        warnings = ["Noise diagnostics are proxy heuristics, not ground-truth annotation audits."]
        return DiagnosticFinding(
            key="noise_level",
            title="Noise Level",
            status="supported",
            confidence=0.5,
            summary="Computed measurement/annotation noise proxies from sampled data.",
            evidence={
                "max_numeric_outlier_rate": measurement_noise_proxy,
                "outlier_rate_by_feature": {k: round(v, 6) for k, v in outlier_rates.items()},
                "label_conflict_proxy": label_conflict_proxy,
            },
            warnings=warnings,
        )

    def _check_feature_scale(self, df, semantics: ResolvedSemantics, task: TaskInference) -> DiagnosticFinding:
        numeric_cols = [c for c in df.columns if self._is_numeric_series(df[c]) and c != semantics.target_col]
        if not numeric_cols:
            return DiagnosticFinding(
                key="feature_scale",
                title="Feature Scale",
                status="needs_input",
                confidence=0.0,
                summary="No numeric features available for scale diagnostics.",
            )

        stats = {}
        stds = []
        ranges = []
        heavy_tail = []
        log_candidates = []

        for c in numeric_cols[:80]:
            s = pd.to_numeric(df[c], errors="coerce").dropna()
            if s.empty:
                continue
            c_min, c_max = float(s.min()), float(s.max())
            c_std = float(s.std(ddof=0)) if len(s) > 1 else 0.0
            q05 = float(s.quantile(0.05))
            q95 = float(s.quantile(0.95))
            skew = float(s.skew()) if len(s) > 2 else 0.0
            stats[c] = {"min": c_min, "max": c_max, "std": c_std, "q05": q05, "q95": q95, "skew": skew}
            if c_std > 0:
                stds.append(c_std)
            if c_max > c_min:
                ranges.append(c_max - c_min)
            if abs(skew) > 2:
                heavy_tail.append(c)
            if q05 > 0 and q95 / max(q05, 1e-9) > 100 and skew > 1:
                log_candidates.append(c)

        scale_ratio = float(max(stds) / min(stds)) if len(stds) >= 2 else None
        range_ratio = float(max(ranges) / min(ranges)) if len(ranges) >= 2 else None
        orders_mag = None
        if range_ratio and range_ratio > 0:
            orders_mag = math.log10(range_ratio)

        return DiagnosticFinding(
            key="feature_scale",
            title="Feature Scale",
            status="supported",
            confidence=0.8,
            summary="Numeric feature scale diagnostics computed.",
            evidence={
                "numeric_feature_count": len(numeric_cols),
                "std_scale_ratio": scale_ratio,
                "range_scale_ratio": range_ratio,
                "orders_of_magnitude_span": orders_mag,
                "heavy_tail_features": heavy_tail[:20],
                "log_transform_candidates": log_candidates[:20],
                "feature_stats": stats,
            },
        )

    def _check_correlation_structure(self, df, semantics: ResolvedSemantics, task: TaskInference) -> DiagnosticFinding:
        feature_cols = [c for c in df.columns if c != semantics.target_col]
        if len(feature_cols) < 2:
            return DiagnosticFinding(
                key="correlation_structure",
                title="Correlation Structure",
                status="needs_input",
                confidence=0.0,
                summary="At least two feature columns are needed for correlation diagnostics.",
            )

        numeric_cols = [c for c in feature_cols if self._is_numeric_series(df[c])]
        high_corr_pairs: List[Dict[str, Any]] = []
        if len(numeric_cols) >= 2:
            corr = df[numeric_cols].apply(pd.to_numeric, errors="coerce").corr()
            for i, c1 in enumerate(corr.columns):
                for c2 in corr.columns[i + 1 :]:
                    v = corr.loc[c1, c2]
                    if pd.notna(v) and abs(float(v)) >= 0.9:
                        high_corr_pairs.append({"a": c1, "b": c2, "corr": round(float(v), 4)})
            high_corr_pairs.sort(key=lambda x: abs(x["corr"]), reverse=True)

        duplicate_features = self._duplicate_feature_pairs(df[feature_cols[:120]])

        warnings = []
        if high_corr_pairs:
            warnings.append("Highly collinear numeric features detected.")
        if duplicate_features:
            warnings.append("Redundant duplicate feature columns detected in sampled data.")
        warnings.append("Strong interaction effects are not fully inferred by this heuristic stage.")

        return DiagnosticFinding(
            key="correlation_structure",
            title="Correlation Structure",
            status="supported",
            confidence=0.78,
            summary="Correlation and redundancy heuristics computed.",
            evidence={
                "high_corr_pair_count": len(high_corr_pairs),
                "high_corr_pairs": high_corr_pairs[:50],
                "duplicate_feature_pairs": duplicate_features[:30],
            },
            warnings=warnings,
        )

    def _check_distribution_shift_risk(self, df, semantics: ResolvedSemantics, task: TaskInference) -> DiagnosticFinding:
        split_col = semantics.split_col
        time_col = semantics.time_col

        if split_col and split_col in df.columns:
            shift = self._split_shift(df, split_col)
            return DiagnosticFinding(
                key="distribution_shift_risk",
                title="Distribution Shift Risk",
                status="supported",
                confidence=0.82,
                summary=f"Compared distributions across split column '{split_col}'.",
                evidence=shift,
            )

        if time_col and time_col in df.columns:
            drift = self._time_drift_signal(df, time_col)
            return DiagnosticFinding(
                key="distribution_shift_risk",
                title="Distribution Shift Risk",
                status="supported",
                confidence=0.7,
                summary=f"Computed temporal drift proxy from '{time_col}'.",
                evidence={"time_column": time_col, "temporal_drift_proxy": drift},
            )

        return DiagnosticFinding(
            key="distribution_shift_risk",
            title="Distribution Shift Risk",
            status="needs_input",
            confidence=0.0,
            summary="No split/time signal available for shift diagnostics.",
            warnings=["Pass --split-col or --time-col to activate shift checks."],
        )

    def _check_evaluation_metric(
        self,
        df,
        semantics: ResolvedSemantics,
        task: TaskInference,
        ctx: InspectionContext,
    ) -> DiagnosticFinding:
        if ctx.objective_metric:
            return DiagnosticFinding(
                key="evaluation_metric",
                title="Evaluation Metric",
                status="supported",
                confidence=0.95,
                summary=f"Using user-specified objective metric '{ctx.objective_metric}'.",
                evidence={"metric": ctx.objective_metric, "source": "user_hint"},
            )

        if task.task_type == "unknown":
            return DiagnosticFinding(
                key="evaluation_metric",
                title="Evaluation Metric",
                status="needs_input",
                confidence=0.0,
                summary="Cannot propose metric without inferred task type.",
                warnings=["Pass --task-hint or --target-col to get a metric recommendation."],
            )

        recommended = []
        rationale = []

        if task.is_classification():
            imbalance = None
            if semantics.target_col and semantics.target_col in df.columns:
                counts = df[semantics.target_col].astype(str).value_counts(dropna=False)
                if len(counts) >= 2:
                    imbalance = float(counts.min() / max(1, counts.sum()))
            if imbalance is not None and imbalance < 0.10:
                recommended = ["pr_auc", "f1_macro", "balanced_accuracy"]
                rationale.append("Detected class imbalance in sampled target.")
            else:
                recommended = ["roc_auc", "f1_macro", "accuracy"]
                rationale.append("Classification task inferred from target distribution.")
        elif task.is_regression():
            recommended = ["mae", "rmse", "r2"]
            rationale.append("Regression task inferred from target distribution.")
        else:
            recommended = ["task_specific_metric"]
            rationale.append("Task family inferred but specific objective remains ambiguous.")

        return DiagnosticFinding(
            key="evaluation_metric",
            title="Evaluation Metric",
            status="supported",
            confidence=0.6,
            summary="Heuristic metric recommendation generated.",
            evidence={"recommended_metrics": recommended, "rationale": rationale},
            warnings=["Recommendation is heuristic; align metric with deployment/business cost."],
        )

    # -------------------------
    # Helpers
    # -------------------------
    def _resolve_semantics(self, df, ctx: InspectionContext) -> ResolvedSemantics:
        cols = [str(c) for c in df.columns]

        target_col = self._pick_col(cols, ctx.target_column, self.TARGET_CANDIDATES)
        time_col = self._pick_col(cols, ctx.time_column, self.TIME_CANDIDATES)
        split_col = self._pick_col(cols, ctx.split_column, self.SPLIT_CANDIDATES)
        group_col = self._pick_col(cols, ctx.group_column, self.GROUP_CANDIDATES)

        id_cols: List[str] = []
        hinted_ids = [self._match_col(cols, x) for x in (ctx.id_columns or ())]
        for c in hinted_ids:
            if c:
                id_cols.append(c)

        for c in cols:
            cn = self._norm(c)
            if cn in {"id", "uuid"} or cn.endswith("_id") or "identifier" in cn:
                id_cols.append(c)
        id_cols = sorted(set(id_cols))

        if target_col is None:
            target_col = self._infer_target_column(df, id_cols, {split_col, time_col, group_col})

        return ResolvedSemantics(
            target_col=target_col,
            time_col=time_col,
            group_col=group_col,
            split_col=split_col,
            id_cols=id_cols,
        )

    def _infer_task(self, df, semantics: ResolvedSemantics, ctx: InspectionContext) -> TaskInference:
        task_hint = (ctx.task_hint or "").strip().lower()
        if task_hint:
            norm = task_hint.replace("-", "_").replace(" ", "_")
            mapping = {
                "binary": "binary_classification",
                "binary_classification": "binary_classification",
                "classification": "multiclass_classification",
                "multiclass": "multiclass_classification",
                "multiclass_classification": "multiclass_classification",
                "multilabel": "multilabel_classification",
                "multilabel_classification": "multilabel_classification",
                "regression": "regression",
                "ranking": "ranking",
                "survival": "survival",
            }
            inferred = mapping.get(norm, norm)
            return TaskInference(
                task_type=inferred,
                confidence=0.95,
                target_col=semantics.target_col,
                temporal=bool(semantics.time_col),
                multi_task=bool(semantics.target_col and "," in semantics.target_col),
                source="task_hint",
            )

        target = semantics.target_col
        if not target or target not in df.columns:
            return TaskInference("unknown", 0.0, target, bool(semantics.time_col), False, "none")

        y = df[target].dropna()
        if y.empty:
            return TaskInference("unknown", 0.0, target, bool(semantics.time_col), False, "empty_target")

        y_str = y.astype(str)
        if self._looks_multilabel(y_str):
            return TaskInference("multilabel_classification", 0.65, target, bool(semantics.time_col), False, "heuristic")

        if self._is_numeric_series(y):
            y_num = pd.to_numeric(y, errors="coerce").dropna()
            if y_num.empty:
                return TaskInference("unknown", 0.0, target, bool(semantics.time_col), False, "coercion_failed")

            unique = int(y_num.nunique(dropna=True))
            integerish = bool((y_num.dropna() % 1 == 0).all()) if len(y_num) else False
            if unique <= 2:
                task_type = "binary_classification"
                conf = 0.9
            elif integerish and unique <= max(20, int(0.10 * len(y_num))):
                task_type = "multiclass_classification"
                conf = 0.7
            else:
                task_type = "regression"
                conf = 0.75
            return TaskInference(task_type, conf, target, bool(semantics.time_col), False, "target_distribution")

        unique = int(y_str.nunique(dropna=True))
        if unique <= 2:
            return TaskInference("binary_classification", 0.85, target, bool(semantics.time_col), False, "target_distribution")
        return TaskInference("multiclass_classification", 0.8, target, bool(semantics.time_col), False, "target_distribution")

    def _conflicting_duplicate_rate(self, df, target_col: str, feature_cols: Sequence[str]) -> Tuple[int, int, Optional[float]]:
        if not feature_cols:
            return 0, 0, None
        work = df[list(feature_cols) + [target_col]].copy()
        if work.empty:
            return 0, 0, None
        sig = work[list(feature_cols)].astype(str).fillna("<NA>").agg("|".join, axis=1)
        tmp = pd.DataFrame({"sig": sig, "target": work[target_col]})
        counts = tmp["sig"].value_counts()
        repeated = counts[counts > 1]
        if repeated.empty:
            return 0, 0, 0.0
        repeated_keys = repeated.index.tolist()
        target_nunique = tmp.groupby("sig")["target"].nunique(dropna=True)
        conflicting = int((target_nunique.loc[repeated_keys] > 1).sum())
        return int(len(repeated_keys)), conflicting, float(conflicting / max(1, len(repeated_keys)))

    def _group_leakage_fraction(self, df, split_col: str, group_col: str) -> Optional[float]:
        part = df[[split_col, group_col]].dropna()
        if part.empty:
            return None
        groups_by_split: Dict[str, set[Any]] = {}
        for split_value, grp in part.groupby(split_col):
            groups_by_split[str(split_value)] = set(grp[group_col].astype(str).tolist())
        if len(groups_by_split) < 2:
            return None
        all_groups = set().union(*groups_by_split.values())
        leaked = set()
        split_names = list(groups_by_split.keys())
        for i, s1 in enumerate(split_names):
            for s2 in split_names[i + 1 :]:
                leaked |= groups_by_split[s1] & groups_by_split[s2]
        return float(len(leaked) / max(1, len(all_groups)))

    def _time_drift_signal(self, df, time_col: str) -> Optional[Dict[str, Any]]:
        if time_col not in df.columns:
            return None
        time_vals = pd.to_datetime(df[time_col], errors="coerce", utc=True)
        part = df.copy()
        part["_time"] = time_vals
        part = part.dropna(subset=["_time"])
        if len(part) < 20:
            return None
        part = part.sort_values("_time")
        mid = len(part) // 2
        early = part.iloc[:mid]
        late = part.iloc[mid:]

        shifted: Dict[str, float] = {}
        for col in part.columns:
            if col in {"_time", time_col}:
                continue
            if not self._is_numeric_series(part[col]):
                continue
            a = pd.to_numeric(early[col], errors="coerce").dropna()
            b = pd.to_numeric(late[col], errors="coerce").dropna()
            if len(a) < 5 or len(b) < 5:
                continue
            std = float(pd.concat([a, b]).std(ddof=0))
            if std <= 0:
                continue
            score = float(abs(a.mean() - b.mean()) / std)
            shifted[col] = score
        if not shifted:
            return {"shifted_feature_count": 0, "max_standardized_shift": 0.0}
        big = {k: v for k, v in shifted.items() if v > 0.5}
        return {
            "shifted_feature_count": len(big),
            "max_standardized_shift": round(max(shifted.values()), 6),
            "shift_scores": {k: round(v, 6) for k, v in shifted.items()},
        }

    def _max_missing_indicator_corr(self, masks: Dict[str, Any]) -> Optional[float]:
        cols = [c for c, m in masks.items() if 0 < float(m.mean()) < 1.0]
        if len(cols) < 2:
            return None
        mat = pd.DataFrame({c: masks[c].astype(int) for c in cols})
        corr = mat.corr().abs()
        vals = []
        for i, c1 in enumerate(corr.columns):
            for c2 in corr.columns[i + 1 :]:
                vals.append(float(corr.loc[c1, c2]))
        return max(vals) if vals else None

    def _target_missingness_signal(
        self,
        df,
        target_col: str,
        masks: Dict[str, Any],
        task: TaskInference,
    ) -> Optional[float]:
        y = df[target_col]
        if y.dropna().empty:
            return None

        best = 0.0
        if task.is_regression() and self._is_numeric_series(y):
            y_num = pd.to_numeric(y, errors="coerce")
            std = float(y_num.std(ddof=0)) if y_num.notna().sum() > 1 else 0.0
            if std <= 0:
                return 0.0
            for col, miss in masks.items():
                if col == target_col or miss.mean() == 0 or miss.mean() == 1:
                    continue
                y_m = y_num[miss].dropna()
                y_p = y_num[~miss].dropna()
                if y_m.empty or y_p.empty:
                    continue
                effect = float(abs(y_m.mean() - y_p.mean()) / std)
                best = max(best, effect)
            return best

        y_cls = y.astype(str)
        for col, miss in masks.items():
            if col == target_col or miss.mean() == 0 or miss.mean() == 1:
                continue
            d1 = y_cls[miss].value_counts(normalize=True)
            d2 = y_cls[~miss].value_counts(normalize=True)
            labels = set(d1.index.tolist()) | set(d2.index.tolist())
            tv = 0.5 * sum(abs(float(d1.get(k, 0.0)) - float(d2.get(k, 0.0))) for k in labels)
            best = max(best, tv)
        return best

    def _split_shift(self, df, split_col: str) -> Dict[str, Any]:
        part = df.dropna(subset=[split_col]).copy()
        part[split_col] = part[split_col].astype(str)
        split_values = part[split_col].value_counts().index.tolist()
        if len(split_values) < 2:
            return {"split_column": split_col, "comparable": False}

        base = split_values[0]
        base_df = part[part[split_col] == base]
        numeric_cols = [c for c in part.columns if c != split_col and self._is_numeric_series(part[c])]

        shifted_features: Dict[str, Dict[str, float]] = {}
        for other in split_values[1:4]:
            other_df = part[part[split_col] == other]
            scores = {}
            for c in numeric_cols[:60]:
                a = pd.to_numeric(base_df[c], errors="coerce").dropna()
                b = pd.to_numeric(other_df[c], errors="coerce").dropna()
                if len(a) < 5 or len(b) < 5:
                    continue
                std = float(pd.concat([a, b]).std(ddof=0))
                if std <= 0:
                    continue
                score = float(abs(a.mean() - b.mean()) / std)
                if score > 0.5:
                    scores[c] = round(score, 6)
            shifted_features[other] = scores

        total_shifted = sum(len(v) for v in shifted_features.values())
        return {
            "split_column": split_col,
            "base_split": base,
            "split_values": split_values[:10],
            "shifted_feature_count": total_shifted,
            "shifted_features_by_split": shifted_features,
        }

    def _duplicate_feature_pairs(self, df) -> List[Tuple[str, str]]:
        pairs: List[Tuple[str, str]] = []
        cols = list(df.columns)
        signatures: Dict[str, str] = {}
        for c in cols:
            sig = "|".join(df[c].astype(str).fillna("<NA>").tolist())
            if sig in signatures:
                pairs.append((signatures[sig], str(c)))
            else:
                signatures[sig] = str(c)
        return pairs

    def _infer_feature_type(self, s) -> str:
        if self._is_bool_like(s):
            return "boolean"
        if self._is_datetime_like(s):
            return "datetime"
        if self._is_numeric_series(s):
            s_num = pd.to_numeric(s, errors="coerce").dropna()
            if s_num.empty:
                return "numeric_unknown"
            unique = int(s_num.nunique(dropna=True))
            integerish = bool((s_num % 1 == 0).all()) if len(s_num) else False
            if integerish and unique <= max(30, int(0.05 * max(1, len(s_num)))):
                return "numeric_discrete"
            return "numeric_continuous"

        non_null = s.dropna()
        if non_null.empty:
            return "unknown"

        values = non_null.tolist()
        if any(isinstance(x, (list, tuple)) for x in values):
            return "sequence"
        if any(isinstance(x, dict) for x in values):
            return "object"

        txt = non_null.astype(str)
        avg_len = float(txt.str.len().mean()) if len(txt) else 0.0
        unique_ratio = float(txt.nunique() / max(1, len(txt)))
        if avg_len > 40 or (avg_len > 16 and unique_ratio > 0.6):
            return "text"
        return "categorical_nominal"

    def _missing_mask(self, s):
        miss = s.isna()
        if str(s.dtype) in {"object", "string"}:
            miss = miss | s.astype(str).str.strip().eq("")
        return miss

    def _iqr_outlier_rate(self, s) -> Optional[float]:
        if s is None or len(s) < 8:
            return None
        q1 = float(s.quantile(0.25))
        q3 = float(s.quantile(0.75))
        iqr = q3 - q1
        if iqr <= 0:
            return 0.0
        lo = q1 - 1.5 * iqr
        hi = q3 + 1.5 * iqr
        return float(((s < lo) | (s > hi)).mean())

    def _is_numeric_series(self, s) -> bool:
        try:
            if pd.api.types.is_bool_dtype(s):
                return False
            return bool(pd.api.types.is_numeric_dtype(s))
        except Exception:
            return False

    def _is_bool_like(self, s) -> bool:
        try:
            if pd.api.types.is_bool_dtype(s):
                return True
            vals = s.dropna().astype(str).str.lower().unique().tolist()
            allowed = {"0", "1", "true", "false", "yes", "no"}
            return bool(vals) and set(vals).issubset(allowed)
        except Exception:
            return False

    def _is_datetime_like(self, s) -> bool:
        if pd.api.types.is_datetime64_any_dtype(s):
            return True
        non_null = s.dropna()
        if len(non_null) < 5:
            return False
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            parsed = pd.to_datetime(non_null.iloc[:200], errors="coerce", utc=True)
        return float(parsed.notna().mean()) >= 0.8

    def _looks_multilabel(self, s) -> bool:
        sample = s.astype(str).head(200)
        if sample.empty:
            return False
        sep_hits = sample.str.contains(r"[,\|;]").mean()
        return float(sep_hits) >= 0.6

    def _pick_col(self, cols: Sequence[str], explicit: Optional[str], candidates: Sequence[str]) -> Optional[str]:
        if explicit:
            matched = self._match_col(cols, explicit)
            if matched:
                return matched
        for cand in candidates:
            matched = self._match_col(cols, cand)
            if matched:
                return matched
        return None

    def _match_col(self, cols: Sequence[str], name: str) -> Optional[str]:
        n = self._norm(name)
        for c in cols:
            if self._norm(c) == n:
                return c
        return None

    def _norm(self, s: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")

    def _all_needs_input(self, reason: str) -> List[DiagnosticFinding]:
        out: List[DiagnosticFinding] = []
        for key, title in VITAL_TITLES:
            out.append(
                DiagnosticFinding(
                    key=key,
                    title=title,
                    status="needs_input",
                    confidence=0.0,
                    summary=reason,
                )
            )
        return out

    def _infer_target_column(self, df, id_cols: Sequence[str], excluded: set[Optional[str]]) -> Optional[str]:
        excluded_cols = {c for c in excluded if c is not None}
        excluded_cols |= set(id_cols)
        candidates: List[Tuple[float, str]] = []

        for col in [str(c) for c in df.columns]:
            if col in excluded_cols:
                continue

            s = df[col]
            non_null = s.dropna()
            if non_null.empty:
                continue

            name = self._norm(col)
            unique = int(non_null.nunique(dropna=True))
            n = int(len(non_null))
            score = 0.0

            if name in {"target", "label", "y"}:
                score += 8.0
            if any(tok in name for tok in ("target", "label", "class", "outcome", "response", "status", "unstable")):
                score += 4.0
            if re.match(r"^f\d+$", name):
                score -= 3.0
            if name in {"split", "fold"} or "time" in name or "date" in name:
                score -= 4.0
            if name.endswith("_id") or name in {"id", "row_id", "entity_id"}:
                score -= 6.0

            if self._is_bool_like(s):
                score += 3.0
            elif self._is_numeric_series(s):
                score += 1.0
                if unique <= 2:
                    score += 2.5
                elif unique <= max(10, int(0.02 * max(1, n))):
                    score += 1.2
                elif unique >= int(0.6 * max(1, n)):
                    score -= 2.0
            else:
                if unique <= max(20, int(0.08 * max(1, n))):
                    score += 1.8
                elif unique >= int(0.8 * max(1, n)):
                    score -= 2.0

            if unique <= 1:
                score -= 5.0

            candidates.append((score, col))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_col = candidates[0]
        if best_score < 2.5:
            return None
        return best_col
