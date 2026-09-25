"""Parsing of the ESS "Datafile codebook" HTML into structured, indexable data.

The codebook lists all available ESS datafiles (with their DOIs) and describes
every variable that can appear in a datafile (id, label, question wording, and
coded value labels). This module parses that static HTML once (lazily,
cached) and exposes it as plain Python objects that are trivially JSON
serializable via ``.to_dict()``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Iterator
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from bs4 import FeatureNotFound as _BS4FeatureNotFound

try:
    from platformdirs import user_cache_dir
except ImportError:  # pragma: no cover
    import os

    def user_cache_dir(appname: str) -> str:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
        return str(Path(base) / appname)

from .models import Round, ValueLabel, Variable

_DOI_RE = re.compile(r"doi\.org/(?P<doi>10\.\d+/\S+)")
_ROUND_LABEL_RE = re.compile(r"ess(?P<num>\d+)(?P<sc>sc)?e", re.IGNORECASE)

# Backwards-compatible alias: earlier versions of py-ess called this
# `Datafile`. `Round` is the same concept, renamed now that variables (not
# datafiles) are the primary thing users index.
Datafile = Round


def _round_label(doi: str) -> str:
    """Derive a short human-friendly label (e.g. "ESS11", "ESS10SC") from a
    round's DOI suffix (e.g. "ess11e04_2", "ess10sce03_2")."""
    match = _ROUND_LABEL_RE.search(doi)
    if not match:
        return doi
    label = f"ESS{match.group('num')}"
    if match.group("sc"):
        label += "SC"
    return label


class Codebook:
    """Parsed representation of the ESS datafile codebook.

    Provides indexable access to datafiles (by name/DOI) and variables (by
    variable id), and can serialize the entire codebook (or any subset) to
    plain dict/JSON structures.
    """

    def __init__(self, rounds: list[Round], variables: list[Variable]):
        self._rounds = rounds
        self._variables = variables
        self._rounds_by_doi = {r.doi: r for r in rounds}
        self._variables_by_id = {v.id: v for v in variables}

    # -- construction ------------------------------------------------
    @classmethod
    def from_html(cls, html: str, rounds_index: dict[str, Any] | None = None) -> Codebook:
        """Parse the codebook HTML (labels/question text/value labels) and
        optionally join it with a round index (see ``rounds.json``, built by
        ``scripts/build_rounds_index.py``) that records which rounds each
        variable was collected in.
        """
        try:
            soup = BeautifulSoup(html, "lxml")
        except _BS4FeatureNotFound:  # pragma: no cover - lxml not installed
            soup = BeautifulSoup(html, "html.parser")
        parsed_rounds = _parse_datafiles(soup)
        variables = _parse_variables(soup)

        if rounds_index:
            rounds, variable_rounds = _rounds_and_membership_from_index(rounds_index)
            # Prefer the richer round list from the index (has countries),
            # but fall back to whatever the static HTML listed if the index
            # is missing/stale for some reason.
            rounds_by_doi = {r.doi: r for r in rounds} or {r.doi: r for r in parsed_rounds}
            for variable in variables:
                variable.rounds = variable_rounds.get(variable.id, [])
            return cls(list(rounds_by_doi.values()) or parsed_rounds, variables)

        return cls(parsed_rounds, variables)

    @classmethod
    def load_bundled(cls) -> Codebook:
        """Load the codebook shipped with the package.

        The package ships a pre-parsed, gzip-compressed JSON snapshot
        (``resources/codebook.json.gz``) - variable labels/question
        text/value labels already joined with round membership from
        ``resources/rounds.json`` - built once by
        ``scripts/build_codebook_json.py`` (which itself runs
        ``scripts/build_rounds_index.py`` first). This avoids shipping the
        ~10MB raw codebook HTML in the distributed package (the compressed
        snapshot is roughly 25x smaller) and avoids the tens-of-seconds
        BeautifulSoup parse cost on every fresh install.

        For local development (e.g. before running the build script, or if
        the snapshot is missing for some other reason) this falls back to
        parsing ``resources/codebook.html`` directly, caching the result on
        disk exactly as before.
        """
        snapshot = _load_bundled_snapshot()
        if snapshot is not None:
            return cls.from_dict(snapshot)

        html = (
            resources.files("pyess.resources")
            .joinpath("codebook.html")
            .read_text(encoding="utf-8")
        )
        rounds_index = _load_bundled_rounds_index()
        cache_key = html + json.dumps(rounds_index, sort_keys=True)

        cached = _load_from_disk_cache(cache_key)
        if cached is not None:
            return cached

        codebook = cls.from_html(html, rounds_index)
        _save_to_disk_cache(cache_key, codebook)
        return codebook

    # -- indexing ------------------------------------------------------
    @property
    def rounds(self) -> list[Round]:
        return list(self._rounds)

    @property
    def datafiles(self) -> list[Round]:
        # Backwards-compatible alias for `.rounds`.
        return self.rounds

    @property
    def variables(self) -> list[Variable]:
        return list(self._variables)

    def __len__(self) -> int:
        return len(self._variables)

    def __iter__(self) -> Iterator[Variable]:
        return iter(self._variables)

    def __getitem__(self, variable_id: str) -> Variable:
        return self._variables_by_id[variable_id]

    def __contains__(self, variable_id: str) -> bool:
        return variable_id in self._variables_by_id

    def get_variable(self, variable_id: str) -> Variable | None:
        return self._variables_by_id.get(variable_id)

    def variables_in_round(self, round_: str) -> list[Variable]:
        """All variables collected in a given round, identified by DOI or by
        short label (e.g. ``"ESS11"``, case-insensitive)."""
        doi = self._resolve_round_doi(round_)
        return [v for v in self._variables if doi in v.rounds]

    def __getattr__(self, name: str) -> Variable:
        # Convenience accessor mirroring __getitem__; only triggered when
        # normal attribute lookup fails, so real attributes/methods (e.g.
        # `.variables`, `.rounds`) always take precedence and are never
        # shadowed by a variable of the same name.
        variables_by_id = self.__dict__.get("_variables_by_id")
        if variables_by_id is not None and name in variables_by_id:
            return variables_by_id[name]
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r} "
            f"(no such variable either; use codebook[{name!r}] to check safely)"
        )

    def __dir__(self) -> list[str]:
        return list(super().__dir__()) + [
            v for v in self._variables_by_id if v.isidentifier()
        ]

    def find_datafile(self, name_substring: str) -> Round | None:
        """Find the first round whose name contains ``name_substring``
        (case-insensitive)."""
        needle = name_substring.lower()
        for d in self._rounds:
            if needle in d.name.lower():
                return d
        return None

    def get_datafile(self, doi: str) -> Round | None:
        return self._rounds_by_doi.get(doi)

    def get_round(self, round_: str) -> Round | None:
        """Look up a round by DOI or short label (e.g. ``"ESS11"``)."""
        if round_ in self._rounds_by_doi:
            return self._rounds_by_doi[round_]
        needle = round_.lower()
        for r in self._rounds:
            if _round_label(r.doi).lower() == needle:
                return r
        return None

    def _resolve_round_doi(self, round_: str) -> str:
        round_obj = self.get_round(round_)
        if round_obj is None:
            raise KeyError(f"Unknown ESS round {round_!r}")
        return round_obj.doi

    # -- serialization ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "rounds": [r.to_dict() for r in self._rounds],
            "variables": {v.id: v.to_dict() for v in self._variables},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Codebook:
        rounds_data = data.get("rounds", data.get("datafiles", []))
        rounds = [
            Round(doi=r["doi"], name=r["name"], countries=list(r.get("countries", [])))
            for r in rounds_data
        ]
        variables = [
            Variable(
                id=v["id"],
                label=v["label"],
                question_texts=list(v["question_texts"]),
                value_labels=[ValueLabel(**vl) for vl in v["value_labels"]],
                rounds=list(v.get("rounds", [])),
            )
            for v in data["variables"].values()
        ]
        return cls(rounds, variables)


def _parse_datafiles(soup: BeautifulSoup) -> list[Datafile]:
    datafiles: list[Datafile] = []
    datafiles_heading = soup.find("h2", string=re.compile(r"^\s*Datafiles\s*$"))
    if datafiles_heading is None:
        return datafiles

    for el in datafiles_heading.find_next_siblings():
        if el.name == "h2":
            break  # reached the next major section (e.g. "Variables")
        if el.name == "h3":
            name = el.get_text(strip=True)
            link = el.find_next_sibling("p")
            doi = None
            if link is not None:
                anchor = link.find("a")
                if anchor is not None and anchor.get("href"):
                    match = _DOI_RE.search(anchor["href"])
                    if match:
                        doi = match.group("doi")
            if doi:
                datafiles.append(Round(name=name, doi=doi))
    return datafiles


def _parse_variables(soup: BeautifulSoup) -> list[Variable]:
    variables: list[Variable] = []
    for header in soup.find_all("h3", id=True):
        container = header.parent  # the wrapping <div> for this variable
        if container is None:
            continue

        var_id = header.get("id")
        label_div = header.find_next_sibling("div")
        label = label_div.get_text(strip=True) if label_div else ""

        question_texts: list[str] = []
        for meta in container.find_all("div", class_="variable-meta-string"):
            text = meta.get_text(strip=True)
            if text:
                question_texts.append(text)

        value_labels: list[ValueLabel] = []
        data_table = container.find("div", class_="data-table")
        if data_table is not None:
            body = data_table.find("tbody")
            rows = body.find_all("tr") if body else []
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    value_labels.append(
                        ValueLabel(
                            value=cells[0].get_text(strip=True),
                            label=cells[1].get_text(strip=True),
                        )
                    )

        variables.append(
            Variable(
                id=var_id,
                label=label,
                question_texts=question_texts,
                value_labels=value_labels,
            )
        )
    return variables


@lru_cache(maxsize=1)
def load_bundled_codebook() -> Codebook:
    """Module-level cached accessor so repeated calls don't reparse the HTML."""
    return Codebook.load_bundled()


@lru_cache(maxsize=1)
def _load_bundled_snapshot() -> dict[str, Any] | None:
    """Load the pre-parsed, gzip-compressed codebook snapshot
    (``resources/codebook.json.gz``), built offline by
    ``scripts/build_codebook_json.py``. Returns ``None`` if the resource is
    missing (e.g. in a dev checkout before the build script has been run),
    so callers can fall back to parsing the raw HTML.
    """
    try:
        compressed = (
            resources.files("pyess.resources")
            .joinpath("codebook.json.gz")
            .read_bytes()
        )
    except (FileNotFoundError, ModuleNotFoundError):
        return None
    return json.loads(gzip.decompress(compressed).decode("utf-8"))


@lru_cache(maxsize=1)
def _load_bundled_rounds_index() -> dict[str, Any] | None:
    """Load the pre-scraped variable-to-round membership index
    (``resources/rounds.json``), built offline by
    ``scripts/build_rounds_index.py``. Returns ``None`` if the resource is
    missing so callers can gracefully fall back to round-less variables.
    """
    try:
        text = (
            resources.files("pyess.resources")
            .joinpath("rounds.json")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError):  # pragma: no cover
        return None
    return json.loads(text)


def _rounds_and_membership_from_index(
    rounds_index: dict[str, Any]
) -> tuple[list[Round], dict[str, list[str]]]:
    """Turn the raw rounds.json structure into ``Round`` objects plus a
    variable id -> list-of-round-DOIs membership mapping."""
    rounds: list[Round] = []
    variable_rounds: dict[str, list[str]] = {}
    for entry in rounds_index.get("rounds", []):
        doi = entry["doi"]
        rounds.append(Round(doi=doi, name=entry["name"], countries=list(entry.get("countries", []))))
        for var in entry.get("variables", []):
            variable_rounds.setdefault(var["name"], []).append(doi)
    return rounds, variable_rounds


def _disk_cache_path(cache_key: str) -> Path:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:16]
    return Path(user_cache_dir("py-ess")) / f"codebook-{digest}.json"


def _load_from_disk_cache(cache_key: str) -> Codebook | None:
    path = _disk_cache_path(cache_key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Codebook.from_dict(data)
    except (OSError, ValueError, KeyError):
        return None


def _save_to_disk_cache(cache_key: str, codebook: Codebook) -> None:
    path = _disk_cache_path(cache_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(codebook.to_dict()), encoding="utf-8")
    except OSError:
        pass  # Non-fatal: caching is a pure performance optimization.
