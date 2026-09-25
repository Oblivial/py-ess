"""One-off scraper: builds the ESS variable/round/country index bundled with py-ess.

This queries the *live* ESS Data Portal GraphQL API (api.nsd.no/graphql, the
backend for https://ess.sikt.no) to discover, for every published ESS
integrated datafile (round):

- its DOI, human-readable title, and included countries, and
- the full list of variables it contains (id/name, label, and the
  variable-group hierarchy they're organized under).

This metadata is static: it only changes when ESS publishes a new round or a
revised edition of an existing one, which happens a few times a year at most.
So rather than querying it at import time, we run this script manually /
occasionally and commit the resulting JSON (``src/pyess/resources/rounds.json``)
as a bundled resource - the same approach already used for ``codebook.html``.

Usage::

    python scripts/build_rounds_index.py

Re-run this whenever a new ESS round or datafile edition is released, then
commit the updated ``rounds.json``.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

GRAPHQL_URL = "https://api.nsd.no/graphql"
AGENCY_ID = "INT_ESSERIC"

# The full list of ESS integrated datafile DOIs, taken from the ESS API's
# bundled "Datafile codebook" (https://api.ess.sikt.no/docs -> Datafile
# codebook.html). Update this list whenever a new round/edition is released.
DATAFILE_DOIS: List[Dict[str, str]] = [
    {"doi": "10.21338/ess1e06_7", "name": "ESS1 - integrated file, edition 6.7"},
    {"doi": "10.21338/ess2e03_6", "name": "ESS2 - integrated file, edition 3.6 (Italy not included)"},
    {"doi": "10.21338/ess3e03_7", "name": "ESS3 - integrated file, edition 3.7 (Latvia and Romania not included)"},
    {"doi": "10.21338/ess4e04_6", "name": "ESS4 - integrated file, edition 4.6 (Austria and Lithuania not included)"},
    {"doi": "10.21338/ess5e03_6", "name": "ESS5 - integrated file, edition 3.6 (Austria not included)"},
    {"doi": "10.21338/ess6e02_7", "name": "ESS6 - integrated file, edition 2.7"},
    {"doi": "10.21338/ess7e02_3", "name": "ESS7 - integrated file, edition 2.3"},
    {"doi": "10.21338/ess8e02_3", "name": "ESS8 - integrated file, edition 2.3"},
    {"doi": "10.21338/ess9e03_3", "name": "ESS9 - integrated file, edition 3.3"},
    {"doi": "10.21338/ess10e03_3", "name": "ESS10 - integrated file, edition 3.3"},
    {"doi": "10.21338/ess10sce03_2", "name": "ESS10 Self-completion - integrated file, edition 3.2"},
    {"doi": "10.21338/ess11e04_2", "name": "ESS11 - integrated file, edition 4.2"},
]

_UUID_RE = re.compile(r"/datafile/([0-9a-fA-F-]{36})")

_METADATA_QUERY = """
query dataFileMetadata($id: ID!, $instance: Instance!) {
  search {
    dataFileMetadata(id: $id, agencyId: INT_ESSERIC, instance: $instance) {
      id
      version
      variableCount
      citation { internationalIdentifier }
      coverage {
        spatialCoverage {
          countryCategoriesControlledVocabulary { label { en } }
        }
      }
    }
  }
}
"""

_VARIABLES_QUERY = """
query datafileVariablesAndGroups($id: ID!, $version: Int, $instance: Instance!) {
  search {
    dataFileMetadata(id: $id, version: $version, instance: $instance, agencyId: INT_ESSERIC) {
      id
      version
      variableGroups {
        name { en }
        variables { name { en } label { en } }
        variableGroups {
          name { en }
          variables { name { en } label { en } }
          variableGroups {
            name { en }
            variables { name { en } label { en } }
          }
        }
      }
    }
  }
}
"""


def gql(query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload["data"]


def resolve_datafile_id(doi: str) -> str:
    """Follow the DOI redirect to the ESS Data Portal to recover the internal
    datafile UUID that the GraphQL API expects."""
    response = requests.get(f"https://doi.org/{doi}", allow_redirects=True, timeout=30)
    match = _UUID_RE.search(response.url)
    if not match:
        raise RuntimeError(f"Could not resolve datafile id for DOI {doi!r} (landed on {response.url!r})")
    return match.group(1)


def _flatten_variables(groups: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """Recursively flatten the (arbitrarily nested) variableGroups tree into a
    flat list of {name, label} dicts."""
    variables: List[Dict[str, str]] = []
    for group in groups or []:
        for var in group.get("variables") or []:
            name = (var.get("name") or {}).get("en")
            label = (var.get("label") or {}).get("en")
            if name:
                variables.append({"name": name, "label": label or ""})
        variables.extend(_flatten_variables(group.get("variableGroups")))
    return variables


def fetch_round(doi: str, name: str) -> Dict[str, Any]:
    datafile_id = resolve_datafile_id(doi)

    metadata = gql(_METADATA_QUERY, {"id": datafile_id, "instance": "PUBLISHED"})
    df_meta = metadata["search"]["dataFileMetadata"]
    version = df_meta["version"]
    resolved_doi = df_meta["citation"]["internationalIdentifier"]
    if resolved_doi.lower() != doi.lower():
        print(f"  WARNING: DOI mismatch for {name}: expected {doi}, API returned {resolved_doi}", file=sys.stderr)

    countries = [
        c["label"]["en"]
        for c in (df_meta.get("coverage") or {}).get("spatialCoverage", {}).get(
            "countryCategoriesControlledVocabulary", []
        )
        if c.get("label", {}).get("en")
    ]

    variables_data = gql(_VARIABLES_QUERY, {"id": datafile_id, "version": version, "instance": "PUBLISHED"})
    groups = variables_data["search"]["dataFileMetadata"]["variableGroups"]
    variables = _flatten_variables(groups)

    return {
        "doi": doi,
        "name": name,
        "datafile_id": datafile_id,
        "version": version,
        "countries": sorted(countries),
        "variables": variables,
    }


def main() -> None:
    rounds: List[Dict[str, Any]] = []
    for entry in DATAFILE_DOIS:
        print(f"Fetching {entry['name']} ({entry['doi']})...")
        round_data = fetch_round(entry["doi"], entry["name"])
        print(f"  -> {len(round_data['variables'])} variables, {len(round_data['countries'])} countries")
        rounds.append(round_data)
        time.sleep(0.5)  # be a polite citizen towards the shared API

    output_path = Path(__file__).resolve().parent.parent / "src" / "pyess" / "resources" / "rounds.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"rounds": rounds}, indent=1), encoding="utf-8")
    print(f"\nWrote {len(rounds)} rounds to {output_path}")


if __name__ == "__main__":
    main()
