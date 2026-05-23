from tools import opentrons_api_index as idx


def test_index_has_required_contexts():
    assert "ProtocolContext" in idx.CONTEXT_METHODS
    assert "InstrumentContext" in idx.CONTEXT_METHODS
    assert "ThermocyclerContext" in idx.CONTEXT_METHODS
    assert "MagneticModuleContext" in idx.CONTEXT_METHODS
    assert "TemperatureModuleContext" in idx.CONTEXT_METHODS
    assert "Labware" in idx.CONTEXT_METHODS


def test_thermocycler_has_known_methods():
    methods = idx.CONTEXT_METHODS["ThermocyclerContext"]
    # These are the canonical names — the May-04 post-mortem flagged
    # wait_for_block_temperature as a known hallucination.
    assert "set_block_temperature" in methods
    assert "set_lid_temperature" in methods
    assert "open_lid" in methods
    assert "close_lid" in methods
    assert "wait_for_block_temperature" not in methods  # this is the hallucinated one


def test_module_load_names_are_strings():
    assert isinstance(idx.VALID_MODULE_LOAD_NAMES, list)
    assert "thermocycler module gen2" in idx.VALID_MODULE_LOAD_NAMES
    assert "magnetic module gen2" in idx.VALID_MODULE_LOAD_NAMES
    # The wrong form (with underscores) must NOT be valid — C.2 was the
    # 'thermocycler_module_gen2' hallucination.
    assert "thermocycler_module_gen2" not in idx.VALID_MODULE_LOAD_NAMES
