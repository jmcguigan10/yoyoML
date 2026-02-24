from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..core.context import InspectionContext
from ..core.report import DetectionResult, InspectionReport
from ..core.source import DataSource
from .base import DiagnosticFinding
from .profiler import TabularProfiler
from .vital import VITAL_TITLES, VitalDiagnostics


@dataclass
class DiagnosticsRunner:
    profiler: TabularProfiler = field(default_factory=TabularProfiler)
    vital: VitalDiagnostics = field(default_factory=VitalDiagnostics)

    @classmethod
    def default(cls) -> "DiagnosticsRunner":
        return cls()

    def apply(
        self,
        source: DataSource,
        detection: DetectionResult,
        report: InspectionReport,
        ctx: InspectionContext,
    ) -> None:
        if not ctx.enable_diagnostics:
            report.diagnostics = {"enabled": False, "reason": "disabled_by_context"}
            return

        profile = self.profiler.build(source, detection, report, ctx)
        if profile is None:
            report.diagnostics = self._empty_payload("No tabular profile could be derived from this source.")
            return

        findings = self.vital.run(profile, ctx)
        finding_dicts = [f.to_dict() for f in findings]
        supported = len([f for f in findings if f.status == "supported"])
        assumptions = self._build_assumptions(finding_dicts, report.summary, ctx)

        report.diagnostics = {
            "enabled": True,
            "profile": {
                "source_name": profile.source_name,
                "detection_type": profile.detection_type,
                "table_name": profile.table_name,
                "rows_profiled": profile.row_count,
                "columns_profiled": profile.col_count,
                "approx_total_rows": profile.approx_total_rows,
                "parse_warnings": profile.parse_warnings,
                "metadata": profile.metadata,
            },
            "coverage": {
                "supported_vital_checks": supported,
                "total_vital_checks": len(VITAL_TITLES),
            },
            "assumptions": assumptions,
            "findings": finding_dicts,
        }

    def _empty_payload(self, reason: str) -> Dict[str, Any]:
        return {
            "enabled": True,
            "coverage": {"supported_vital_checks": 0, "total_vital_checks": len(VITAL_TITLES)},
            "reason": reason,
            "findings": [
                DiagnosticFinding(
                    key=key,
                    title=title,
                    status="needs_input",
                    confidence=0.0,
                    summary=reason,
                ).to_dict()
                for key, title in VITAL_TITLES
            ],
        }

    def _build_assumptions(
        self,
        findings: List[Dict[str, Any]],
        summary: Dict[str, Any],
        ctx: InspectionContext,
    ) -> List[Dict[str, Any]]:
        by_key = {str(f.get("key")): f for f in findings}
        assumptions: List[Dict[str, Any]] = []

        def add(
            *,
            key: str,
            value: Any,
            confidence: float,
            source: str,
            evidence: List[str],
            risk_if_wrong: str,
        ) -> None:
            status = "unresolved"
            if value is not None and value != "":
                status = "auto_accept" if confidence >= ctx.assumption_auto_accept_threshold else "needs_user_verification"
            assumptions.append(
                {
                    "key": key,
                    "value": value,
                    "confidence": round(float(confidence), 3),
                    "status": status,
                    "source": source,
                    "evidence": evidence,
                    "risk_if_wrong": risk_if_wrong,
                }
            )

        problem = by_key.get("problem_type", {})
        problem_ev = problem.get("evidence", {}) if isinstance(problem.get("evidence"), dict) else {}
        task_type = problem_ev.get("task_type")
        task_conf = float(problem.get("confidence", 0.0) or 0.0)
        add(
            key="task_type",
            value=task_type,
            confidence=task_conf,
            source="problem_type",
            evidence=[
                f"task={task_type}" if task_type else "task unresolved",
                f"temporal={problem_ev.get('temporal')}",
                f"inference_source={problem_ev.get('inference_source')}",
            ],
            risk_if_wrong="Wrong model family and evaluation setup.",
        )

        target_f = by_key.get("target_definition", {})
        target_ev = target_f.get("evidence", {}) if isinstance(target_f.get("evidence"), dict) else {}
        target = target_ev.get("target_column") or problem_ev.get("target_column")
        target_conf = max(float(target_f.get("confidence", 0.0) or 0.0), task_conf * 0.9 if target else 0.0)
        add(
            key="target_column",
            value=target,
            confidence=target_conf,
            source="target_definition",
            evidence=[
                f"collision_noise_rate={target_ev.get('collision_noise_rate')}",
                f"leakage_markers={len(target_ev.get('possible_leakage_columns', []) or [])}",
            ],
            risk_if_wrong="Metrics become invalid due to label mismatch/leakage.",
        )

        split_f = by_key.get("data_splitting_structure", {})
        split_ev = split_f.get("evidence", {}) if isinstance(split_f.get("evidence"), dict) else {}
        split_conf = float(split_f.get("confidence", 0.0) or 0.0)
        add(
            key="split_column",
            value=split_ev.get("split_column"),
            confidence=split_conf,
            source="data_splitting_structure",
            evidence=[
                f"structure={split_ev.get('structure')}",
                f"split_values={split_ev.get('split_values_sample')}",
            ],
            risk_if_wrong="Train/validation contamination and optimistic validation scores.",
        )
        add(
            key="time_column",
            value=split_ev.get("time_column"),
            confidence=split_conf if split_ev.get("time_column") else 0.0,
            source="data_splitting_structure",
            evidence=[f"structure={split_ev.get('structure')}"],
            risk_if_wrong="Temporal leakage risk and incorrect drift assumptions.",
        )
        add(
            key="group_column",
            value=split_ev.get("group_column"),
            confidence=split_conf if split_ev.get("group_column") else 0.0,
            source="data_splitting_structure",
            evidence=[f"group_leakage_fraction={split_ev.get('group_leakage_fraction')}"],
            risk_if_wrong="Entity leakage across splits.",
        )

        metric_f = by_key.get("evaluation_metric", {})
        metric_ev = metric_f.get("evidence", {}) if isinstance(metric_f.get("evidence"), dict) else {}
        recommended = metric_ev.get("recommended_metrics")
        metric_value = recommended[0] if isinstance(recommended, list) and recommended else metric_ev.get("metric")
        add(
            key="objective_metric",
            value=metric_value,
            confidence=float(metric_f.get("confidence", 0.0) or 0.0),
            source="evaluation_metric",
            evidence=[f"recommended={recommended}", f"rationale={metric_ev.get('rationale')}"],
            risk_if_wrong="Optimization objective misaligned with deployment cost.",
        )

        # NPZ-specific assumptions from inspector summary.
        if isinstance(summary, dict) and summary.get("format") == "npz":
            preview = summary.get("tabular_preview")
            if isinstance(preview, dict):
                feature_array = preview.get("feature_array")
                target_array = preview.get("target_array")
                add(
                    key="feature_array",
                    value=feature_array,
                    confidence=0.95 if feature_array else 0.0,
                    source="npz_tabular_preview",
                    evidence=[f"shape={preview.get('feature_shape')}", f"rows_previewed={preview.get('rows_previewed')}"],
                    risk_if_wrong="Wrong design matrix selection breaks downstream preprocessing.",
                )
                add(
                    key="target_array",
                    value=target_array,
                    confidence=0.8 if target_array else 0.0,
                    source="npz_tabular_preview",
                    evidence=[f"feature_array={feature_array}", "row-aligned 1D/1-column array heuristic"],
                    risk_if_wrong="Labels may be misaligned or replaced by a feature vector.",
                )

        return assumptions
