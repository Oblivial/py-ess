import io

import pandas as pd
import pytest
import responses

from pyess.client import ESS, ESSAPIError


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

    ess = ESS(user_id="py-ess-test", cache_dir=tmp_path)
    dataset = ess.load("10.21338/ess11e04_2")

    assert len(dataset) == 2
    assert dataset.columns == ["idno", "cntry"]
    assert dataset["cntry"].values == ["DE", "FR"]
    assert dataset["cntry"].decoded() == ["Germany", "France"]
    assert dataset[0] == {"idno": 1, "cntry": "DE"}

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
    ess = ESS(user_id="py-ess-test", cache_dir=tmp_path, use_cache=False)
    with pytest.raises(ESSAPIError, match="DOI URL resolution error"):
        ess.load("10.21338/bogus")


def test_invalid_doi_raises_value_error(tmp_path):
    ess = ESS(user_id="py-ess-test", cache_dir=tmp_path)
    with pytest.raises(ValueError):
        ess.load("not-a-doi")


def test_dataset_to_dict_includes_variable_metadata(tmp_path, sample_parquet_bytes):
    import responses as resp_module

    with resp_module.RequestsMock() as rsps:
        rsps.add(
            rsps.GET,
            "https://api.ess.sikt.no/v1/data/dataFile/10.21338/ess11e04_2",
            body=sample_parquet_bytes,
            status=200,
        )
        ess = ESS(user_id="py-ess-test", cache_dir=tmp_path)
        dataset = ess.load("10.21338/ess11e04_2")

    data = dataset.to_dict()
    assert data["variables"]["cntry"]["label"] == "Country"
    assert data["records"] == [
        {"idno": 1, "cntry": "DE"},
        {"idno": 2, "cntry": "FR"},
    ]
