from driftwatch.modules.rating_curve import causes


def test_catalog_has_every_required_cause_with_evidence():
    keys = {c.key for c in causes.CAUSES}
    assert keys == {
        "scour",
        "fill",
        "debris",
        "vegetation",
        "datum_change",
        "measurement_quality",
        "insufficient_data",
    }
    assert all(c.evidence for c in causes.CAUSES)


def test_signs_follow_claude_md_convention():
    assert causes.get_cause("scour").expected_sign == "positive"
    assert causes.get_cause("fill").expected_sign == "negative"
    assert causes.get_cause("debris").expected_sign == "negative"
    assert causes.get_cause("debris").transient
    assert causes.get_cause("vegetation").transient
    assert causes.get_cause("datum_change").expected_sign == "either"


def test_causes_for_negative_step_exclude_scour_include_datum():
    keys = {c.key for c in causes.causes_for_sign("negative")}
    assert "fill" in keys and "datum_change" in keys and "scour" not in keys


def test_field_notes_map_to_causes():
    assert causes.cause_for_note("Fill control changed").key == "fill"
    assert causes.cause_for_note("Scour control changed").key == "scour"
    assert causes.cause_for_note("Debris - Moderate").key == "debris"
    assert causes.cause_for_note("Vegetation - Heavy").key == "vegetation"
    assert causes.cause_for_note("Clear") is None
    assert causes.cause_for_note(None) is None


def test_scour_note_disagrees_with_negative_step():
    assert not causes.sign_agrees(causes.get_cause("scour"), "negative")
    assert causes.sign_agrees(causes.get_cause("datum_change"), "negative")
