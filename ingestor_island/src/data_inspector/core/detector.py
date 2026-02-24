from __future__ import annotations

import configparser
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from .context import InspectionContext
from .report import DetectionResult
from .source import DataSource, PathSource

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


MAGIC_GZIP = b"\x1f\x8b"
MAGIC_BZ2 = b"BZh"
MAGIC_ZIP = b"PK"
MAGIC_SQLITE = b"SQLite format 3\x00"
MAGIC_PARQUET = b"PAR1"


_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class FileTypeDetector:
    """Heuristic detector for common data-ish file types."""

    def detect(self, source: DataSource, ctx: InspectionContext) -> DetectionResult:
        sample = self._read_sample(source, ctx.max_bytes_to_sniff)
        suffix = source.suffix_lower()

        # 1) Magic bytes first (fast + reliable)
        if sample.startswith(MAGIC_GZIP) or suffix == ".gz":
            return DetectionResult("gzip", 0.95, "gzip magic bytes or .gz extension")
        if sample.startswith(MAGIC_BZ2) or suffix in {".bz2", ".bzip2"}:
            return DetectionResult("bzip2", 0.95, "bzip2 magic bytes or .bz2 extension")
        if sample.startswith(MAGIC_SQLITE) or suffix in {".sqlite", ".db", ".sqlite3"}:
            return DetectionResult("sqlite", 0.95, "SQLite header or typical extension")
        if sample.startswith(MAGIC_PARQUET) or suffix == ".parquet":
            return DetectionResult("parquet", 0.9, "Parquet magic bytes or .parquet extension")
        if sample.startswith(MAGIC_ZIP) or suffix in {".zip", ".npz"}:
            # NumPy .npz is a ZIP container of .npy members.
            npz = self._zip_looks_like_npz(source, ctx)
            if suffix == ".npz":
                if npz:
                    return DetectionResult("npz", 0.97, ".npz extension and ZIP with .npy members", details=npz)
                return DetectionResult("npz", 0.85, ".npz extension (ZIP container)")

            if npz:
                return DetectionResult("npz", 0.88, "ZIP container with .npy members", details=npz)

            # Might be xlsx (zip container)
            xlsx = self._zip_looks_like_xlsx(source, ctx)
            if xlsx:
                return DetectionResult("xlsx", 0.95, "ZIP container with Excel workbook structure", details=xlsx)
            return DetectionResult("zip", 0.9, "ZIP magic bytes or .zip extension")

        if suffix in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
            return DetectionResult("xlsx", 0.9, "Excel extension")

        # 2) Binary vs text check
        is_binary = self._looks_binary(sample)
        if is_binary:
            # Some common binary-ish data formats we can at least label
            if suffix in {".pkl", ".pickle"}:
                return DetectionResult("pickle", 0.8, "Pickle extension (not loaded by default for safety)")
            if suffix in {".feather"}:
                return DetectionResult("feather", 0.8, "Feather extension")
            if suffix in {".avro"}:
                return DetectionResult("avro", 0.8, "Avro extension")
            return DetectionResult("binary", 0.7, "High proportion of non-text bytes")

        text = self._decode_text(sample)
        head = text.lstrip()

        # 3) Structured text formats: JSON / JSONL / YAML / XML / HTML / INI
        if suffix in {".jsonl", ".ndjson"}:
            ok, details = self._sniff_jsonl(text)
            if ok:
                return DetectionResult("jsonl", 0.95, "Extension indicates JSONL and lines parse as JSON", details=details)

        if head.startswith("{") or head.startswith("[") or suffix == ".json":
            ok, details = self._sniff_json(text)
            if ok:
                conf = 0.95 if suffix == ".json" else 0.85
                return DetectionResult("json", conf, "Looks like JSON and parses", details=details)

        # JSONL without extension
        ok_jsonl, details_jsonl = self._sniff_jsonl(text)
        if ok_jsonl:
            return DetectionResult("jsonl", 0.85, "Multiple lines parse as JSON objects", details=details_jsonl)

        if suffix in {".yaml", ".yml"} and yaml is not None:
            ok, details = self._sniff_yaml(text)
            if ok:
                return DetectionResult("yaml", 0.95, "YAML extension and safe_load succeeds", details=details)

        # YAML without extension (careful: YAML is permissive)
        if yaml is not None and self._probably_yaml(text):
            ok, details = self._sniff_yaml(text)
            if ok:
                return DetectionResult("yaml", 0.75, "Heuristics suggest YAML and safe_load succeeds", details=details)

        if head.startswith("<?xml") or (head.startswith("<") and suffix == ".xml"):
            ok, details = self._sniff_xml(text)
            if ok:
                return DetectionResult("xml", 0.9, "Looks like XML and parses", details=details)

        if "<html" in head[:2048].lower() or suffix in {".html", ".htm"} or "<table" in head[:2048].lower():
            # We'll label as html if it smells like it; parsing is done by inspector
            return DetectionResult("html", 0.8, "Contains HTML-ish tags or .html extension")

        if suffix == ".ini" or self._probably_ini(text):
            ok, details = self._sniff_ini(text)
            if ok:
                return DetectionResult("ini", 0.8 if suffix != ".ini" else 0.95, "INI-like structure and parses", details=details)

        # 4) Delimited tables (csv/tsv/semicolon/pipe)
        ok_delim, details_delim = self._sniff_delimited(text, suffix)
        if ok_delim:
            ft = details_delim.get("kind", "delimited")
            conf = 0.95 if suffix in {".csv", ".tsv"} else 0.8
            return DetectionResult(str(ft), conf, "Looks like delimited tabular text", details=details_delim)

        # 5) Key-value text
        if self._looks_like_kv(text):
            return DetectionResult("text_kv", 0.65, "Many lines look like key=value or key: value")

        # 6) Plain text fallback
        return DetectionResult("text", 0.55, "Decodes as text but no stronger structure detected")

    # -------------------------
    # Helpers
    # -------------------------
    def _read_sample(self, source: DataSource, n: int) -> bytes:
        with source.open_binary() as f:
            return f.read(n)

    def _decode_text(self, b: bytes) -> str:
        # UTF-8 first; if that fails badly it'll still replace.
        return b.decode("utf-8", errors="replace")

    def _looks_binary(self, b: bytes) -> bool:
        if not b:
            return False
        if b"\x00" in b:
            return True
        # crude non-text ratio
        text_like = sum(1 for x in b if 9 <= x <= 13 or 32 <= x <= 126)
        ratio = text_like / max(1, len(b))
        return ratio < 0.70

    def _zip_looks_like_xlsx(self, source: DataSource, ctx: InspectionContext) -> Optional[dict[str, Any]]:
        try:
            if isinstance(source, PathSource):
                zf = zipfile.ZipFile(str(source.path))
            else:
                with source.open_binary() as f:
                    # zipfile needs seekable; read into memory up to limit
                    data = f.read(ctx.max_bytes_to_load)
                zf = zipfile.ZipFile(io.BytesIO(data))
            with zf:
                names = set(zf.namelist())
                is_xlsx = "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names)
                if not is_xlsx:
                    return None
                return {
                    "members": len(names),
                    "has_workbook": "xl/workbook.xml" in names,
                }
        except Exception:
            return None

    def _zip_looks_like_npz(self, source: DataSource, ctx: InspectionContext) -> Optional[dict[str, Any]]:
        try:
            if isinstance(source, PathSource):
                zf = zipfile.ZipFile(str(source.path))
            else:
                with source.open_binary() as f:
                    data = f.read(ctx.max_bytes_to_load)
                zf = zipfile.ZipFile(io.BytesIO(data))
            with zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                if not names:
                    return None
                npy_members = [n for n in names if n.lower().endswith(".npy")]
                if not npy_members:
                    return None
                if len(npy_members) != len(names):
                    return None
                return {
                    "members": len(names),
                    "npy_members": len(npy_members),
                    "sample_members": npy_members[: min(5, len(npy_members))],
                }
        except Exception:
            return None

    def _sniff_json(self, text: str) -> Tuple[bool, dict[str, Any]]:
        try:
            obj = json.loads(text)
            return True, {"top_level": type(obj).__name__}
        except Exception:
            return False, {}

    def _sniff_jsonl(self, text: str) -> Tuple[bool, dict[str, Any]]:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return False, {}
        parsed = 0
        for ln in lines[: min(20, len(lines))]:
            try:
                json.loads(ln)
                parsed += 1
            except Exception:
                pass
        if parsed >= max(2, int(0.8 * min(20, len(lines)))):
            return True, {"tested_lines": min(20, len(lines)), "parsed": parsed}
        return False, {}

    def _probably_yaml(self, text: str) -> bool:
        # YAML is annoyingly permissive; we only attempt if there are strong hints.
        t = text.lstrip()
        if t.startswith("---"):
            return True
        if re.search(r"^\w[\w\-]*:\s+", text, flags=re.MULTILINE):
            return True
        if re.search(r"^\-\s+\w", text, flags=re.MULTILINE):
            return True
        return False

    def _sniff_yaml(self, text: str) -> Tuple[bool, dict[str, Any]]:
        if yaml is None:
            return False, {}
        try:
            obj = yaml.safe_load(text)
            return True, {"top_level": type(obj).__name__}
        except Exception:
            return False, {}

    def _sniff_xml(self, text: str) -> Tuple[bool, dict[str, Any]]:
        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(text)
            return True, {"root_tag": root.tag}
        except Exception:
            return False, {}

    def _probably_ini(self, text: str) -> bool:
        if re.search(r"^\[[^\]]+\]\s*$", text, flags=re.MULTILINE):
            return True
        if re.search(r"^\w[\w\-\.]*\s*=\s*.+$", text, flags=re.MULTILINE):
            return True
        return False

    def _sniff_ini(self, text: str) -> Tuple[bool, dict[str, Any]]:
        parser = configparser.ConfigParser()
        try:
            parser.read_string(text)
            return True, {"sections": parser.sections()}
        except Exception:
            return False, {}

    def _sniff_delimited(self, text: str, suffix: str) -> Tuple[bool, dict[str, Any]]:
        import csv

        # take a few lines
        lines = [ln for ln in text.splitlines() if ln.strip()][:50]
        if len(lines) < 2:
            return False, {}

        sample = "\n".join(lines)

        # If extension strongly suggests delimiter, try it first
        preferred = None
        kind = "delimited"
        if suffix == ".csv":
            preferred = ","
            kind = "csv"
        elif suffix == ".tsv":
            preferred = "\t"
            kind = "tsv"

        candidates = [preferred] if preferred else []
        candidates += [",", "\t", ";", "|"]
        candidates = [c for c in candidates if c is not None]
        candidates_unique = []
        for c in candidates:
            if c not in candidates_unique:
                candidates_unique.append(c)

        best = None
        for delim in candidates_unique:
            try:
                reader = csv.reader(lines, delimiter=delim)
                rows = list(reader)
                widths = [len(r) for r in rows if r]
                if not widths:
                    continue
                # require some consistency
                common = max(set(widths), key=widths.count)
                consistency = widths.count(common) / len(widths)
                if common >= 2 and consistency >= 0.8:
                    score = common * consistency
                    if best is None or score > best[0]:
                        best = (score, delim, common, consistency)
            except Exception:
                continue

        if not best:
            # Try csv.Sniffer as a fallback
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
                delim = dialect.delimiter
                return True, {
                    "delimiter": delim,
                    "kind": kind if kind != "delimited" else "delimited",
                    "method": "csv.Sniffer",
                }
            except Exception:
                return False, {}

        _, delim, width, consistency = best
        details: dict[str, Any] = {
            "delimiter": delim,
            "approx_columns": width,
            "consistency": round(consistency, 3),
            "method": "heuristic",
        }
        if suffix in {".csv", ".tsv"}:
            details["kind"] = kind
        else:
            details["kind"] = "delimited"

        # header guess: first row has fewer numeric-only cells
        try:
            import re as _re
            first = next(csv.reader([lines[0]], delimiter=delim))
            second = next(csv.reader([lines[1]], delimiter=delim))
            num = lambda x: bool(_re.match(r"^[\+\-]?(\d+(\.\d+)?|\.\d+)$", x.strip()))
            first_nums = sum(1 for c in first if num(c))
            second_nums = sum(1 for c in second if num(c))
            details["has_header_guess"] = first_nums < second_nums
        except Exception:
            pass

        return True, details

    def _looks_like_kv(self, text: str) -> bool:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 3:
            return False
        kv = 0
        for ln in lines[:50]:
            if re.match(r"^\s*[A-Za-z0-9_.\-]+\s*[:=]\s*.+$", ln):
                kv += 1
        return kv / min(50, len(lines)) >= 0.6
