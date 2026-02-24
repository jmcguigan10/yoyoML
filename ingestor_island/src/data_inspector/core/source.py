from __future__ import annotations

import io
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Optional


class DataSource:
    """Abstract data source."""

    @property
    def display_name(self) -> str:
        raise NotImplementedError

    @contextmanager
    def open_binary(self) -> Iterator[BinaryIO]:
        raise NotImplementedError

    def suffix_lower(self) -> str:
        return ""


@dataclass(frozen=True)
class PathSource(DataSource):
    path: Path

    @property
    def display_name(self) -> str:
        return str(self.path)

    @contextmanager
    def open_binary(self) -> Iterator[BinaryIO]:
        with self.path.open("rb") as f:
            yield f

    def suffix_lower(self) -> str:
        return self.path.suffix.lower()


@dataclass(frozen=True)
class BytesSource(DataSource):
    name: str
    data: bytes
    suffix: str = ""

    @property
    def display_name(self) -> str:
        return self.name

    @contextmanager
    def open_binary(self) -> Iterator[BinaryIO]:
        yield io.BytesIO(self.data)

    def suffix_lower(self) -> str:
        return self.suffix.lower()
