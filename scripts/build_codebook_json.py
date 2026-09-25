"""Builds the compressed codebook snapshot shipped inside the package.

Parses the bundled ``resources/codebook.html`` (~10MB), joins it with the
variable-to-round membership index (``resources/rounds.json``, produced by
``scripts/build_rounds_index.py``), and writes the result as a gzip-compressed
JSON file: ``resources/codebook.json.gz``.

Why this exists
----------------
``Codebook.load_bundled()`` prefers this pre-built snapshot over parsing the
raw HTML at runtime, for two reasons:

- **Size**: the raw HTML is ~10MB; the compressed snapshot is ~370KB (about
  25x smaller), which matters if this library gets installed via pip.
- **Speed**: parsing the HTML with BeautifulSoup takes tens of seconds;
  loading the snapshot is near-instant (gzip decompress + ``json.loads``).

The raw ``codebook.html`` and ``rounds.json`` are excluded from built
sdists/wheels (see ``pyproject.toml``) - they only need to exist in a
development checkout, as the input to this script.

Usage::

    python scripts/build_codebook_json.py

Re-run this (and commit the updated ``codebook.json.gz``) whenever
``codebook.html`` or ``rounds.json`` changes.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pyess.codebook import Codebook


def main() -> None:
    resources_dir = Path(__file__).resolve().parent.parent / "src" / "pyess" / "resources"
    html_path = resources_dir / "codebook.html"
    rounds_path = resources_dir / "rounds.json"
    output_path = resources_dir / "codebook.json.gz"

    html = html_path.read_text(encoding="utf-8")
    rounds_index = json.loads(rounds_path.read_text(encoding="utf-8")) if rounds_path.exists() else None

    print("Parsing codebook.html and joining with rounds.json...")
    codebook = Codebook.from_html(html, rounds_index)
    print(f"  -> {len(codebook.rounds)} rounds, {len(codebook)} variables")

    data = json.dumps(codebook.to_dict(), separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(data, compresslevel=9)

    output_path.write_bytes(compressed)
    print(f"Wrote {len(compressed):,} bytes (from {len(data):,} bytes uncompressed) to {output_path}")


if __name__ == "__main__":
    main()
