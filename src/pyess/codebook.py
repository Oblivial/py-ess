"""Parsing of the ESS "Datafile codebook" HTML into structured, indexable data.

The codebook lists all available ESS datafiles (with their DOIs) and describes
every variable that can appear in a datafile (id, label, question wording, and
coded value labels). This module parses that static HTML once (lazily,
cached) and exposes it as plain Python objects that are trivially JSON
serializable via ``.to_dict()``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bs4 import BeautifulSoup

try:
    from platformdirs import user_cache_dir
except ImportError:  # pragma: no cover
    import os

    def user_cache_dir(appname: str) -> str:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
        return str(Path(base) / appname)

from .models import Variable, ValueLabel

_DOI_RE = re.compile(r"doi\.org/(?P<doi>10\.\d+/\S+)")


@dataclass
class Datafile:
    """A single ESS datafile entry (e.g. one round/edition) from the codebook."""

    name: str
    doi: str

    @property
    def doi_prefix(self) -> str:
        return self.doi.split("/", 1)[0]

    @property
    def doi_suffix(self) -> str:
        return self.doi.split("/", 1)[1]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "doi": self.doi}


class Codebook:
    """Parsed representation of the ESS datafile codebook.

    Provides indexable access to datafiles (by name/DOI) and variables (by
    variable id), and can serialize the entire codebook (or any subset) to
    plain dict/JSON structures.
    """

    def __init__(self, datafiles: List[Datafile], variables: List[Variable]):
        self._datafiles = datafiles
        self._variables = variables
        self._datafiles_by_doi = {d.doi: d for d in datafiles}
        self._variables_by_id = {v.id: v for v in variables}

    # -- construction ------------------------------------------------
    @classmethod
    def from_html(cls, html: str) -> "Codebook":
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:  # pragma: no cover - lxml not installed
            soup = BeautifulSoup(html, "html.parser")
        datafiles = _parse_datafiles(soup)
        variables = _parse_variables(soup)
        return cls(datafiles, variables)

    @classmethod
    def load_bundled(cls) -> "Codebook":
        """Load the codebook shipped with the package (resources/codebook.html).

        Parsing the ~10MB bundled HTML with BeautifulSoup takes tens of
        seconds, so the parsed result is cached as JSON on disk (keyed by a
        hash of the source HTML) for near-instant subsequent loads.
        """
        html = (
            resources.files("pyess.resources")
            .joinpath("codebook.html")
            .read_text(encoding="utf-8")
        )
        cached = _load_from_disk_cache(html)
        if cached is not None:
            return cached

        codebook = cls.from_html(html)
        _save_to_disk_cache(html, codebook)
        return codebook

    # -- indexing ------------------------------------------------------
    @property
    def datafiles(self) -> List[Datafile]:
        return list(self._datafiles)

    @property
    def variables(self) -> List[Variable]:
        return list(self._variables)

    def __len__(self) -> int:
        return len(self._variables)

    def __iter__(self) -> Iterable[Variable]:
        return iter(self._variables)

    def __getitem__(self, variable_id: str) -> Variable:
        return self._variables_by_id[variable_id]

    def __contains__(self, variable_id: str) -> bool:
        return variable_id in self._variables_by_id

    def get_variable(self, variable_id: str) -> Optional[Variable]:
        return self._variables_by_id.get(variable_id)

    def __getattr__(self, name: str) -> Variable:
        # Convenience accessor mirroring __getitem__; only triggered when
        # normal attribute lookup fails, so real attributes/methods (e.g.
        # `.variables`, `.datafiles`) always take precedence and are never
        # shadowed by a variable of the same name.
        variables_by_id = self.__dict__.get("_variables_by_id")
        if variables_by_id is not None and name in variables_by_id:
            return variables_by_id[name]
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r} "
            f"(no such variable either; use codebook[{name!r}] to check safely)"
        )

    def __dir__(self) -> List[str]:
        return list(super().__dir__()) + [
            v for v in self._variables_by_id if v.isidentifier()
        ]

    def find_datafile(self, name_substring: str) -> Optional[Datafile]:
        """Find the first datafile whose name contains ``name_substring``
        (case-insensitive)."""
        needle = name_substring.lower()
        for d in self._datafiles:
            if needle in d.name.lower():
                return d
        return None

    def get_datafile(self, doi: str) -> Optional[Datafile]:
        return self._datafiles_by_doi.get(doi)

    # -- serialization ---------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "datafiles": [d.to_dict() for d in self._datafiles],
            "variables": {v.id: v.to_dict() for v in self._variables},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Codebook":
        datafiles = [Datafile(name=d["name"], doi=d["doi"]) for d in data["datafiles"]]
        variables = [
            Variable(
                id=v["id"],
                label=v["label"],
                question_texts=list(v["question_texts"]),
                value_labels=[ValueLabel(**vl) for vl in v["value_labels"]],
            )
            for v in data["variables"].values()
        ]
        return cls(datafiles, variables)


def _parse_datafiles(soup: BeautifulSoup) -> List[Datafile]:
    datafiles: List[Datafile] = []
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
                datafiles.append(Datafile(name=name, doi=doi))
    return datafiles


def _parse_variables(soup: BeautifulSoup) -> List[Variable]:
    variables: List[Variable] = []
    for header in soup.find_all("h3", id=True):
        container = header.parent  # the wrapping <div> for this variable
        if container is None:
            continue

        var_id = header.get("id")
        label_div = header.find_next_sibling("div")
        label = label_div.get_text(strip=True) if label_div else ""

        question_texts: List[str] = []
        for meta in container.find_all("div", class_="variable-meta-string"):
            text = meta.get_text(strip=True)
            if text:
                question_texts.append(text)

        value_labels: List[ValueLabel] = []
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


def _disk_cache_path(html: str) -> Path:
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]
    return Path(user_cache_dir("py-ess")) / f"codebook-{digest}.json"


def _load_from_disk_cache(html: str) -> Optional[Codebook]:
    path = _disk_cache_path(html)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Codebook.from_dict(data)
    except (OSError, ValueError, KeyError):
        return None


def _save_to_disk_cache(html: str, codebook: Codebook) -> None:
    path = _disk_cache_path(html)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(codebook.to_dict()), encoding="utf-8")
    except OSError:
        pass  # Non-fatal: caching is a pure performance optimization.
