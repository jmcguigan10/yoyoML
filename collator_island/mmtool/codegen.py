from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

from .assembler import SnippetAssembler
from .db import SnippetDB
from .snippets import Snippet


def assemble_file(
    *,
    db: SnippetDB,
    snippet_keys: Iterable[str],
    out_path: Path,
    module_docstring: Optional[str] = None,
) -> None:
    snippets: List[Snippet] = []
    for key in snippet_keys:
        code = db.get_code(key)
        snippets.append(Snippet(name=key, code=code))

    assembler = SnippetAssembler(snippets, module_docstring=module_docstring)
    assembler.write(out_path)
