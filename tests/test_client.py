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


def test_load_local_csv_with_polars(tmp_path):
    pl = pytest.importorskip("polars")
    csv_path = tmp_path / "ess.csv"
    csv_path.write_text("idno,cntry\n1,DE\n2,FR\n", encoding="utf-8")
    ess = ESS(user_id=configured_user_id())

    dataset = ess.load_local_csv(csv_path, variables=["cntry"], engine="polars")

    assert isinstance(dataset.dataframe, pl.DataFrame)
    assert dataset.columns == ["idno", "cntry"]
    assert dataset["cntry"].values == ["DE", "FR"]
    assert dataset["cntry"].decoded() == ["Germany", "France"]
    assert dataset["cntry"][1] == "FR"
    assert dataset[0] == {"idno": 1, "cntry": "DE"}
    assert dataset[-1] == {"idno": 2, "cntry": "FR"}
    assert dataset.to_records() == [
        {"idno": 1, "cntry": "DE"},
        {"idno": 2, "cntry": "FR"},
    ]


def test_load_local_csv_recodes_missing_values_by_default(tmp_path):
    """stfeco's codebook-designated codes 77/88/99 ("Refusal"/"Don't
    know"/"No answer") should become NaN, same as the API's
    recodeMissingValues=true, without having to ask for it explicitly."""
    csv_path = tmp_path / "ess.csv"
    csv_path.write_text(
        "idno,cntry,stfeco\n1,DE,5\n2,DE,77\n3,DE,88\n4,DE,99\n5,DE,10\n",
        encoding="utf-8",
    )
    ess = ESS(user_id=configured_user_id())

    dataset = ess.load_local_csv(csv_path, variables=["stfeco"])

    values = dataset["stfeco"].values
    assert values[0] == 5
    assert pd.isna(values[1])
    assert pd.isna(values[2])
    assert pd.isna(values[3])
    assert values[4] == 10


def test_load_local_csv_recode_missing_values_false_keeps_raw_codes(tmp_path):
    csv_path = tmp_path / "ess.csv"
    csv_path.write_text("idno,stfeco\n1,5\n2,77\n", encoding="utf-8")
    ess = ESS(user_id=configured_user_id())

    dataset = ess.load_local_csv(
        csv_path, variables=["stfeco"], recode_missing_values=False
    )

    assert dataset["stfeco"].values == [5, 77]


def test_load_local_csv_polars_infers_schema_from_full_file(tmp_path):
    """Regression test: a decimal value beyond Polars' sampled rows should
    not raise a parse error when full_schema_scan is enabled (the default).
    """
    pytest.importorskip("polars")
    csv_path = tmp_path / "ess.csv"
    rows = ["idno,wkhtot"]
    rows.extend(f"{i},40" for i in range(1, 200))
    rows.append("200,8.5")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    ess = ESS(user_id=configured_user_id())

    dataset = ess.load_local_csv(csv_path, engine="polars")

    assert dataset["wkhtot"][-1] == 8.5

    with pytest.raises(Exception):
        ess.load_local_csv(csv_path, engine="polars", full_schema_scan=False)


def test_load_local_csv_rejects_unknown_engine(tmp_path):
    csv_path = tmp_path / "ess.csv"
    csv_path.write_text("idno\n1\n", encoding="utf-8")
    ess = ESS(user_id=configured_user_id())

    with pytest.raises(ValueError, match="expected 'pandas' or 'polars'"):
        ess.load_local_csv(csv_path, engine="other")


def test_dataset_missing_variable_lists_available_columns(tmp_path):
    csv_path = tmp_path / "ess.csv"
    csv_path.write_text("idno,cntry\n1,DE\n", encoding="utf-8")
    dataset = ESS(user_id=configured_user_id()).load_local_csv(csv_path)

    with pytest.raises(KeyError, match="stfeco.*Available columns: idno, cntry"):
        dataset["stfeco"]


class TestLoadLocalCsvByRound:
    def test_splits_merged_file_into_one_dataset_per_round(self, tmp_path):
        csv_path = tmp_path / "ess.csv"
        csv_path.write_text(
            "idno,essround,cntry,stfeco\n"
            "1,1,DE,5\n"
            "2,1,FR,6\n"
            "3,2,DE,7\n",
            encoding="utf-8",
        )
        ess = ESS(user_id=configured_user_id())

        datasets = ess.load_local_csv_by_round(csv_path, variables=["stfeco"])

        assert set(datasets) == {"10.21338/ess1e06_7", "10.21338/ess2e03_6"}
        round1 = datasets["10.21338/ess1e06_7"]
        assert len(round1) == 2
        assert round1["cntry"].values == ["DE", "FR"]
        round2 = datasets["10.21338/ess2e03_6"]
        assert len(round2) == 1
        assert round2["stfeco"].values == [7]

    def test_drops_columns_entirely_absent_for_a_given_round(self, tmp_path):
        """Regression test: a merged local CSV can have a column (e.g. a
        weight or year column) populated for one round but entirely blank
        for another - each per-round Dataset should only keep columns that
        actually have data for that specific round, so "pick the first
        present column" logic downstream behaves the same as it would
        loading each round from the API separately."""
        csv_path = tmp_path / "ess.csv"
        csv_path.write_text(
            "idno,essround,cntry,anweight,pspwght\n"
            "1,1,DE,,0.9\n"
            "2,2,DE,1.1,0.8\n",
            encoding="utf-8",
        )
        ess = ESS(user_id=configured_user_id())

        datasets = ess.load_local_csv_by_round(csv_path)

        round1 = datasets["10.21338/ess1e06_7"]
        assert "anweight" not in round1.columns
        assert "pspwght" in round1.columns
        round2 = datasets["10.21338/ess2e03_6"]
        assert "anweight" in round2.columns
        assert "pspwght" in round2.columns

    def test_recodes_missing_values_per_round(self, tmp_path):
        csv_path = tmp_path / "ess.csv"
        csv_path.write_text(
            "idno,essround,cntry,stfeco\n"
            "1,1,DE,5\n"
            "2,1,DE,77\n"
            "3,2,DE,88\n",
            encoding="utf-8",
        )
        ess = ESS(user_id=configured_user_id())

        datasets = ess.load_local_csv_by_round(csv_path, variables=["stfeco"])

        round1_values = datasets["10.21338/ess1e06_7"]["stfeco"].values
        assert round1_values[0] == 5
        assert pd.isna(round1_values[1])
        round2_values = datasets["10.21338/ess2e03_6"]["stfeco"].values
        assert pd.isna(round2_values[0])

    def test_missing_round_column_raises_clear_error(self, tmp_path):
        csv_path = tmp_path / "ess.csv"
        csv_path.write_text("idno,cntry\n1,DE\n", encoding="utf-8")
        ess = ESS(user_id=configured_user_id())

        with pytest.raises(KeyError, match="essround"):
            ess.load_local_csv_by_round(csv_path)

    def test_unknown_round_number_is_skipped_with_warning(self, tmp_path, caplog):
        csv_path = tmp_path / "ess.csv"
        csv_path.write_text(
            "idno,essround,cntry\n1,1,DE\n2,9999,DE\n",
            encoding="utf-8",
        )
        ess = ESS(user_id=configured_user_id())

        with caplog.at_level("WARNING", logger="pyess"):
            datasets = ess.load_local_csv_by_round(csv_path)

        assert set(datasets) == {"10.21338/ess1e06_7"}
        assert "9999" in caplog.text

    def test_with_polars_engine(self, tmp_path):
        pl = pytest.importorskip("polars")
        csv_path = tmp_path / "ess.csv"
        csv_path.write_text(
            "idno,essround,cntry,anweight\n"
            "1,1,DE,\n"
            "2,2,DE,1.1\n",
            encoding="utf-8",
        )
        ess = ESS(user_id=configured_user_id())

        datasets = ess.load_local_csv_by_round(csv_path, engine="polars")

        assert isinstance(datasets["10.21338/ess1e06_7"].dataframe, pl.DataFrame)
        assert "anweight" not in datasets["10.21338/ess1e06_7"].columns
        assert "anweight" in datasets["10.21338/ess2e03_6"].columns
