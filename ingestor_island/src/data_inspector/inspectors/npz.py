from __future__ import annotations

import ast
import io
import re
import struct
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from ..core.context import InspectionContext
from ..core.report import DetectionResult
from ..core.source import DataSource, PathSource
from .base import BaseInspector

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore


class NpzInspector(BaseInspector):
    """Inspector for NumPy .npz archives."""

    def _inspect(
        self, source: DataSource, detection: DetectionResult, ctx: InspectionContext
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        with self._open_zip(source, ctx, warnings) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            npy_infos = [i for i in infos if i.filename.lower().endswith(".npy")]
            non_npy_infos = [i for i in infos if not i.filename.lower().endswith(".npy")]

            arrays: List[Dict[str, Any]] = []
            header_failures = 0
            for info in npy_infos[: ctx.max_archive_members]:
                key = self._strip_npy_suffix(info.filename.rsplit("/", 1)[-1])
                entry: Dict[str, Any] = {
                    "member": info.filename,
                    "key": key,
                    "compressed_size": int(info.compress_size),
                    "uncompressed_size": int(info.file_size),
                }
                try:
                    with zf.open(info.filename) as fh:
                        header = self._read_npy_header(fh)
                    entry.update(header)
                except Exception as e:
                    header_failures += 1
                    entry["header_parse_error"] = f"{e.__class__.__name__}: {e}"
                arrays.append(entry)

            if len(npy_infos) > ctx.max_archive_members:
                warnings.append(
                    f"Listing only first {ctx.max_archive_members} .npy members of {len(npy_infos)}."
                )
            if header_failures:
                warnings.append(f"Could not parse headers for {header_failures} .npy member(s).")
            if non_npy_infos:
                warnings.append(f"Found {len(non_npy_infos)} non-.npy ZIP member(s).")

            summary: Dict[str, Any] = {
                "format": "npz",
                "member_count": len(infos),
                "npy_member_count": len(npy_infos),
                "arrays": arrays,
            }

            if non_npy_infos:
                summary["non_npy_members"] = [
                    {
                        "name": i.filename,
                        "compressed_size": int(i.compress_size),
                        "uncompressed_size": int(i.file_size),
                    }
                    for i in non_npy_infos[:20]
                ]
                if len(non_npy_infos) > 20:
                    warnings.append(f"Showing only first 20 non-.npy members of {len(non_npy_infos)}.")

            preview = self._build_tabular_preview(source, arrays, ctx, warnings)
            if preview:
                summary.update(preview)

            return summary, warnings

    def _open_zip(self, source: DataSource, ctx: InspectionContext, warnings: List[str]) -> zipfile.ZipFile:
        if isinstance(source, PathSource):
            return zipfile.ZipFile(str(source.path))

        data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
        if truncated:
            warnings.append(
                f"Loaded only first {ctx.max_bytes_to_load:,} bytes from in-memory source; archive may be incomplete."
            )
        return zipfile.ZipFile(io.BytesIO(data))

    def _read_npy_header(self, fh) -> Dict[str, Any]:
        magic = fh.read(6)
        if magic != b"\x93NUMPY":
            raise ValueError("not a .npy member (missing NPY magic)")

        version = fh.read(2)
        if len(version) != 2:
            raise ValueError("truncated NPY version header")
        major, minor = version[0], version[1]

        if major == 1:
            raw_len = fh.read(2)
            if len(raw_len) != 2:
                raise ValueError("truncated NPY v1 header length")
            header_len = struct.unpack("<H", raw_len)[0]
        elif major in {2, 3}:
            raw_len = fh.read(4)
            if len(raw_len) != 4:
                raise ValueError("truncated NPY v2/v3 header length")
            header_len = struct.unpack("<I", raw_len)[0]
        else:
            raise ValueError(f"unsupported NPY header version: {major}.{minor}")

        header_bytes = fh.read(header_len)
        if len(header_bytes) != header_len:
            raise ValueError("truncated NPY header payload")
        header_text = header_bytes.decode("latin-1").strip()
        header_obj = ast.literal_eval(header_text)

        descr = str(header_obj.get("descr", ""))
        shape_obj = header_obj.get("shape", ())
        if isinstance(shape_obj, int):
            shape = (int(shape_obj),)
        elif isinstance(shape_obj, tuple):
            shape = tuple(int(x) for x in shape_obj)
        else:
            shape = tuple()

        itemsize = self._dtype_itemsize(descr)
        size = self._shape_size(shape)
        estimated_nbytes = int(size * itemsize) if size is not None and itemsize is not None else None

        return {
            "dtype": descr,
            "shape": list(shape),
            "ndim": int(len(shape)),
            "fortran_order": bool(header_obj.get("fortran_order", False)),
            "estimated_nbytes": estimated_nbytes,
            "npy_version": f"{major}.{minor}",
        }

    def _shape_size(self, shape: Tuple[int, ...]) -> Optional[int]:
        total = 1
        try:
            for dim in shape:
                total *= int(dim)
            return int(total)
        except Exception:
            return None

    def _dtype_itemsize(self, descr: str) -> Optional[int]:
        m = re.match(r"^[<>=|]([A-Za-z])(\d+)$", descr)
        if not m:
            return None
        kind = m.group(1)
        width = int(m.group(2))
        if kind == "U":
            return width * 4
        return width

    def _build_tabular_preview(
        self,
        source: DataSource,
        arrays: List[Dict[str, Any]],
        ctx: InspectionContext,
        warnings: List[str],
    ) -> Optional[Dict[str, Any]]:
        if np is None:
            warnings.append("numpy not installed; skipping .npz array value preview.")
            return None
        if not arrays:
            return None

        feature = self._pick_feature_array(arrays)
        if not feature:
            return None

        est = feature.get("estimated_nbytes")
        if isinstance(est, int) and est > int(ctx.max_bytes_to_load * 3):
            warnings.append(
                "Skipping tabular preview for large array "
                f"'{feature.get('key')}' ({est:,} bytes estimated)."
            )
            return None

        target = self._pick_target_array(arrays, feature)

        try:
            with self._load_npz(source, ctx, warnings) as npz:
                feature_key = str(feature.get("key"))
                if feature_key not in npz.files:
                    return None
                x = np.asarray(npz[feature_key])
                if x.ndim == 1:
                    x = x.reshape(-1, 1)
                if x.ndim != 2:
                    return None

                rows_total = int(x.shape[0])
                cols_total = int(x.shape[1])
                rows_show = min(rows_total, ctx.max_rows)
                cols_show = min(cols_total, ctx.max_cols)

                y = None
                y_name = None
                if target is not None:
                    target_key = str(target.get("key"))
                    if target_key in npz.files:
                        y_arr = np.asarray(npz[target_key])
                        if y_arr.ndim == 2 and y_arr.shape[1] == 1:
                            y_arr = y_arr.reshape(-1)
                        if y_arr.ndim == 1 and y_arr.shape[0] == rows_total:
                            y = y_arr
                            y_name = target_key

                rows: List[Dict[str, Any]] = []
                for r in range(rows_show):
                    row: Dict[str, Any] = {}
                    for c in range(cols_show):
                        row[f"f{c}"] = self._to_py_scalar(x[r, c])
                    if y is not None:
                        row[y_name or "target"] = self._to_py_scalar(y[r])
                    rows.append(row)

                return {
                    "tabular_preview": {
                        "feature_array": feature_key,
                        "feature_shape": [rows_total, cols_total],
                        "feature_columns_previewed": cols_show,
                        "rows_previewed": rows_show,
                        "target_array": y_name,
                    },
                    "tabular_preview_rows": rows,
                }
        except Exception as e:
            warnings.append(f"Failed reading .npz array preview: {e.__class__.__name__}: {e}")
            return None

    def _pick_feature_array(self, arrays: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        candidates = []
        for item in arrays:
            shape = item.get("shape")
            if not isinstance(shape, list) or not shape:
                continue
            if len(shape) == 2 and all(isinstance(x, int) for x in shape):
                rows, cols = int(shape[0]), int(shape[1])
                if rows > 0 and cols > 0:
                    candidates.append((rows * cols, item))
            elif len(shape) == 1 and isinstance(shape[0], int) and shape[0] > 0:
                candidates.append((int(shape[0]), item))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _pick_target_array(
        self,
        arrays: List[Dict[str, Any]],
        feature: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        fshape = feature.get("shape")
        if not isinstance(fshape, list) or not fshape:
            return None
        rows = int(fshape[0]) if isinstance(fshape[0], int) else None
        if rows is None:
            return None

        scored: List[Tuple[int, Dict[str, Any]]] = []
        for item in arrays:
            if item is feature:
                continue
            shape = item.get("shape")
            if not isinstance(shape, list) or not shape:
                continue
            is_row_aligned = False
            if len(shape) == 1 and isinstance(shape[0], int) and int(shape[0]) == rows:
                is_row_aligned = True
            if len(shape) == 2 and len(shape) >= 2 and all(isinstance(x, int) for x in shape[:2]):
                is_row_aligned = int(shape[0]) == rows and int(shape[1]) == 1
            if not is_row_aligned:
                continue

            key = str(item.get("key", "")).lower()
            score = 0
            if any(tok in key for tok in ("y", "target", "label", "outcome", "response")):
                score += 5
            if any(tok in key for tok in ("unstable", "status", "class")):
                score += 2
            scored.append((score, item))

        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def _load_npz(self, source: DataSource, ctx: InspectionContext, warnings: List[str]):
        if isinstance(source, PathSource):
            return np.load(str(source.path), allow_pickle=False)

        data, truncated = self._read_all_bytes_limited(source, ctx.max_bytes_to_load)
        if truncated:
            warnings.append(
                f"Loaded only first {ctx.max_bytes_to_load:,} bytes from in-memory source for numpy.load."
            )
        return np.load(io.BytesIO(data), allow_pickle=False)

    def _strip_npy_suffix(self, name: str) -> str:
        if name.lower().endswith(".npy"):
            return name[:-4]
        return name

    def _to_py_scalar(self, x: Any) -> Any:
        if hasattr(x, "item"):
            try:
                return x.item()
            except Exception:
                return x
        return x
