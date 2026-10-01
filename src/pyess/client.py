"""HTTP client for the ESS API: on-demand, cached loading of ESS datafiles."""

from __future__ import annotations

import io
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import requests

try:
    from platformdirs import user_cache_dir
except ImportError:  # pragma: no cover
    import os

    def user_cache_dir(appname: str) -> str:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
        return str(Path(base) / appname)

from .codebook import Codebook
from .dataset import Dataset, SeriesView
from .missing_values import recode_missing_values as _recode_missing_values
from .userid import get_user_id

logger = logging.getLogger("pyess")

_DEFAULT_BASE_URL = "https://api.ess.sikt.no"
_VALID_FORMATS = {"parquet", "csv", "sav", "dta"}


class ESSAPIError(RuntimeError):
    """Raised when the ESS API returns an error response."""


class ESS:
    """Entry point for dynamically loading ESS data on demand.

    Parameters
    ----------
    user_id:
        Registered ESS user ID to send as the ``userId`` query parameter. If
        omitted, ``PYESS_USER_ID`` must be set. Get an ID at
        ``https://ess.sikt.no/en/api``.
    base_url:
        Override the API base URL (mainly for testing).
    cache_dir:
        Directory used to cache downloaded datafiles so repeated access
        doesn't re-download. Defaults to a per-user cache directory.
        Pass ``None`` with ``use_cache=False`` to disable caching entirely.
    use_cache:
        Whether to cache downloaded files on disk. Defaults to ``True``.
    session:
        Optional pre-configured ``requests.Session`` (e.g. for retries/auth
        in a corporate proxy environment).
    """

    def __init__(
        self,
        user_id: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        use_cache: bool = True,
        session: requests.Session | None = None,
    ):
        self.user_id = user_id or get_user_id()
        self.base_url = base_url.rstrip("/")
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir) if cache_dir else Path(user_cache_dir("py-ess"))
        self.session = session or requests.Session()
        self._codebook: Codebook | None = None

    def load_local_csv(
        self,
        path: str | Path,
        variables: Iterable[str] | None = None,
        engine: Literal["pandas", "polars"] = "pandas",
        full_schema_scan: bool = True,
        recode_missing_values: bool = True,
    ) -> Dataset:
        """Load an ESS CSV file from disk and attach bundled metadata.

        If ``variables`` is supplied, every requested variable must be a
        column in the file. A clear error lists missing and available columns
        instead of failing later during variable access. ``engine`` selects
        the dataframe library; Polars must be installed separately.

        ``full_schema_scan`` only applies to ``engine="polars"``. Polars
        normally infers each column's dtype from a small sample of rows,
        which can misjudge mostly-integer ESS columns that contain the
        occasional decimal value (e.g. ``wkhtot``) further down the file and
        raise a parse error. When ``True`` (the default), the full file is
        scanned for schema inference to avoid this, at the cost of extra read
        time/memory on very large files. Set it to ``False`` to restore
        Polars' default sampled inference (faster, but may hit the same
        mixed-dtype parse errors on columns whose irregular values appear
        beyond the sampled rows).

        ``recode_missing_values`` mirrors the ``recode_missing_values``
        parameter of :meth:`load`, but there is no API to ask to do the work
        for a file that's already on disk: instead, every column is recoded
        locally using the designated-missing value codes (Refusal/Don't
        know/No answer/etc.) recorded in the bundled codebook (see
        ``Variable.missing_values``). Defaults to ``True`` so local CSVs and
        API downloads behave the same way out of the box.

        A single local CSV typically stacks *every* ESS round together in
        one file (unlike the API, which serves one round per request). Rounds
        differ in which columns they populate at all (e.g. ``anweight`` and
        ``inwyys`` don't exist until later rounds) - that's invisible here,
        since every column in the merged file is kept regardless of which
        round(s) actually populated it. If you need each round's own
        subset of real (non-blank) columns - e.g. to replicate the
        per-round shape the API serves - use :meth:`load_local_csv_by_round`
        instead.
        """
        dataframe = self._read_local_csv(path, engine, full_schema_scan)
        requested = self._validate_requested_variables(dataframe, variables, path)
        if recode_missing_values:
            # Only touch the columns actually requested, if any were: with
            # hundreds of columns in a full ESS datafile, recoding every one
            # of them is needlessly slow when the caller only cares about a
            # handful of variables.
            dataframe = _recode_missing_values(
                dataframe, self.codebook, columns=requested or None
            )
        return Dataset(dataframe, codebook=self.codebook)

    def load_local_csv_by_round(
        self,
        path: str | Path,
        variables: Iterable[str] | None = None,
        engine: Literal["pandas", "polars"] = "pandas",
        full_schema_scan: bool = True,
        recode_missing_values: bool = True,
        round_column: str = "essround",
    ) -> dict[str, Dataset]:
        """Load a merged local ESS CSV and split it into one :class:`Dataset`
        per round, keyed by that round's DOI - mirroring how :meth:`load`
        returns one dataset per round when fetched from the API, instead of
        :meth:`load_local_csv`'s single dataframe spanning every round.

        This matters because ESS rounds differ in which columns they
        populate at all (e.g. ``anweight`` doesn't exist before round 4;
        ``inwyys`` doesn't exist before round 3). Code that picks "the best
        available column" out of several candidates (as callers commonly do
        for weight/year columns) needs to make that choice *per round*, the
        same way it naturally would when loading each round from the API
        separately - otherwise a single dataframe spanning every round can
        make that choice once globally and silently lose every row from
        whichever round doesn't populate the chosen column. Each per-round
        dataframe returned here drops columns that are entirely absent
        (NaN) for that specific round, so "the first candidate column
        present" is correct again without the caller needing any
        round-awareness of its own.

        Parameters are otherwise identical to :meth:`load_local_csv`, plus:

        round_column:
            Column identifying the ESS round number (e.g. ``1``, ``2``, ...).
            Defaults to ``"essround"``, the standard ESS column name. Each
            distinct round number present is matched to a codebook round via
            its short label (``f"ESS{number}"``); round numbers with no
            matching codebook round are skipped with a warning (this can
            happen for a malformed/foreign ``round_column`` value).

        Note: a column is considered "absent for a round" based on its *raw*
        values, before missing-value recoding - so a column is only dropped
        if the round's rows for it are blank in the source file (truly not
        collected), not merely because every respondent who *did* answer
        happened to decline (e.g. all "Don't know"). Recoding happens after
        the split, per round, so it can never influence which columns a
        round keeps.
        """
        dataframe = self._read_local_csv(path, engine, full_schema_scan)
        requested = self._validate_requested_variables(dataframe, variables, path)
        if round_column not in dataframe.columns:
            raise KeyError(
                f"ESS CSV {str(path)!r} is missing the round-identifying column "
                f"{round_column!r}; cannot split it by round. Available columns: "
                f"{', '.join(map(str, dataframe.columns))}"
            )
        datasets = self._split_by_round(dataframe, round_column)
        if recode_missing_values:
            datasets = {
                doi: Dataset(
                    _recode_missing_values(
                        dataset.dataframe, self.codebook, columns=requested or None
                    ),
                    datafile=dataset.datafile,
                    codebook=self.codebook,
                )
                for doi, dataset in datasets.items()
            }
        return datasets

    def _read_local_csv(
        self, path: str | Path, engine: Literal["pandas", "polars"], full_schema_scan: bool
    ) -> Any:
        if engine == "pandas":
            return pd.read_csv(path)
        if engine == "polars":
            try:
                import polars as pl
            except ImportError as exc:
                raise ImportError(
                    "Polars support requires the optional dependency; "
                    "install it with `pip install py-ess[polars]`."
                ) from exc
            infer_schema_length = None if full_schema_scan else 100
            return pl.read_csv(path, infer_schema_length=infer_schema_length)
        raise ValueError(f"Unsupported engine {engine!r}; expected 'pandas' or 'polars'")

    @staticmethod
    def _validate_requested_variables(
        dataframe: Any, variables: Iterable[str] | None, path: str | Path
    ) -> list[str]:
        requested = list(dict.fromkeys(variables or []))
        missing = [variable for variable in requested if variable not in dataframe]
        if missing:
            raise KeyError(
                f"ESS CSV {str(path)!r} is missing variable(s): {', '.join(missing)}. "
                f"Available columns: {', '.join(map(str, dataframe.columns))}"
            )
        return requested

    def _split_by_round(self, dataframe: Any, round_column: str) -> dict[str, Dataset]:
        is_polars = not isinstance(dataframe, pd.DataFrame)
        if is_polars:
            import polars as pl

            numbers = dataframe[round_column].cast(pl.Float64, strict=False)
            unique_numbers = sorted({n for n in numbers.to_list() if n is not None})
        else:
            numbers = pd.to_numeric(dataframe[round_column], errors="coerce")
            unique_numbers = sorted(numbers.dropna().unique().tolist())

        datasets: dict[str, Dataset] = {}
        for number in unique_numbers:
            round_obj = self.codebook.get_round(f"ESS{int(number)}")
            if round_obj is None:
                logger.warning(
                    "No codebook round found for %s=%s; skipping these rows.",
                    round_column,
                    number,
                )
                continue
            if is_polars:
                round_df = dataframe.filter(numbers == number)
                keep_columns = [
                    c for c in round_df.columns if round_df[c].null_count() < round_df.height
                ]
                round_df = round_df.select(keep_columns)
            else:
                round_df = dataframe.loc[numbers == number].reset_index(drop=True)
                round_df = round_df.dropna(axis=1, how="all")
            datasets[round_obj.doi] = Dataset(
                round_df, datafile=round_obj, codebook=self.codebook
            )
        return datasets


    # -- codebook (static metadata) --------------------------------------
    @property
    def codebook(self) -> Codebook:
        """Lazily parsed, cached codebook of datafiles + variable metadata."""
        if self._codebook is None:
            self._codebook = Codebook.load_bundled()
        return self._codebook

    # -- data loading ------------------------------------------------
    def load(
        self,
        doi: str,
        file_format: str = "parquet",
        recode_missing_values: bool = True,
        refresh: bool = False,
    ) -> Dataset:
        """Load a datafile by DOI, downloading (and caching) it on demand.

        Parameters
        ----------
        doi:
            Full datafile DOI, e.g. ``"10.21338/ess11e04_2"``.
        file_format:
            One of ``"parquet"`` (default), ``"csv"``, ``"sav"``, ``"dta"``.
        recode_missing_values:
            Defaults to ``True``. Asks the ESS API itself to recode
            designated-missing values (e.g. "Refusal", "Don't know", "No
            answer") to system missing values before the file is downloaded.
            Set to ``False`` to receive the raw, undecoded value codes
            instead. See ``load_local_csv`` for the equivalent behaviour
            when loading a file that's already on disk, which has no API to
            delegate to and instead recodes locally using the bundled
            codebook.
        refresh:
            If ``True``, bypass the on-disk cache and re-download.
        """
        if file_format not in _VALID_FORMATS:
            raise ValueError(
                f"Unsupported file_format {file_format!r}; expected one of {_VALID_FORMATS}"
            )

        doi_prefix, doi_suffix = _split_doi(doi)
        cache_path = self._cache_path(doi_prefix, doi_suffix, file_format)

        if self.use_cache and cache_path.exists() and not refresh:
            logger.debug("Loading %s from cache at %s", doi, cache_path)
            content = cache_path.read_bytes()
        else:
            content = self._download(doi_prefix, doi_suffix, file_format, recode_missing_values)
            if self.use_cache:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(content)

        dataframe = _parse_content(content, file_format)
        datafile = self.codebook.get_datafile(doi)
        return Dataset(dataframe, datafile=datafile, codebook=self.codebook)

    def load_round(self, round_: str, **kwargs: Any) -> Dataset:
        """Load a full ESS round's datafile, identified by DOI or short label
        (e.g. ``"ESS11"``). Equivalent to ``self.load(round_doi, **kwargs)``
        but lets you skip the datafile/DOI lookup step."""
        round_obj = self.codebook.get_round(round_)
        if round_obj is None:
            raise KeyError(f"Unknown ESS round {round_!r}")
        return self.load(round_obj.doi, **kwargs)

    def load_variable(
        self,
        variable: str,
        round_: str | None = None,
        **kwargs: Any,
    ) -> SeriesView:
        """Load a single variable's data, indexed purely by name (and,
        optionally, round) - without the caller ever having to look up a
        datafile/DOI themselves.

        Parameters
        ----------
        variable:
            Variable name, e.g. ``"netusoft"``.
        round_:
            Which ESS round to load it from, by DOI or short label (e.g.
            ``"ESS11"``). Required if the variable was collected in more than
            one round; if omitted and the variable exists in exactly one
            round, that round is used automatically.
        """
        var = self.codebook.get_variable(variable)
        if var is None:
            raise KeyError(f"Unknown ESS variable {variable!r}")

        if round_ is not None:
            doi = self.codebook._resolve_round_doi(round_)
            if doi not in var.rounds:
                raise KeyError(
                    f"Variable {variable!r} was not collected in round {round_!r}; "
                    f"available rounds: {var.rounds}"
                )
        elif len(var.rounds) == 1:
            doi = var.rounds[0]
        elif len(var.rounds) == 0:
            raise KeyError(f"Variable {variable!r} has no known round membership")
        else:
            raise ValueError(
                f"Variable {variable!r} appears in multiple rounds ({var.rounds}); "
                "pass `round_=` to disambiguate"
            )

        dataset = self.load(doi, **kwargs)
        return dataset[variable]

    def _download(
        self, doi_prefix: str, doi_suffix: str, file_format: str, recode_missing_values: bool
    ) -> bytes:
        url = f"{self.base_url}/v1/data/dataFile/{doi_prefix}/{doi_suffix}"
        params = {"userId": self.user_id, "fileFormat": file_format}
        if recode_missing_values:
            params["recodeMissingValues"] = "true"

        logger.debug("Requesting %s with params=%s", url, params)
        response = self.session.get(url, params=params, allow_redirects=True)
        if not response.ok:
            _raise_for_error(response)
        return response.content

    def _cache_path(self, doi_prefix: str, doi_suffix: str, file_format: str) -> Path:
        safe_prefix = doi_prefix.replace("/", "_")
        return self.cache_dir / safe_prefix / f"{doi_suffix}.{file_format}"


def _split_doi(doi: str) -> tuple[str, str]:
    if "/" not in doi:
        raise ValueError(
            f"Invalid DOI {doi!r}; expected format '<prefix>/<suffix>', e.g. '10.21338/ess11e04_2'"
        )
    prefix, suffix = doi.split("/", 1)
    return prefix, suffix


def _parse_content(content: bytes, file_format: str) -> pd.DataFrame:
    if file_format == "parquet":
        return pd.read_parquet(io.BytesIO(content))
    if file_format == "csv":
        return pd.read_csv(io.BytesIO(content))
    if file_format == "dta":
        return pd.read_stata(io.BytesIO(content))
    if file_format == "sav":
        # pandas.read_spss (via pyreadstat) requires an on-disk path, not a
        # file-like object, so spill to a temp file for parsing.
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            return pd.read_spss(tmp_path)
        finally:
            os.unlink(tmp_path)
    raise ValueError(f"Unsupported file_format {file_format!r}")  # pragma: no cover


def _raise_for_error(response: requests.Response) -> None:
    try:
        payload = response.json()
        message = payload.get("message", response.text)
        code = payload.get("code")
    except ValueError:
        message = response.text
        code = None
    raise ESSAPIError(
        f"ESS API request failed with status {response.status_code}"
        f"{f' (code {code})' if code is not None else ''}: {message}"
    )
