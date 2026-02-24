from __future__ import annotations

import csv
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import BytesSource, DataSource, PathSource
from ..utils.pretty import first_n
from ..utils.text import guess_encoding
from .base import BaseInspector

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore


class DelimitedTextInspector(BaseInspector):
    """CSV/TSV/other-delimited text."""

    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []

        # Read a chunk for encoding guess and maybe fallback parsing
        raw, truncated = self._read_all_bytes_limited(source, min(ctx.max_bytes_to_load, 4 * 1024 * 1024))
        if truncated:
            warnings.append(f"Loaded only first {len(raw):,} bytes for inspection (truncated).")

        enc = guess_encoding(raw[: min(len(raw), 64 * 1024)])
        text = raw.decode(enc, errors="replace")
        delim = detection.details.get("delimiter")
        if not delim:
            if detection.file_type == "tsv":
                delim = "\t"
            else:
                delim = ","

        # Try pandas first if available
        if pd is not None:
            try:
                df = self._read_with_pandas(source, delim, enc, ctx)
                summary = self._summarize_df(df, delim, enc, ctx, raw, warnings)
                return summary, warnings
            except Exception as e:
                warnings.append(f"pandas read_csv failed, falling back to csv module: {e.__class__.__name__}: {e}")

        # Fallback: csv module, sample only
        try:
            rows = self._read_with_csv(text, delim, ctx)
            summary: Dict[str, Any] = {
                "format": "delimited_text",
                "delimiter": delim,
                "encoding": enc,
                "sample_rows": rows,
                "note": "Parsed with Python csv module (pandas not available or failed).",
            }
            # Try to infer header/columns from first row
            if rows:
                summary["columns_guess"] = list(rows[0].keys())
            return summary, warnings
        except Exception as e:
            warnings.append(f"csv parsing failed: {e.__class__.__name__}: {e}")
            return {"format": "delimited_text", "delimiter": delim, "encoding": enc}, warnings

    def _read_with_pandas(self, source: DataSource, delim: str, enc: str, ctx: InspectionContext):
        # Use a file path when we can; pandas handles that well.
        if isinstance(source, PathSource):
            return pd.read_csv(
                source.path,
                sep=delim,
                encoding=enc,
                engine="python",
                nrows=ctx.max_rows,
            )
        # Otherwise read from bytes
        with source.open_binary() as f:
            data = f.read(ctx.max_bytes_to_load)
        import io

        return pd.read_csv(
            io.BytesIO(data),
            sep=delim,
            encoding=enc,
            engine="python",
            nrows=ctx.max_rows,
        )

    def _summarize_df(
        self,
        df,
        delim: str,
        enc: str,
        ctx: InspectionContext,
        raw: bytes,
        warnings: List[str],
    ) -> Dict[str, Any]:
        # Limit columns for display
        if df.shape[1] > ctx.max_cols:
            warnings.append(f"Showing only first {ctx.max_cols} of {df.shape[1]} columns.")
            df_disp = df.iloc[:, : ctx.max_cols]
        else:
            df_disp = df

        dtypes = {c: str(t) for c, t in df_disp.dtypes.items()}
        missing = {c: int(v) for c, v in df_disp.isna().sum().items()}

        sample_rows = df_disp.head(ctx.max_rows).to_dict(orient="records")

        approx_total_lines = None
        # If we already loaded bytes (for archives), we can count newlines cheaply
        try:
            approx_total_lines = raw.count(b"\n")
        except Exception:
            approx_total_lines = None

        return {
            "format": "delimited_text",
            "delimiter": delim,
            "encoding": enc,
            "sample_shape": {"rows": int(df.shape[0]), "cols": int(df.shape[1])},
            "approx_total_lines": approx_total_lines,
            "columns": list(df.columns)[: ctx.max_cols],
            "dtypes": dtypes,
            "missing_in_sample": missing,
            "sample_rows": sample_rows,
        }

    def _read_with_csv(self, text: str, delim: str, ctx: InspectionContext) -> List[Dict[str, Any]]:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        # Use DictReader: assumes first row is header
        reader = csv.DictReader(lines, delimiter=delim)
        out = []
        for i, row in enumerate(reader):
            if i >= ctx.max_rows:
                break
            out.append(dict(row))
        return out
