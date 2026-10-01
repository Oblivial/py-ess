# py-ess

A Python library for dynamically loading [European Social Survey (ESS)](https://www.europeansocialsurvey.org/)
data **on demand**, via the [ESS API](https://api.ess.sikt.no/docs), and exposing it as
indexable, self-describing, JSON-serializable Python objects.

## Quick start

```python
from pyess import ESS

# Get your ESS user ID at https://ess.sikt.no/en/api after logging in.
ess = ESS(user_id="your-ess-user-id")

# Look up a variable and see which ESS rounds it was collected in
variable = ess.codebook["netusoft"]
print(variable.label)   # "Internet use, how often"
print(variable.rounds)  # every round DOI it appears in

# Load its data directly, by name + round - no DOI lookup required
values = ess.load_variable("netusoft", round_="ESS11")
print(values.decoded())   # ["Never", "Only occasionally", ...] instead of raw codes
```

See below for loading a whole round's dataset, `[]`/`.` indexing, JSON export, and more.

## Installation

`py-ess` is currently in beta and not yet published to PyPI. Install directly from GitHub:

```bash
pip install git+https://github.com/Oblivial/py-ess.git@v0.1.0b3
```

This pins to the [`v0.1.0b3`](https://github.com/Oblivial/py-ess/releases/tag/v0.1.0b3) tag,
published at commit [`0f2f40d`](https://github.com/Oblivial/py-ess/commit/0f2f40d), so your
install won't change under you as development continues on `main`. Drop the `@v0.1.0b3`
(i.e. just `pip install git+https://github.com/Oblivial/py-ess.git`) to track the latest commit
on `main` instead.

For local development (editable install, e.g. from a clone of this repo):

```bash
git clone https://github.com/Oblivial/py-ess.git
cd py-ess
pip install -e ".[dev]"
```

Development and client tests require a real ESS user ID. Get it by logging in
at [`https://ess.sikt.no/en/api`](https://ess.sikt.no/en/api), copy
`.env.example` to `.env`, and put your ID in the local `.env` file:

```powershell
Copy-Item .env.example .env
# Edit .env and replace the placeholder with your ESS user ID.
pytest -q
```

The test configuration loads `.env` automatically, and `.env` is ignored by
Git. You can also configure the variable directly in PowerShell:

```powershell
$env:PYESS_USER_ID = "your-ess-user-id"
pytest -q
```

## Guide

### Looking up variables and rounds

```python
variable = ess.codebook["netusoft"]        # or ess.codebook.netusoft
variable.label            # "Internet use, how often"
variable.question_texts   # respondent-facing question wording
variable.rounds           # every round DOI this variable was collected in
variable.label_for(1)     # human-readable label for a coded value

ess.codebook.get_round("ESS11")            # -> Round(doi=..., name=..., countries=[...])
ess.codebook.variables_in_round("ESS11")   # every Variable collected in that round
```

If a variable was only ever collected in a single round, `round_=` can be omitted from
`ess.load_variable(...)` and it resolves automatically; if it appears in multiple rounds,
`round_` is required to disambiguate.

### Loading a whole round's dataset

```python
dataset = ess.load_round("ESS11")   # same as ess.load(codebook.get_round("ESS11").doi)

len(dataset)                 # number of respondents
dataset.columns              # variable/column names
dataset["cntry"].values      # raw coded values, e.g. ["DE", "FR", ...]
dataset["cntry"].decoded()   # ["Germany", "France", ...]
dataset[0]                   # first respondent as a dict
```

You can also load by DOI directly if you already have one: `ess.load("10.21338/ess11e04_2")`.

### Loading a local ESS CSV

Local ESS CSV files can be loaded without an API request. The bundled codebook
is still used to provide variable labels and decoded value labels:

For workflows that need to process large amounts of data in bulk, loading
directly from a local file can improve performance by avoiding repeated
downloads or API requests.

```python
dataset = ess.load_local_csv(
  "path/to/ess11.csv",
  variables=["cntry", "stfeco"],
)

dataset["stfeco"].decoded()
```

Pandas is used by default. To use Polars instead, install the optional extra
and select it when loading the local CSV:

```bash
pip install "py-ess[polars]"
```

```python
dataset = ess.load_local_csv("path/to/ess11.csv", engine="polars")
polars_frame = dataset.dataframe
```

The `Dataset` indexing and export methods work with either backend; the
`dataframe` property returns the selected backend's native dataframe.

With `engine="polars"`, the full file is scanned to infer each column's dtype
by default (`full_schema_scan=True`). This avoids parse errors on ESS columns
that are mostly integers but contain an occasional decimal value further down
the file (e.g. `wkhtot`), which Polars' default sampled inference can miss.
Pass `full_schema_scan=False` to restore Polars' faster, sampled inference if
you're confident your file doesn't have such mixed-dtype columns.

The optional `variables` argument checks that the requested columns are present
and raises an error listing the available columns when the wrong ESS file is
supplied. Without that argument, accessing a missing variable produces the
same explanatory error. When `variables` is supplied, missing-value recoding
(see below) is also limited to just those columns, which is considerably
faster than recoding every column in a full ESS datafile.

#### Splitting a merged local CSV by round

A local CSV typically bundles *every* ESS round together in one file (unlike
the API, which serves one round per request), and rounds differ in which
columns they even have (e.g. `anweight` doesn't exist before round 4;
`inwyys` doesn't exist before round 3). If your code picks "the best
available column" out of several candidates (a common pattern for weight or
interview-year columns), doing that over the whole merged file can silently
make the wrong row-level choice for whichever round doesn't populate the
column it picked.

`load_local_csv_by_round` avoids this by splitting the file into one
`Dataset` per round, keyed by that round's DOI - exactly like loading each
round from the API separately, so the same "pick the first present column"
logic works correctly either way:

```python
datasets = ess.load_local_csv_by_round(
    "path/to/merged_ess.csv",
    variables=["cntry", "stfeco"],
)
datasets["10.21338/ess11e04_2"]["stfeco"].decoded()
```

Each returned dataset only keeps columns that have at least one real (raw,
pre-recoding) value for that specific round; columns that are entirely blank
for a round are dropped, so callers never have to reason about per-round
column availability themselves. The round-identifying column defaults to
`essround` (override with `round_column=...` if yours differs).

### File formats

`ess.load(...)` / `ess.load_round(...)` accept `file_format="parquet"` (default), `"csv"`,
`"sav"` (SPSS), or `"dta"` (Stata) - the wire format the datafile is downloaded in.

### Missing-value recoding

ESS codes don't-know/refused/no-answer/not-applicable-style responses as
designated-missing values (e.g. `77`/`88`/`99` for a 0-10 scale), rather than
leaving them blank. `recode_missing_values` (default `True` on `ess.load(...)`,
`ess.load_local_csv(...)`, and `ess.load_local_csv_by_round(...)`) recodes
those to system missing (`NaN`/`null`) so they don't silently skew statistics
computed over the raw column. Set it to `False` to get the original,
undecoded codes back.

The *mechanism* differs depending on where the data comes from, but the
result is the same either way:

- `ess.load(...)` / `ess.load_round(...)` / `ess.load_variable(...)`: the
  flag is sent to the ESS API as `recodeMissingValues=true`, so recoding
  happens server-side, before the file is even downloaded.
- `ess.load_local_csv(...)` / `ess.load_local_csv_by_round(...)`: there is no
  server to ask, since the file is already on disk. Instead, py-ess recodes
  it locally, using the designated-missing value codes recorded in the
  bundled codebook (parsed from each variable's "*) Missing value"-flagged
  categories, e.g. "Refusal", "Don't know", "No answer" - see
  `Variable.missing_values`).

### `[]` vs. `.` access

Both `dataset["cntry"]` and `dataset.cntry` (likewise `codebook["cntry"]` / `codebook.cntry`)
return the same thing. This mirrors how `pandas.DataFrame` itself works: `df["col"]` is the
reliable, fully general form that works for *any* column name, while `df.col` is convenience
sugar that only works when the name doesn't collide with a real attribute/method (e.g. a
column literally named `columns` or `to_dict`) and is a valid Python identifier. `py-ess`
follows the same rule — `.` access is only ever a fallback used when normal attribute lookup
fails, so real attributes and methods always win and are never silently shadowed. When in
doubt, or when working with dynamic/unknown column names, prefer `[]`.

### JSON / dict export

```python
dataset["cntry"].to_dict()   # {"name": ..., "variable": {...}, "values": [...]}
dataset.to_dict()            # whole dataset: variable metadata + per-respondent records
dataset.to_records()         # list of per-respondent dicts, no metadata

import json
json.dumps(dataset.to_dict())
```

### The `userId` parameter

The ESS API requires a registered ESS user ID on every data request. It is used
for usage statistics rather than authentication, but an arbitrary UUID or a
locally generated ID is not accepted. Get your ID by logging in at
[`https://ess.sikt.no/en/api`](https://ess.sikt.no/en/api).

Pass it directly:

```python
ess = ESS(user_id="your-ess-user-id")
```

Or configure it through the `PYESS_USER_ID` environment variable:

```powershell
$env:PYESS_USER_ID = "your-ess-user-id"
```

`ESS()` without a configured ID raises a helpful error instead of making a
request that the API will reject. `load_local_csv()` does not need an ID because
it reads only from disk.

## Features

- **Variable-first indexing** — look up a variable by name (`codebook["netusoft"]`), see every
  ESS round it appears in (`.rounds`), and load its data directly (`ess.load_variable(...)`)
  without ever having to look up a DOI yourself.
- **Lazy, on-demand loading** — datafiles are only downloaded when you ask for them,
  and are cached on disk (`platformdirs` user cache directory) so repeat access is instant.
- **Codebook-joined metadata** — variable labels, respondent-facing question text, and
  coded value → category label mappings, automatically matched to any loaded dataset.
- **Indexable like a dict/JSON object** — `dataset["netuse"]` or `dataset.netuse`,
  `dataset[0]`, `dataset.to_dict()`.
- **Round discovery** — `codebook.get_round("ESS11")` / `codebook.variables_in_round("ESS11")`,
  including which countries participated, without manually looking up DOIs from the docs.
- **Multiple wire formats** — `parquet` (default), `csv`, `sav` (SPSS), `dta` (Stata).
- **Missing-value recoding on by default** — designated-missing codes (Refusal/Don't
  know/No answer/etc.) are recoded to `NaN`/`null` for both API downloads and local CSVs.
- **Explicit API identity** — API requests use the registered ESS user ID from
  the ESS portal; local CSV loading works without an API identity.

## Why not just use `pd.read_parquet(url)`?

The ESS API docs already show you can load a datafile directly with pandas in one line.
If that's all you need, do that — no library required.

`py-ess` exists for the part pandas (or any bare API call) doesn't give you: **the codebook**,
and **not having to think in terms of datafiles/DOIs at all**. Raw ESS datafiles are just coded
values (`cntry: "DE"`, `netuse: 0`, ...), organized by round — so normally you first have to look
up which datafile/DOI you need, download it, and only then dig around inside it. `py-ess` inverts
that: **variables are the primary thing you index by**, and each variable already knows which
ESS round(s) it was collected in. It also joins the official ESS "Datafile codebook" (~2,800
variables across all rounds) to whatever datafile you load, so coded survey data becomes
self-describing, adds on-disk caching so repeat loads are instant.

## Internals: where the variable ↔ round mapping comes from

ESS's own bundled "Datafile codebook" (the source `py-ess` uses for variable labels, question
text, and value labels) lists every variable exactly once, with **no record of which round(s)**
it was collected in. That mapping isn't published anywhere in the public ESS API either.

Instead, `py-ess` ships a small pre-built index (`src/pyess/resources/rounds.json`) that was
scraped once, offline, from the ESS Data Portal's own (undocumented) GraphQL backend — see
[`scripts/build_rounds_index.py`](scripts/build_rounds_index.py) for the full, commented
scraper. This data only changes when ESS publishes a new round or revises an existing datafile
edition (a few times per year at most), so it's committed as a static resource rather than
fetched at runtime — no live scraping happens when you import or use `py-ess`. Re-run the
script and commit the updated `rounds.json` whenever a new round/edition ships.

## Internals: keeping the package small

The official ESS codebook is a ~10MB HTML file. Rather than shipping that raw file (and paying
tens of seconds of parsing cost on every fresh install), `py-ess` ships a pre-parsed,
gzip-compressed JSON snapshot instead (`src/pyess/resources/codebook.json.gz`, ~360KB — about
25x smaller), built by [`scripts/build_codebook_json.py`](scripts/build_codebook_json.py). This
snapshot already has the round-membership mapping above joined in, so loading it at runtime is
just a gzip decompress + `json.loads` (near-instant), no HTML parsing required.

The raw `codebook.html` and `rounds.json` stay in the git repo as the build step's source
input, but are excluded from built sdists/wheels (see `pyproject.toml`). If you're developing
`py-ess` itself and change `codebook.html` or `rounds.json`, re-run the build script and commit
the updated `codebook.json.gz`:

```bash
python scripts/build_rounds_index.py    # only if a new ESS round/edition was released
python scripts/build_codebook_json.py
```

## Development

```bash
pip install -e ".[dev]"
pytest
```
