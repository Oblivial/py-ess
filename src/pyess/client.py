"""HTTP client for the ESS API: on-demand, cached loading of ESS datafiles."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

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
from .dataset import Dataset
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
        Value to send as the ``userId`` query parameter. If omitted, a
        stable anonymous identifier of the form ``py-ess-<uuid4>`` is
        generated (or read from the ``PYESS_USER_ID`` env var / cache).
        See :func:`pyess.userid.get_user_id`.
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
        user_id: Optional[str] = None,
        base_url: str = _DEFAULT_BASE_URL,
        cache_dir: Optional[Path] = None,
        use_cache: bool = True,
        session: Optional[requests.Session] = None,
    ):
        self.user_id = user_id or get_user_id()
        self.base_url = base_url.rstrip("/")
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir) if cache_dir else Path(user_cache_dir("py-ess"))
        self.session = session or requests.Session()
        self._codebook: Optional[Codebook] = None

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
        recode_missing_values: bool = False,
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
            If ``True``, ask the API to recode designated missing values
            (e.g. "Not applicable") to system missing values.
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


def _parse_content(content: bytes, file_format: str) -> "pd.DataFrame":
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
