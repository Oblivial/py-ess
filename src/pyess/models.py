"""Plain, JSON-serializable data models shared across py-ess."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class ValueLabel:
    """A single value -> category label mapping for a coded variable."""

    value: str
    label: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Round:
    """A single ESS round/edition datafile: the thing users used to have to
    look up first. Kept mainly so a :class:`Variable` can point back to the
    round(s) it was collected in, and so rounds can still be browsed/listed
    directly if useful (e.g. to see which countries took part)."""

    doi: str
    name: str
    countries: List[str] = field(default_factory=list)

    @property
    def doi_prefix(self) -> str:
        return self.doi.split("/", 1)[0]

    @property
    def doi_suffix(self) -> str:
        return self.doi.split("/", 1)[1]

    def to_dict(self) -> Dict[str, Any]:
        return {"doi": self.doi, "name": self.name, "countries": list(self.countries)}


@dataclass
class Variable:
    """Metadata for a single ESS variable, parsed from the codebook and
    joined with the round-membership index.

    Variables are the primary namespace in py-ess: rather than users having
    to first pick a datafile/round and then look inside it for a variable,
    a ``Variable`` already knows every round it was collected in (``rounds``),
    so it can be looked up purely by name (e.g. ``codebook["netusoft"]``) and
    then optionally filtered/loaded for a specific round or year range.
    """

    id: str
    label: str
    question_texts: List[str] = field(default_factory=list)
    value_labels: List[ValueLabel] = field(default_factory=list)
    rounds: List[str] = field(default_factory=list)  # DOIs of rounds containing this variable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "question_texts": list(self.question_texts),
            "value_labels": [vl.to_dict() for vl in self.value_labels],
            "rounds": list(self.rounds),
        }

    def label_for(self, value: Any) -> Optional[str]:
        """Look up the human-readable category label for a coded value."""
        value_str = str(value)
        for vl in self.value_labels:
            if vl.value == value_str:
                return vl.label
        return None

    def in_round(self, doi: str) -> bool:
        """Whether this variable was collected in the round identified by ``doi``."""
        return doi in self.rounds
