"""Local recoding of ESS designated-missing value codes to system missing.

The ESS API has a ``recodeMissingValues=true`` request parameter (used by
``ESS.load(...)``) that recodes designated-missing categories - Refusal,
Don't know, No answer, Not applicable, etc. - to system missing (``NaN``)
server-side, before the file is downloaded. There is no equivalent for data
that's already on disk (``ESS.load_local_csv(...)``), so this module performs
the same recoding locally, using the same designated-missing codes recorded
in the bundled codebook (see ``Variable.missing_values``, parsed from the
codebook's "*) Missing value"-flagged categories).

Exposed publicly (``pyess.recode_missing_values``) so callers that cache a
loaded dataframe across multiple variable accesses - rather than reloading
the CSV every time - can recode newly-accessed columns on demand.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .codebook import Codebook


def recode_missing_values(
    dataframe: Any, codebook: Codebook, columns: Iterable[str] | None = None
) -> Any:
    """Recode ESS designated-missing value codes to system-missing (NaN/null)
    for the given ``columns`` (every column in ``dataframe`` if omitted) that
    the bundled codebook knows about.

    Safe to call more than once on the same dataframe/columns: a cell that's
    already been recoded to missing won't match any designated-missing code
    and is left untouched.
    """
    is_polars = hasattr(dataframe, "with_columns")
    target_columns = list(columns) if columns is not None else list(dataframe.columns)
    for column in target_columns:
        if column not in dataframe.columns:
            continue
        variable = codebook.get_variable(column)
        if variable is None:
            continue
        missing_codes = variable.missing_values
        if not missing_codes:
            continue
        if is_polars:
            import polars as pl

            numeric_codes = [float(c) for c in missing_codes if _is_number(c)]
            col_dtype = dataframe.schema[column]
            if numeric_codes and col_dtype.is_numeric():
                condition = pl.col(column).cast(pl.Float64).is_in(numeric_codes)
            else:
                condition = pl.col(column).cast(pl.Utf8).is_in(list(missing_codes))
            dataframe = dataframe.with_columns(
                pl.when(condition).then(None).otherwise(pl.col(column)).alias(column)
            )
        else:
            mask = dataframe[column].isin(_value_matchers(missing_codes))
            if mask.any():
                dataframe[column] = dataframe[column].mask(mask)
    return dataframe


def _value_matchers(codes: set[str]) -> set[Any]:
    """Expand codebook value codes (always strings, e.g. ``"77"``) into every
    representation they might take once a CSV column has been parsed (int,
    float, or left as the original string), so they can be matched against a
    column regardless of the dtype pandas/Polars inferred for it."""
    matchers: set[Any] = set(codes)
    for code in codes:
        try:
            matchers.add(int(code))
        except ValueError:
            pass
        try:
            matchers.add(float(code))
        except ValueError:
            pass
    return matchers


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
