"""Citation registry: shape, seeded keys, three-state verification."""
from tools.citation_registry import REGISTRY, Citation


def test_registry_has_required_seed_keys():
    required = {
        "MIQE_2009",
        "MIQE_essential_inhibition_testing",
        "MIQE_essential_linear_dynamic_range",
        "MIQE_essential_reaction_volume_and_template",
        "common_practice_cq_gray_zone",
        "PCR_inhibition_matrix_specific_schrader_2012",
    }
    assert required.issubset(REGISTRY.keys())


def test_each_entry_is_a_citation_model():
    for key, entry in REGISTRY.items():
        assert isinstance(entry, Citation), f"{key} is not a Citation"
        assert entry.key == key, f"{key}: key field mismatch ({entry.key})"


def test_citation_types_are_constrained():
    valid = {"paper", "guideline_checklist_item", "common_practice"}
    for entry in REGISTRY.values():
        assert entry.citation_type in valid


def test_quoted_text_present_when_url_present_for_guideline_items():
    for entry in REGISTRY.values():
        if entry.citation_type == "guideline_checklist_item":
            assert entry.url is not None
            assert entry.quoted_text is not None
