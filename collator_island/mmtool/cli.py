from __future__ import annotations

import argparse
from pathlib import Path

from .db import SnippetDB, build_db
from .generate import generate_project


def _cmd_init_db(args: argparse.Namespace) -> None:
    txt_store = Path(args.txt_store)
    db_path = Path(args.db)
    build_db(txt_store, db_path)
    print(f"Initialized snippet DB: {db_path}")


def _cmd_list(args: argparse.Namespace) -> None:
    db = SnippetDB(db_path=Path(args.db), txt_root=Path(args.txt_store))
    for name in db.list(prefix=args.prefix):
        print(name)


def _cmd_generate(args: argparse.Namespace) -> None:
    generate_project(
        project_file=Path(args.project),
        txt_store=Path(args.txt_store),
        db_path=Path(args.db),
        out_dir=Path(args.out),
        force=args.force,
        pipeline_config_format=args.pipeline_config_format,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mmtool",
        description="Prototype: config-driven pipeline generator using sqlite snippet registry.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_db = sub.add_parser("init-db", help="Scan txt_store and build snippets sqlite DB")
    p_db.add_argument(
        "--txt-store", default="txt_store", help="Directory of .txt snippets"
    )
    p_db.add_argument("--db", default="snippets.sqlite", help="Path to sqlite DB")
    p_db.set_defaults(func=_cmd_init_db)

    p_ls = sub.add_parser(
        "list-snippets", help="List snippets available in the sqlite DB"
    )
    p_ls.add_argument("--db", default="snippets.sqlite")
    p_ls.add_argument("--txt-store", default="txt_store")
    p_ls.add_argument("--prefix", default=None)
    p_ls.set_defaults(func=_cmd_list)

    p_gen = sub.add_parser(
        "generate", help="Generate pipeline directories from a project config"
    )
    p_gen.add_argument(
        "--project",
        "--project-yaml",
        dest="project",
        required=True,
        help="Project config defining pipelines (.toml or .yaml/.yml)",
    )
    p_gen.add_argument(
        "--txt-store", default="txt_store", help="Directory of .txt snippets"
    )
    p_gen.add_argument("--db", default="snippets.sqlite", help="Path to sqlite DB")
    p_gen.add_argument("--out", default="dist", help="Output directory")
    p_gen.add_argument(
        "--force", action="store_true", help="Overwrite existing pipelines"
    )
    p_gen.add_argument(
        "--pipeline-config-format",
        choices=["toml", "yaml"],
        default="toml",
        help="Format to write each generated pipeline config (default: toml)",
    )
    p_gen.set_defaults(func=_cmd_generate)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
