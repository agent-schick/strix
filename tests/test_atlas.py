from strix.report.atlas import normalize_atlas_techniques, technique_url


def test_normalize_atlas_techniques_validates_ids() -> None:
    ids, errors = normalize_atlas_techniques(["aml.t0051", "AML.T0051", "AML.T0054 jailbreak"])
    assert ids == ["AML.T0051", "AML.T0054"]
    assert errors == []


def test_normalize_atlas_techniques_rejects_unknown_and_malformed() -> None:
    ids, errors = normalize_atlas_techniques(["AML.T9999", "T1190"])
    assert ids == []
    assert len(errors) == 2
    assert "unknown ATLAS technique" in errors[0]
    assert "invalid ATLAS technique" in errors[1]


def test_technique_url() -> None:
    assert technique_url("AML.T0051.000") == "https://atlas.mitre.org/techniques/AML.T0051.000"
