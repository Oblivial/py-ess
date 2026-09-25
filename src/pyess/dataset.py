"""Indexable, JSON-serializable wrapper around a downloaded ESS datafile."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pandas as pd

from .codebook import Codebook, Datafile
from .models import Variable


class SeriesView:
    """A single column paired with its codebook metadata.

    Supports JSON serialization of both the variable's metadata and its
    values (as records), and indexing by row position.
    """

    def __init__(self, name: str, series: pd.Series, variable: Variable | None):
        self._name = name
        self._series = series
        self._variable = variable

    @property
    def name(self) -> str:
        return self._name

    @property
    def variable(self) -> Variable | None:
        return self._variable

    @property
    def values(self) -> list[Any]:
        return self._series.tolist()

    def __len__(self) -> int:
        return len(self._series)

    def __getitem__(self, index: int) -> Any:
        return self._series.iloc[index]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._series.tolist())

    def decoded(self) -> list[Any]:
        """Return values with coded numbers/strings replaced by their
        human-readable category label, where a mapping exists."""
        if self._variable is None or not self._variable.value_labels:
            return self.values
        return [
            self._variable.label_for(v) if self._variable.label_for(v) is not None else v
            for v in self._series.tolist()
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "variable": self._variable.to_dict() if self._variable else None,
            "values": self.values,
        }


class Dataset:
    """A downloaded ESS datafile, indexable by variable name and row.

    Wraps a :class:`pandas.DataFrame` (the raw data) together with the
    matching :class:`~pyess.codebook.Codebook` metadata, exposing a
    dict/JSON-like interface without requiring pandas knowledge:

        dataset["netuse"]          # -> SeriesView with metadata + values
        dataset["netuse"].decoded()  # -> category labels instead of codes
        dataset.to_dict()          # -> whole dataset as nested dict
        dataset.to_records()       # -> list of per-respondent dicts
    """

    def __init__(
        self,
        dataframe: pd.DataFrame,
        datafile: Datafile | None = None,
        codebook: Codebook | None = None,
    ):
        self._df = dataframe
        self._datafile = datafile
        self._codebook = codebook

    @property
    def dataframe(self) -> pd.DataFrame:
        """Escape hatch to the underlying pandas DataFrame."""
        return self._df

    @property
    def datafile(self) -> Datafile | None:
        return self._datafile

    @property
    def columns(self) -> list[str]:
        return list(self._df.columns)

    def __len__(self) -> int:
        return len(self._df)

    def __contains__(self, column: str) -> bool:
        return column in self._df.columns

    def __iter__(self) -> Iterator[str]:
        return iter(self.columns)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return self._series_view(key)
        if isinstance(key, int):
            return self._df.iloc[key].to_dict()
        raise TypeError(f"Unsupported index type for Dataset: {type(key)!r}")

    def __getattr__(self, name: str) -> Any:
        # Only called when normal attribute lookup fails, so this never
        # shadows real attributes/methods (e.g. `.columns`, `.to_dict`) -
        # mirroring pandas' `df.column_name` convenience accessor.
        df = self.__dict__.get("_df")
        if df is not None and name in df.columns:
            return self._series_view(name)
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r} "
            f"(no such column either; use dataset[{name!r}] to check safely)"
        )

    def __dir__(self) -> list[str]:
        # Enables tab-completion for column names in IDEs/notebooks.
        return list(super().__dir__()) + [
            c for c in self.columns if c.isidentifier()
        ]

    def _series_view(self, column: str) -> SeriesView:
        variable = self._codebook.get_variable(column) if self._codebook else None
        return SeriesView(column, self._df[column], variable)

    def variable(self, column: str) -> Variable | None:
        return self._codebook.get_variable(column) if self._codebook else None

    def to_records(self) -> list[dict[str, Any]]:
        """Return the dataset as a list of per-row dicts (JSON-serializable)."""
        return self._df.to_dict(orient="records")

    def to_dict(self, include_metadata: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "datafile": self._datafile.to_dict() if self._datafile else None,
            "columns": self.columns,
            "row_count": len(self._df),
            "records": self.to_records(),
        }
        if include_metadata and self._codebook is not None:
            result["variables"] = {
                col: v.to_dict()
                for col in self.columns
                if (v := self._codebook.get_variable(col)) is not None
            }
        return result
