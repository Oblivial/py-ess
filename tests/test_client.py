import io
import os

import pandas as pd
import pytest
import responses

from pyess.client import ESS, ESSAPIError


def configured_user_id():
    user_id = os.environ.get("PYESS_USER_ID")
    if not user_id:
        pytest.fail(
            "Set PYESS_USER_ID to your ESS user ID before running client tests. "
            "Get it at https://ess.sikt.no/en/api."
        )
    return user_id


def test_empty_constructor_without_user_id(monkeypatch):
    monkeypatch.delenv("PYESS_USER_ID", raising=False)
    with pytest.raises(ValueError, match=r"https://ess\.sikt\.no/en/api"):
        ESS()


def test_live_api_loads_real_ess_data(tmp_path):
    ess = ESS(user_id=configured_user_id(), cache_dir=tmp_path, use_cache=False)

    dataset = ess.load("10.21338/ess2e03_6")

    assert len(dataset) > 0
    assert "idno" in dataset
    assert dataset["cntry"][0] == "AT"


@pytest.fixture
def sample_parquet_bytes():
    df = pd.DataFrame({"idno": [1, 2], "cntry": ["DE", "FR"]})
    buf = io.BytesIO()
    df.to_parquet(buf)
    return buf.getvalue()


@responses.activate
def test_load_downloads_and_caches(tmp_path, sample_parquet_bytes):
    responses.add(
        responses.GET,
        "https://api.ess.sikt.no/v1/data/dataFile/10.21338/ess11e04_2",
        body=sample_parquet_bytes,
        status=200,
        content_type="application/octet-stream",
    )

    ess = ESS(user_id=configured_user_id(), cache_dir=tmp_path)
    dataset = ess.load("10.21338/ess11e04_2")

    assert len(dataset) == 2
    assert dataset.columns == ["idno", "cntry"]
    assert dataset["cntry"].values == ["DE", "FR"]
    assert dataset["cntry"].decoded() == ["Germany", "France"]
    assert dataset[0] == {"idno": 1, "cntry": "DE"}

    # Attribute-style access is equivalent to item-style access for columns.
    assert dataset.cntry.values == dataset["cntry"].values
    assert dataset.idno.values == [1, 2]
    with pytest.raises(AttributeError):
        _ = dataset.not_a_real_column
    # Real attributes/methods always take precedence over columns.
    assert dataset.columns == ["idno", "cntry"]

    cache_file = tmp_path / "10.21338" / "ess11e04_2.parquet"
    assert cache_file.exists()

    # Second call should use cache, not hit network again.
    responses.reset()
    dataset2 = ess.load("10.21338/ess11e04_2")
    assert dataset2.columns == ["idno", "cntry"]


@responses.activate
def test_load_raises_on_error(tmp_path):
    responses.add(
        responses.GET,
        "https://api.ess.sikt.no/v1/data/dataFile/10.21338/bogus",
        json={"code": 201, "message": "DOI URL resolution error", "requestId": "abc"},
        status=400,
    )
    ess = ESS(user_id=configured_user_id(), cache_dir=tmp_path, use_cache=False)
    with pytest.raises(ESSAPIError, match="DOI URL resolution error"):
        ess.load("10.21338/bogus")


def test_invalid_doi_raises_value_error(tmp_path):
    ess = ESS(user_id=configured_user_id(), cache_dir=tmp_path)
    with pytest.raises(ValueError):
        ess.load("not-a-doi")


@responses.activate
def test_load_round_by_label(tmp_path, sample_parquet_bytes):
    responses.add(
        responses.GET,
        "https://api.ess.sikt.no/v1/data/dataFile/10.21338/ess11e04_2",
        body=sample_parquet_bytes,
        status=200,
        content_type="application/octet-stream",
    )
    ess = ESS(user_id=configured_user_id(), cache_dir=tmp_path)
    dataset = ess.load_round("ESS11")
    assert dataset.columns == ["idno", "cntry"]
    assert dataset.datafile.doi == "10.21338/ess11e04_2"


@responses.activate
def test_load_variable_by_name_and_round(tmp_path, sample_parquet_bytes):
    responses.add(
        responses.GET,
        "https://api.ess.sikt.no/v1/data/dataFile/10.21338/ess11e04_2",
        body=sample_parquet_bytes,
        status=200,
        content_type="application/octet-stream",
    )
    ess = ESS(user_id=configured_user_id(), cache_dir=tmp_path)
    series = ess.load_variable("cntry", round_="ESS11")
    assert series.values == ["DE", "FR"]
    assert series.decoded() == ["Germany", "France"]


def test_load_variable_unknown_round_raises(tmp_path):
    ess = ESS(user_id="py-ess-test", cache_dir=tmp_path)
    with pytest.raises(KeyError):
        ess.load_variable("cntry", round_="not-a-real-round")


def test_dataset_to_dict_includes_variable_metadata(tmp_path, sample_parquet_bytes):
    import responses as resp_module

    with resp_module.RequestsMock() as rsps:
        rsps.add(
            rsps.GET,
            "https://api.ess.sikt.no/v1/data/dataFile/10.21338/ess11e04_2",
            body=sample_parquet_bytes,
            status=200,
        )
        ess = ESS(user_id=configured_user_id(), cache_dir=tmp_path)
        dataset = ess.load("10.21338/ess11e04_2")

    data = dataset.to_dict()
    assert data["variables"]["cntry"]["label"] == "Country"
    assert data["records"] == [
        {"idno": 1, "cntry": "DE"},
        {"idno": 2, "cntry": "FR"},
    ]


def test_load_local_csv_validates_requested_variables(tmp_path):
    csv_path = tmp_path / "ess.csv"
    csv_path.write_text("idno,cntry\n1,DE\n", encoding="utf-8")
    ess = ESS(user_id=configured_user_id())

    dataset = ess.load_local_csv(csv_path, variables=["cntry"])

    assert dataset["cntry"].values == ["DE"]
    with pytest.raises(KeyError, match="stfeco.*Available columns: idno, cntry"):
        ess.load_local_csv(csv_path, variables=["stfeco"])


def test_dataset_missing_variable_lists_available_columns(tmp_path):
    csv_path = tmp_path / "ess.csv"
    csv_path.write_text("idno,cntry\n1,DE\n", encoding="utf-8")
    dataset = ESS(user_id=configured_user_id()).load_local_csv(csv_path)

    with pytest.raises(KeyError, match="stfeco.*Available columns: idno, cntry"):
        dataset["stfeco"]
