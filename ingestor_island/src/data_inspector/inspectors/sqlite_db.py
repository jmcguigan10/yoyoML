from __future__ import annotations

import os
import sqlite3
import tempfile
from typing import Any, Dict, List, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import DataSource, PathSource
from .base import BaseInspector


class SqliteInspector(BaseInspector):
    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        tmp_path = None

        try:
            if isinstance(source, PathSource):
                db_path = str(source.path)
            else:
                # sqlite3 wants a file, so write a temp copy
                with source.open_binary() as f:
                    data = f.read(ctx.max_bytes_to_load)
                fd, tmp_path = tempfile.mkstemp(suffix=".sqlite")
                os.close(fd)
                with open(tmp_path, "wb") as out:
                    out.write(data)
                db_path = tmp_path

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            cur = conn.cursor()
            cur.execute(
                "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name;"
            )
            objs = cur.fetchall()

            objects = []
            for row in objs:
                name = row["name"]
                typ = row["type"]
                sql = row["sql"]
                entry: Dict[str, Any] = {"name": name, "type": typ, "sql": sql}

                safe_name = name.replace("'", "''")

                if typ == "table" and name != "sqlite_sequence":
                    # Schema
                    cur.execute(f"PRAGMA table_info('{safe_name}');")
                    cols = cur.fetchall()
                    entry["columns"] = [
                        {
                            "cid": c["cid"],
                            "name": c["name"],
                            "type": c["type"],
                            "notnull": bool(c["notnull"]),
                            "default": c["dflt_value"],
                            "pk": bool(c["pk"]),
                        }
                        for c in cols
                    ]

                    # Row count (can be slow, but it's sqlite; people use it for small-ish stuff)
                    try:
                        cur.execute(f"SELECT COUNT(*) AS n FROM '{safe_name}';")
                        entry["row_count"] = int(cur.fetchone()[0])
                    except Exception as e:
                        warnings.append(f"Couldn't count rows for {name}: {e.__class__.__name__}: {e}")

                    # Sample rows
                    try:
                        cur.execute(f"SELECT * FROM '{safe_name}' LIMIT {ctx.max_rows};")
                        sample = [dict(r) for r in cur.fetchall()]
                        entry["sample_rows"] = sample
                    except Exception as e:
                        warnings.append(f"Couldn't sample rows for {name}: {e.__class__.__name__}: {e}")

                objects.append(entry)

            summary: Dict[str, Any] = {
                "format": "sqlite",
                "objects": objects,
                "object_count": len(objects),
            }

            conn.close()
            return summary, warnings

        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
