from fastapi_contract.adapters.fastapi import normalize_top_level_selection
from fastapi_contract.domain.model import Completeness, ObjectSelection, WholeSelection


def _entry_names(value: object) -> tuple[str, ...]:
    assert value is not None
    root = value.root  # type: ignore[attr-defined]
    assert isinstance(root, ObjectSelection)
    return tuple(entry.name for entry in root.fields)


def test_none_remains_absent_selection() -> None:
    assert normalize_top_level_selection(None) is None


def test_empty_selection_is_distinct_from_none() -> None:
    result = normalize_top_level_selection(set())

    assert result is not None
    assert result.completeness is Completeness.COMPLETE
    assert _entry_names(result) == ()


def test_equivalent_collection_forms_have_same_canonical_selection() -> None:
    values = [
        {"email", "name"},
        ["name", "email"],
        ("email", "name"),
        frozenset({"name", "email"}),
    ]

    normalized = [normalize_top_level_selection(value) for value in values]

    assert all(value == normalized[0] for value in normalized)
    assert normalized[0] is not None
    assert _entry_names(normalized[0]) == ("email", "name")
    root = normalized[0].root
    assert isinstance(root, ObjectSelection)
    assert all(isinstance(entry.selection, WholeSelection) for entry in root.fields)


def test_duplicate_entries_are_canonicalized_once() -> None:
    result = normalize_top_level_selection(["email", "email", "name"])

    assert result is not None
    assert _entry_names(result) == ("email", "name")


def test_nested_selector_is_marked_incomplete_in_slice1() -> None:
    result = normalize_top_level_selection({"profile": {"email"}})

    assert result is not None
    assert result.completeness is Completeness.INCOMPLETE
    assert result.incomplete_reason


def test_distinct_nested_selectors_do_not_collapse_to_same_snapshot_fact() -> None:
    email = normalize_top_level_selection({"profile": {"email"}})
    name = normalize_top_level_selection({"profile": {"name"}})

    assert email is not None
    assert name is not None
    assert email.completeness is Completeness.INCOMPLETE
    assert name.completeness is Completeness.INCOMPLETE
    assert email != name


def test_all_selector_is_incomplete_not_unknown_harmless_field() -> None:
    result = normalize_top_level_selection({"__all__"})

    assert result is not None
    assert result.completeness is Completeness.INCOMPLETE
    assert result.incomplete_reason


def test_sequence_index_selector_is_incomplete() -> None:
    result = normalize_top_level_selection({0})

    assert result is not None
    assert result.completeness is Completeness.INCOMPLETE
    assert result.incomplete_reason
