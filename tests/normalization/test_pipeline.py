from app.normalization.pipeline import extract_fields_from_title


def test_extract_fields_from_title_full_example():
    fields = extract_fields_from_title("Xerjoff Erba Gold Eau de Parfum 100 ml Tester")

    assert fields.concentration == "EDP"
    assert fields.volume_ml == 100
    assert fields.tester is True


def test_extract_fields_from_title_prefers_structured_volume():
    fields = extract_fields_from_title("Xerjoff Erba Gold EDP", structured_volume_ml=100)

    assert fields.volume_ml == 100


def test_extract_fields_missing_data_returns_none():
    fields = extract_fields_from_title("Unrelated product title")

    assert fields.concentration is None
    assert fields.volume_ml is None
    assert fields.tester is False
