#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import json
import os
import random
import sqlite3
import string
import zipfile
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook  # type: ignore


def rand_name(rng: random.Random) -> str:
    first = rng.choice(
        ["Ada", "Grace", "Linus", "Ken", "Margaret", "Alan", "Edsger", "Donald", "Barbara", "Guido"]
    )
    last = rng.choice(["Lovelace", "Hopper", "Torvalds", "Thompson", "Hamilton", "Turing", "Dijkstra", "Knuth", "Liskov", "Rossum"])
    return f"{first} {last}"


def generate_people(n: int = 25, seed: int = 7):
    rng = random.Random(seed)
    base = date(2022, 1, 1)
    people = []
    for i in range(1, n + 1):
        person = {
            "id": i,
            "name": rand_name(rng),
            "age": rng.randint(18, 65),
            "height_cm": round(rng.uniform(150, 200), 1),
            "signup_date": str(base + timedelta(days=rng.randint(0, 900))),
            "is_active": rng.choice([True, False]),
            "score": round(rng.random() * 100, 3),
        }
        people.append(person)
    return people


def write_csv(path: Path, rows: list[dict], delimiter: str = ",") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_yaml(path: Path) -> None:
    # Keep it simple so PyYAML isn't required just to generate.
    text = """app:
  name: ExampleApp
  version: 1.2.3
features:
  - ingest
  - validate
  - export
thresholds:
  warn: 0.7
  fail: 0.9
"""
    path.write_text(text, encoding="utf-8")


def write_xml(path: Path, people: list[dict]) -> None:
    parts = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<people>"]
    for p in people:
        parts.append(f"  <person id=\"{p['id']}\">")
        for k, v in p.items():
            if k == "id":
                continue
            parts.append(f"    <{k}>{str(v)}</{k}>")
        parts.append("  </person>")
    parts.append("</people>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_ini(path: Path) -> None:
    text = """\
[general]
name = DataInspector
mode = demo

[paths]
input = ./sample_data
output = ./out

[flags]
recursive = true
"""
    path.write_text(text, encoding="utf-8")


def write_kv_text(path: Path) -> None:
    text = """\
host: localhost
port: 5432
user = demo
password = not_a_real_password
retries: 3
timeout_seconds = 10
"""
    path.write_text(text, encoding="utf-8")


def write_html(path: Path, people: list[dict]) -> None:
    cols = list(people[0].keys())
    rows = []
    for p in people[:10]:
        tds = "".join(f"<td>{p[c]}</td>" for c in cols)
        rows.append(f"<tr>{tds}</tr>")
    html = f"""\
<!doctype html>
<html>
  <head><meta charset=\"utf-8\"><title>People</title></head>
  <body>
    <h1>People</h1>
    <table border=\"1\">
      <thead><tr>{''.join(f'<th>{c}</th>' for c in cols)}</tr></thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_xlsx(path: Path, people: list[dict]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "people"
    cols = list(people[0].keys())
    ws.append(cols)
    for p in people:
        ws.append([p[c] for c in cols])

    ws2 = wb.create_sheet("summary")
    ws2.append(["metric", "value"])
    ws2.append(["count", len(people)])
    ws2.append(["active", sum(1 for p in people if p["is_active"])])

    wb.save(path)


def write_sqlite(path: Path, people: list[dict]) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE people (
            id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            height_cm REAL,
            signup_date TEXT,
            is_active INTEGER,
            score REAL
        );
        """
    )
    cur.executemany(
        "INSERT INTO people (id, name, age, height_cm, signup_date, is_active, score) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                p["id"],
                p["name"],
                p["age"],
                p["height_cm"],
                p["signup_date"],
                1 if p["is_active"] else 0,
                p["score"],
            )
            for p in people
        ],
    )
    cur.execute("CREATE TABLE events (event_id INTEGER PRIMARY KEY, kind TEXT, created_at TEXT)")
    cur.executemany(
        "INSERT INTO events (event_id, kind, created_at) VALUES (?, ?, ?)",
        [(i, random.choice(["login", "purchase", "logout"]), str(date(2024, 1, 1) + timedelta(days=i))) for i in range(1, 51)],
    )
    conn.commit()
    conn.close()


def write_gz_csv(path: Path, people: list[dict]) -> None:
    # write CSV to bytes then gzip
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(people[0].keys()))
    writer.writeheader()
    writer.writerows(people)
    raw = buf.getvalue().encode("utf-8")

    with gzip.open(path, "wb") as f:
        f.write(raw)


def write_random_binary(path: Path, n: int = 2048, seed: int = 99) -> None:
    rng = random.Random(seed)
    b = bytes(rng.randint(0, 255) for _ in range(n))
    path.write_bytes(b)


def write_archive(path: Path, base_dir: Path, members: list[str]) -> None:
    if path.exists():
        path.unlink()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for m in members:
            zf.write(base_dir / m, arcname=m)


def main() -> int:
    out = Path(__file__).resolve().parents[1] / "sample_data"
    out.mkdir(parents=True, exist_ok=True)

    people = generate_people()

    write_csv(out / "people.csv", people, delimiter=",")
    write_csv(out / "people.tsv", people, delimiter="\t")
    write_csv(out / "people_semicolon.csv", people, delimiter=";")

    write_json(out / "records.json", people)
    write_jsonl(out / "records.jsonl", people)
    write_json(
        out / "nested.json",
        {
            "meta": {"generated": True, "count": len(people)},
            "people": people[:5],
            "stats": {"min_age": min(p["age"] for p in people), "max_age": max(p["age"] for p in people)},
        },
    )

    write_yaml(out / "config.yaml")
    write_xml(out / "data.xml", people)
    write_ini(out / "settings.ini")
    write_kv_text(out / "key_values.txt")
    write_html(out / "table.html", people)

    write_xlsx(out / "table.xlsx", people)
    write_sqlite(out / "data.sqlite", people)

    write_gz_csv(out / "metrics.csv.gz", people)

    write_random_binary(out / "unknown.bin")

    write_archive(
        out / "archive.zip",
        out,
        [
            "people.csv",
            "records.json",
            "records.jsonl",
            "config.yaml",
            "data.xml",
            "table.html",
            "settings.ini",
            "unknown.bin",
        ],
    )

    print(f"Wrote sample data to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
