from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, List


@dataclass(frozen=True)
class Snippet:
    name: str
    code: str


class SnippetCollection:
    def __init__(self, snippets: Iterable[Snippet] | None = None) -> None:
        self._snippets: List[Snippet] = list(snippets) if snippets else []

    def add(self, snippet: Snippet) -> None:
        self._snippets.append(snippet)

    def extend(self, snippets: Iterable[Snippet]) -> None:
        self._snippets.extend(snippets)

    def __iter__(self) -> Iterator[Snippet]:
        return iter(self._snippets)

    def __len__(self) -> int:
        return len(self._snippets)

    def items(self) -> List[Snippet]:
        return list(self._snippets)
