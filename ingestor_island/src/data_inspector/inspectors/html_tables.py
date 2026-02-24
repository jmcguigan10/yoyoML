from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import DataSource, PathSource
from .base import BaseInspector

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore


class _TableCountingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "table":
            self.tables += 1


class HtmlInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
        if truncated:
            warnings.append(f"Loaded only first {ctx.max_bytes_to_load:,} bytes.")

        text = data.decode("utf-8", errors="replace")

        # Always at least count tables
        parser = _TableCountingParser()
        try:
            parser.feed(text)
        except Exception:
            pass

        summary: Dict[str, Any] = {
            "format": "html",
            "tables_count": parser.tables,
        }

        if pd is None:
            warnings.append("pandas not installed, so HTML table extraction is disabled.")
            return summary, warnings

        try:
            # pandas.read_html wants a file path or a string of html
            import io
            tables = pd.read_html(io.StringIO(text))
            table_summaries = []
            for i, t in enumerate(tables[: min(len(tables), 10)]):
                if t.shape[1] > ctx.max_cols:
                    t_disp = t.iloc[:, : ctx.max_cols]
                    warnings.append(f"Table {i}: showing only first {ctx.max_cols} columns.")
                else:
                    t_disp = t
                table_summaries.append(
                    {
                        "index": i,
                        "shape": {"rows": int(t.shape[0]), "cols": int(t.shape[1])},
                        "columns": [str(c) for c in list(t.columns)[: ctx.max_cols]],
                        "sample_rows": t_disp.head(ctx.max_rows).to_dict(orient="records"),
                    }
                )
            summary["tables"] = table_summaries
        except Exception as e:
            warnings.append(f"pandas.read_html failed: {e.__class__.__name__}: {e}")

        return summary, warnings
