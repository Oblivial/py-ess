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
class Variable:
    """Metadata for a single ESS variable, parsed from the codebook.

    This mirrors the structure found in the codebook HTML: a short name
    (``id``), a human-readable label, optional question/instruction text
    shown to respondents, and an optional list of coded value labels.
    """

    id: str
    label: str
    question_texts: List[str] = field(default_factory=list)
    value_labels: List[ValueLabel] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "question_texts": list(self.question_texts),
            "value_labels": [vl.to_dict() for vl in self.value_labels],
        }

    def label_for(self, value: Any) -> Optional[str]:
        """Look up the human-readable category label for a coded value."""
        value_str = str(value)
        for vl in self.value_labels:
            if vl.value == value_str:
                return vl.label
        return None
