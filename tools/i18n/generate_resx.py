#!/usr/bin/env python3
"""Generates the .resx resource files of the WebUI from the tab-separated translation tables.

    python3 tools/i18n/generate_resx.py

translations.tsv -> Resources/SharedResource.{en-US,fa-IR}.resx       (IStringLocalizer<SharedResource>)
login.tsv        -> Resources/Pages/Account/Login.{en-US,fa-IR}.resx  (IViewLocalizer of the login page)

Line format: key<TAB>Persian[<TAB>English]. English defaults to the key itself.
"""
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
RESOURCES = HERE.parent.parent / "src" / "Crm.WebUI" / "Resources"

HEADER = """<?xml version="1.0" encoding="utf-8"?>
<root>
  <resheader name="resmimetype"><value>text/microsoft-resx</value></resheader>
  <resheader name="version"><value>2.0</value></resheader>
  <resheader name="reader"><value>System.Resources.ResXResourceReader, System.Windows.Forms, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089</value></resheader>
  <resheader name="writer"><value>System.Resources.ResXResourceWriter, System.Windows.Forms, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089</value></resheader>
"""


def read(table: Path):
    rows, seen = [], set()
    for number, line in enumerate(table.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise SystemExit(f"{table.name}:{number}: expected key<TAB>Persian[<TAB>English]")
        key, fa, en = parts[0], parts[1], (parts[2] if len(parts) > 2 and parts[2] else parts[0])
        if key.lower() in seen:  # .resx names are case-insensitive
            raise SystemExit(f"{table.name}:{number}: duplicate key '{key}'")
        seen.add(key.lower())
        rows.append((key, en, fa))
    return rows


def write(target: Path, entries):
    body = "".join(
        f'  <data name="{escape(key, {chr(34): "&quot;"})}" xml:space="preserve"><value>{escape(value)}</value></data>\n'
        for key, value in entries
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(HEADER + body + "</root>\n", encoding="utf-8")
    print(f"{target.relative_to(RESOURCES.parent)}: {len(entries)} entries")


def generate(table: str, base: str):
    rows = read(HERE / table)
    write(RESOURCES / f"{base}.en-US.resx", [(key, en) for key, en, _ in rows])
    write(RESOURCES / f"{base}.fa-IR.resx", [(key, fa) for key, _, fa in rows])


if __name__ == "__main__":
    generate("translations.tsv", "SharedResource")
    generate("login.tsv", "Pages/Account/Login")
