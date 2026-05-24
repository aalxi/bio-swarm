from agents import coder


def test_codegen_prompt_includes_thermocycler_methods():
    prompt = coder.WET_LAB_CODEGEN_SYSTEM_PROMPT
    # The known canonical methods must be listed
    assert "set_block_temperature" in prompt
    assert "open_lid" in prompt
    # The hallucinated method must NOT be in the prompt
    assert "wait_for_block_temperature" not in prompt


def test_codegen_prompt_includes_valid_module_load_names():
    prompt = coder.WET_LAB_CODEGEN_SYSTEM_PROMPT
    assert "thermocycler module gen2" in prompt
    # The underscore form is the May-04 hallucination
    assert "thermocycler_module_gen2" not in prompt


def test_fix_prompt_includes_api_index():
    prompt = coder.WET_LAB_FIX_SYSTEM_PROMPT
    assert "set_block_temperature" in prompt
