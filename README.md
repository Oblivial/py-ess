# py-ess

A Python library for dynamically loading [European Social Survey (ESS)](https://www.europeansocialsurvey.org/)
data **on demand**, via the [ESS API](https://api.ess.sikt.no/docs), and exposing it as
indexable, JSON-serializable Python objects.

## Features

- **Lazy, on-demand loading** — datafiles are only downloaded when you ask for them,
  and are cached on disk (`platformdirs` user cache directory) so repeat access is instant.
- **Indexable like a dict/JSON object** — `dataset["netuse"]`, `dataset[0]`, `dataset.to_dict()`.
- **Rich variable metadata** — parsed from the ESS "Datafile codebook", including
  variable labels, respondent-facing question text, and coded value → category label
  mappings (`dataset["cntry"].decoded()`).
- **Multiple wire formats** — `parquet` (default), `csv`, `sav` (SPSS), `dta` (Stata).
- **No forced registration** — a stable, anonymous `py-ess-<uuid4>` identifier is used
  for the mandatory (non-authenticating) `userId` API parameter, unless you provide your own.

## Installation

```bash
pip install -e .
```

## Quick start

```python
from pyess import ESS

ess = ESS()  # uses an auto-generated anonymous userId (see below)

# Browse the codebook (parsed from the bundled ESS "Datafile codebook")
codebook = ess.codebook
datafile = codebook.find_datafile("ESS11")
print(datafile.doi)  # "10.21338/ess11e04_2"

# Download (or load from local cache) the actual data
dataset = ess.load(datafile.doi)  # defaults to fileFormat=parquet

# Index like a dict
print(len(dataset))                 # number of respondents
print(dataset.columns)              # variable/column names
print(dataset["cntry"].values)      # raw coded values, e.g. ["DE", "FR", ...]
print(dataset["cntry"].decoded())   # ["Germany", "France", ...]
print(dataset["cntry"].variable.label)  # "Country"
print(dataset[0])                   # first respondent as a dict

# Full JSON-serializable representation (variable metadata + records)
import json
json.dumps(dataset.to_dict())
```

## The `userId` parameter

The ESS API requires a `userId` query parameter on every request. Per the API docs,
this is used only for usage statistics, not authentication. `py-ess` follows common
SDK practice (similar to npm/pip telemetry client IDs): it generates a random,
anonymous `py-ess-<uuid4>` identifier once, caches it in your user config directory,
and reuses it on every call — no personal data (hostname, IP, username) is embedded.

You can override this:

```python
ess = ESS(user_id="my-registered-user-id")
```

or via the `PYESS_USER_ID` environment variable.

## Development

```bash
pip install -e ".[dev]"
pytest
```
