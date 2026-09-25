# py-ess

A Python library for dynamically loading [European Social Survey (ESS)](https://www.europeansocialsurvey.org/)
data **on demand**, via the [ESS API](https://api.ess.sikt.no/docs), and exposing it as
indexable, self-describing, JSON-serializable Python objects.

## Why not just use `pd.read_parquet(url)`?

The ESS API docs already show you can load a datafile directly with pandas in one line.
If that's all you need, do that — no library required.

`py-ess` exists for the part pandas (or any bare API call) doesn't give you: **the codebook**.
Raw ESS datafiles are just coded values (`cntry: "DE"`, `netuse: 0`, ...). On their own they
carry no labels, no question wording, and no value → category mappings. `py-ess` parses the
official ESS "Datafile codebook" (~2,800 variables across all rounds) once and automatically
joins it to whatever datafile you load, so coded survey data becomes self-describing:

```python
dataset["netuse"].decoded()        # ["No access at home or work", ...] instead of [0, ...]
dataset["netuse"].variable.label   # "Personal use of internet/e-mail/www"
```

It also adds datafile/round discovery (`codebook.find_datafile("ESS11")` instead of
manually looking up DOIs), on-disk caching so repeat loads are instant, and a stable
anonymous identifier for the API's mandatory `userId` parameter. Everything else
(attribute access, `.to_dict()`, etc.) is convenience sugar on top.

## Features

- **Lazy, on-demand loading** — datafiles are only downloaded when you ask for them,
  and are cached on disk (`platformdirs` user cache directory) so repeat access is instant.
- **Codebook-joined metadata** — variable labels, respondent-facing question text, and
  coded value → category label mappings, automatically matched to any loaded dataset.
- **Indexable like a dict/JSON object** — `dataset["netuse"]` or `dataset.netuse`,
  `dataset[0]`, `dataset.to_dict()`.
- **Datafile/round discovery** — `codebook.find_datafile("ESS11")` instead of manually
  looking up DOIs from the docs.
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

# Index like a dict - or, as a convenience, like an attribute
print(len(dataset))                 # number of respondents
print(dataset.columns)              # variable/column names
print(dataset["cntry"].values)      # raw coded values, e.g. ["DE", "FR", ...]
print(dataset.cntry.values)         # same thing, attribute-style
print(dataset["cntry"].decoded())   # ["Germany", "France", ...]
print(dataset["cntry"].variable.label)  # "Country"
print(dataset[0])                   # first respondent as a dict

# Full JSON-serializable representation (variable metadata + records)
import json
json.dumps(dataset.to_dict())
```

### `[]` vs. `.` access

Both `dataset["cntry"]` and `dataset.cntry` (likewise `codebook["cntry"]` / `codebook.cntry`)
return the same thing. This mirrors how `pandas.DataFrame` itself works: `df["col"]` is the
reliable, fully general form that works for *any* column name, while `df.col` is convenience
sugar that only works when the name doesn't collide with a real attribute/method (e.g. a
column literally named `columns` or `to_dict`) and is a valid Python identifier. `py-ess`
follows the same rule — `.` access is only ever a fallback used when normal attribute lookup
fails, so real attributes and methods always win and are never silently shadowed. When in
doubt, or when working with dynamic/unknown column names, prefer `[]`.

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
