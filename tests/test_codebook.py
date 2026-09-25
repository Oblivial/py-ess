from pyess.codebook import Codebook, load_bundled_codebook


def test_load_bundled_codebook_has_datafiles_and_variables():
    codebook = load_bundled_codebook()
    assert len(codebook.datafiles) >= 10
    assert len(codebook) > 100


def test_find_datafile_by_name():
    codebook = load_bundled_codebook()
    df = codebook.find_datafile("ESS11")
    assert df is not None
    assert df.doi == "10.21338/ess11e04_2"
    assert df.doi_prefix == "10.21338"
    assert df.doi_suffix == "ess11e04_2"


def test_variable_indexing_and_metadata():
    codebook = load_bundled_codebook()
    assert "cntry" in codebook
    var = codebook["cntry"]
    assert var.label == "Country"
    assert var.label_for("DE") == "Germany"
    assert var.label_for("ZZ") is None


def test_variable_with_question_text():
    codebook = load_bundled_codebook()
    var = codebook.get_variable("netuse")
    assert var is not None
    assert var.label == "Personal use of internet/e-mail/www"
    assert any("internet" in q.lower() for q in var.question_texts)
    assert var.label_for("0") == "No access at home or work"


def test_attribute_access_for_variables():
    codebook = load_bundled_codebook()
    assert codebook.cntry is codebook["cntry"]
    assert codebook.cntry.label == "Country"


def test_attribute_access_does_not_shadow_real_attributes():
    codebook = load_bundled_codebook()
    # `.variables` is a real property and must never be confused with a
    # variable literally named "variables" (there isn't one in ESS, but the
    # precedence must hold regardless).
    assert isinstance(codebook.variables, list)


def test_attribute_access_raises_for_unknown_name():
    codebook = load_bundled_codebook()
    import pytest

    with pytest.raises(AttributeError):
        codebook.definitely_not_a_variable


def test_variable_has_round_membership():
    codebook = load_bundled_codebook()
    var = codebook["netusoft"]
    assert len(var.rounds) >= 1
    assert all(doi.startswith("10.21338/") for doi in var.rounds)


def test_get_round_by_label_and_doi():
    codebook = load_bundled_codebook()
    by_label = codebook.get_round("ESS11")
    assert by_label is not None
    assert by_label.doi == "10.21338/ess11e04_2"
    by_doi = codebook.get_round("10.21338/ess11e04_2")
    assert by_doi is by_label
    assert codebook.get_round("nope-not-a-round") is None


def test_variables_in_round():
    codebook = load_bundled_codebook()
    variables = codebook.variables_in_round("ESS1")
    assert len(variables) > 100
    names = {v.id for v in variables}
    assert "essround" in names



    import json

    codebook = load_bundled_codebook()
    data = codebook.to_dict()
    serialized = json.dumps(data)
    assert "cntry" in serialized


def test_from_html_minimal_document():
    html = """
    <html><body>
    <h2>Datafiles</h2>
    <h3>ESS1 - integrated file</h3>
    <p><a href="https://doi.org/10.21338/ess1e06_7">doi</a></p>
    <h2>Variables</h2>
    <div>
      <h3 id="foo">foo</h3>
      <div>Foo label</div>
      <div class="variable-meta-string">Some question</div>
      <div class="data-table">
        <table><tbody>
          <tr><td>1</td><td>Yes</td></tr>
          <tr><td>2</td><td>No</td></tr>
        </tbody></table>
      </div>
    </div>
    </body></html>
    """
    codebook = Codebook.from_html(html)
    assert len(codebook.datafiles) == 1
    assert codebook.datafiles[0].doi == "10.21338/ess1e06_7"
    var = codebook["foo"]
    assert var.label == "Foo label"
    assert var.question_texts == ["Some question"]
    assert var.label_for("1") == "Yes"
