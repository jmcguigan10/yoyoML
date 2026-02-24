from __future__ import annotations

import io
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult, InspectionReport
from ..core.source import DataSource, PathSource
from ..core.tabular_profile import TabularProfile

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


TABULAR_TYPES = {"csv", "tsv", "delimited", "jsonl", "json", "yaml", "xlsx", "sqlite", "html", "npz"}


@dataclass
class TabularProfiler:
    """Build a canonical tabular profile from a file or inspector summary."""

    def build(
        self,
        source: DataSource,
        detection: DetectionResult,
        report: InspectionReport,
        ctx: InspectionContext,
    ) -> Optional[TabularProfile]:
        if pd is None:
            return None

        # Prefer reading from source so diagnostics are based on a larger, consistent sample.
        profile = self._build_from_source(source, detection, report, ctx)
        if profile is not None:
            return profile

        # Fallback for nested containers / parse failures: derive what we can from report summary.
        return self._build_from_summary(report.display_name, detection.file_type, report.summary, ctx)

    def _build_from_source(
        self,
        source: DataSource,
        detection: DetectionResult,
        report: InspectionReport,
        ctx: InspectionContext,
    ) -> Optional[TabularProfile]:
        file_type = detection.file_type
        warnings: List[str] = []

        try:
            if file_type in {"csv", "tsv", "delimited"}:
                profile = self._from_delimited_source(source, detection, report, ctx)
            elif file_type == "jsonl":
                profile = self._from_jsonl_source(source, detection, ctx)
            elif file_type == "json":
                profile = self._from_json_source(source, detection, ctx)
            elif file_type == "yaml":
                profile = self._from_yaml_source(source, detection, ctx)
            elif file_type == "xlsx":
                profile = self._from_xlsx_source(source, detection, ctx)
            elif file_type == "sqlite":
                profile = self._from_sqlite_source(source, detection, ctx)
            elif file_type == "html":
                profile = self._from_html_source(source, detection, ctx)
            else:
                return None
        except Exception as e:
            warnings.append(f"Tabular profiling from source failed: {e.__class__.__name__}: {e}")
            profile = None

        if profile is None:
            return None
        profile.parse_warnings.extend(warnings)
        profile.dataframe = self._sanitize_dataframe(profile.dataframe, ctx)
        return profile

    def _from_delimited_source(
        self,
        source: DataSource,
        detection: DetectionResult,
        report: InspectionReport,
        ctx: InspectionContext,
    ) -> Optional[TabularProfile]:
        delimiter = detection.details.get("delimiter")
        if not delimiter:
            delimiter = "\t" if detection.file_type == "tsv" else ","

        kwargs = {
            "sep": delimiter,
            "engine": "python",
            "nrows": ctx.max_profile_rows,
        }

        if isinstance(source, PathSource):
            df = pd.read_csv(source.path, **kwargs)
        else:
            data = self._read_bytes(source, ctx.max_bytes_to_load)
            df = pd.read_csv(io.BytesIO(data), **kwargs)

        approx_total_rows = None
        approx_lines = report.summary.get("approx_total_lines")
        if isinstance(approx_lines, int):
            approx_total_rows = max(0, approx_lines - 1)

        return TabularProfile(
            source_name=source.display_name,
            detection_type=detection.file_type,
            dataframe=df,
            approx_total_rows=approx_total_rows,
            metadata={"delimiter": delimiter},
        )

    def _from_jsonl_source(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Optional[TabularProfile]:
        raw = self._read_bytes(source, ctx.max_bytes_to_load)
        lines = [ln for ln in raw.decode("utf-8", errors="replace").splitlines() if ln.strip()]

        rows: List[Dict[str, Any]] = []
        for ln in lines[: ctx.max_profile_rows]:
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)

        if not rows:
            return None
        return TabularProfile(source_name=source.display_name, detection_type=detection.file_type, dataframe=pd.DataFrame(rows))

    def _from_json_source(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Optional[TabularProfile]:
        raw = self._read_bytes(source, ctx.max_bytes_to_load)
        obj = json.loads(raw.decode("utf-8", errors="replace"))

        if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
            return TabularProfile(
                source_name=source.display_name,
                detection_type=detection.file_type,
                dataframe=pd.DataFrame(obj[: ctx.max_profile_rows]),
            )
        return None

    def _from_yaml_source(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Optional[TabularProfile]:
        if yaml is None:
            return None
        raw = self._read_bytes(source, ctx.max_bytes_to_load)
        obj = yaml.safe_load(raw.decode("utf-8", errors="replace"))
        if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
            return TabularProfile(
                source_name=source.display_name,
                detection_type=detection.file_type,
                dataframe=pd.DataFrame(obj[: ctx.max_profile_rows]),
            )
        return None

    def _from_xlsx_source(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Optional[TabularProfile]:
        if isinstance(source, PathSource):
            sheets = pd.read_excel(source.path, sheet_name=None, nrows=ctx.max_profile_rows, engine="openpyxl")
        else:
            raw = self._read_bytes(source, ctx.max_bytes_to_load)
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None, nrows=ctx.max_profile_rows, engine="openpyxl")
        if not sheets:
            return None
        first_name = next(iter(sheets))
        return TabularProfile(
            source_name=source.display_name,
            detection_type=detection.file_type,
            dataframe=sheets[first_name],
            table_name=str(first_name),
            metadata={"sheet_count": len(sheets)},
        )

    def _from_sqlite_source(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Optional[TabularProfile]:
        tmp_path = None
        try:
            if isinstance(source, PathSource):
                db_path = str(source.path)
            else:
                raw = self._read_bytes(source, ctx.max_bytes_to_load)
                fd, tmp_path = tempfile.mkstemp(suffix=".sqlite")
                import os

                os.close(fd)
                with open(tmp_path, "wb") as out:
                    out.write(raw)
                db_path = tmp_path

            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name LIMIT 1;"
            )
            row = cur.fetchone()
            if not row:
                conn.close()
                return None
            table_name = str(row[0])
            safe_name = table_name.replace("'", "''")

            total_rows = None
            try:
                cur.execute(f"SELECT COUNT(*) FROM '{safe_name}';")
                total_rows = int(cur.fetchone()[0])
            except Exception:
                pass

            q = f"SELECT * FROM '{safe_name}' LIMIT {int(ctx.max_profile_rows)};"
            df = pd.read_sql_query(q, conn)
            conn.close()

            return TabularProfile(
                source_name=source.display_name,
                detection_type=detection.file_type,
                dataframe=df,
                table_name=table_name,
                approx_total_rows=total_rows,
            )
        finally:
            if tmp_path:
                try:
                    import os

                    os.remove(tmp_path)
                except Exception:
                    pass

    def _from_html_source(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Optional[TabularProfile]:
        raw = self._read_bytes(source, ctx.max_bytes_to_load)
        text = raw.decode("utf-8", errors="replace")
        tables = pd.read_html(io.StringIO(text))
        if not tables:
            return None
        df = tables[0].head(ctx.max_profile_rows)
        return TabularProfile(
            source_name=source.display_name,
            detection_type=detection.file_type,
            dataframe=df,
            table_name="table_0",
            metadata={"tables_detected": len(tables)},
        )

    def _build_from_summary(
        self,
        source_name: str,
        file_type: str,
        summary: Dict[str, Any],
        ctx: InspectionContext,
    ) -> Optional[TabularProfile]:
        if pd is None:
            return None
        if not summary:
            return None

        if file_type in {"gzip", "bzip2"} and isinstance(summary.get("inner"), dict):
            inner = summary["inner"]
            detection = inner.get("detection", {})
            inner_type = detection.get("file_type", "unknown")
            inner_summary = inner.get("summary", {})
            profile = self._build_from_summary(source_name, inner_type, inner_summary, ctx)
            if profile is not None:
                profile.parse_warnings.append(
                    "Profile built from compressed-inner summary (lower confidence than direct parsing)."
                )
            return profile

        if file_type == "zip":
            members = summary.get("inspected_members", [])
            if isinstance(members, list):
                for member in members:
                    if not isinstance(member, dict):
                        continue
                    detection = member.get("detection", {})
                    member_type = detection.get("file_type", "unknown")
                    member_summary = member.get("summary", {})
                    profile = self._build_from_summary(source_name, member_type, member_summary, ctx)
                    if profile is not None:
                        profile.parse_warnings.append(
                            "Profile built from ZIP member summary (lower confidence than direct parsing)."
                        )
                        return profile
            return None

        rows, table_name, approx_total_rows = self._rows_from_summary(file_type, summary, ctx.max_profile_rows)
        if not rows:
            return None
        df = pd.DataFrame(rows)
        if df.empty:
            return None
        return TabularProfile(
            source_name=source_name,
            detection_type=file_type,
            dataframe=self._sanitize_dataframe(df, ctx),
            table_name=table_name,
            approx_total_rows=approx_total_rows,
            parse_warnings=["Profile built from inspector summary sample rows."],
        )

    def _rows_from_summary(
        self,
        file_type: str,
        summary: Dict[str, Any],
        max_rows: int,
    ) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[int]]:
        if file_type in {"csv", "tsv", "delimited"} and isinstance(summary.get("sample_rows"), list):
            rows = [r for r in summary["sample_rows"] if isinstance(r, dict)]
            approx = summary.get("approx_total_lines")
            if isinstance(approx, int):
                approx = max(0, approx - 1)
            return rows[:max_rows], None, approx

        if file_type == "jsonl" and isinstance(summary.get("sample_items"), list):
            rows = [r for r in summary["sample_items"] if isinstance(r, dict)]
            return rows[:max_rows], None, None

        if file_type in {"json", "yaml"} and isinstance(summary.get("sample_items"), list):
            rows = [r for r in summary["sample_items"] if isinstance(r, dict)]
            return rows[:max_rows], None, None

        if file_type == "xlsx" and isinstance(summary.get("sheets"), list):
            for sheet in summary["sheets"]:
                if not isinstance(sheet, dict):
                    continue
                if isinstance(sheet.get("sample_records"), list):
                    rows = [r for r in sheet["sample_records"] if isinstance(r, dict)]
                    return rows[:max_rows], str(sheet.get("name", "sheet_0")), None
                if isinstance(sheet.get("sample_rows"), list):
                    raw_rows = sheet["sample_rows"]
                    if len(raw_rows) >= 2 and all(isinstance(r, list) for r in raw_rows):
                        header = [str(x) for x in raw_rows[0]]
                        rows: List[Dict[str, Any]] = []
                        for vals in raw_rows[1:max_rows + 1]:
                            if not isinstance(vals, list):
                                continue
                            row = {header[i]: vals[i] if i < len(vals) else None for i in range(len(header))}
                            rows.append(row)
                        if rows:
                            return rows[:max_rows], str(sheet.get("name", "sheet_0")), None
            return [], None, None

        if file_type == "html" and isinstance(summary.get("tables"), list):
            for table in summary["tables"]:
                if not isinstance(table, dict):
                    continue
                rows = table.get("sample_rows")
                if isinstance(rows, list):
                    return [r for r in rows if isinstance(r, dict)][:max_rows], str(table.get("index", "table_0")), None
            return [], None, None

        if file_type == "sqlite" and isinstance(summary.get("objects"), list):
            for obj in summary["objects"]:
                if not isinstance(obj, dict) or obj.get("type") != "table":
                    continue
                rows = obj.get("sample_rows")
                if isinstance(rows, list):
                    approx = obj.get("row_count")
                    approx = int(approx) if isinstance(approx, int) else None
                    return [r for r in rows if isinstance(r, dict)][:max_rows], str(obj.get("name")), approx
            return [], None, None

        if file_type == "npz" and isinstance(summary.get("tabular_preview_rows"), list):
            rows = [r for r in summary["tabular_preview_rows"] if isinstance(r, dict)]
            table_name = None
            preview = summary.get("tabular_preview")
            if isinstance(preview, dict):
                table_name = str(preview.get("feature_array")) if preview.get("feature_array") else None
            return rows[:max_rows], table_name, None

        return [], None, None

    def _sanitize_dataframe(self, df: Any, ctx: InspectionContext):
        if pd is None:
            return df
        if df is None:
            return pd.DataFrame()
        # Normalize column names to strings and cap very wide tables for predictable diagnostics.
        try:
            df = df.copy()
            df.columns = [str(c) for c in list(df.columns)]
            if df.shape[1] > ctx.max_profile_cols:
                df = df.iloc[:, : ctx.max_profile_cols]
            return df
        except Exception:
            return df

    def _read_bytes(self, source: DataSource, limit: int) -> bytes:
        with source.open_binary() as f:
            return f.read(limit)
