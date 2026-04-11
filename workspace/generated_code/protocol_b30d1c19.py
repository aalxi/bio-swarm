from opentrons import protocol_api

metadata = {
    "protocolName": "Broth microdilution antimicrobial susceptibility testing (CLSI M07-based)",
    "author": "OpenAI",
    "description": "Partially automated OT-2 protocol generated from a guideline-style JSON definition. Ambiguous or unspecified fields are explicitly skipped.",
    "apiLevel": "2.13"
}


def run(protocol: protocol_api.ProtocolContext):
    # Load labware implied by the JSON definition
    plate = protocol.load_labware('opentrons_96_wellplate_200ul_pcr_full_skirt', '1')
    tuberack = protocol.load_labware('opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical', '2')

    # Load tip racks for implied pipettes
    tiprack_20 = protocol.load_labware('opentrons_96_tiprack_20ul', '3')
    tiprack_300_a = protocol.load_labware('opentrons_96_tiprack_300ul', '4')
    tiprack_300_b = protocol.load_labware('opentrons_96_tiprack_300ul', '5')

    # Load pipettes implied by the JSON definition
    p20 = protocol.load_instrument('p20_single_gen2', mount='left', tip_racks=[tiprack_20])
    p300 = protocol.load_instrument('p300_single_gen2', mount='right', tip_racks=[tiprack_300_a])
    # The JSON also specifies p300_multi_gen2, but OT-2 supports only one pipette per mount.
    # SKIPPED: p300_multi_gen2 cannot be loaded simultaneously with both single-channel pipettes because only two mounts are available on OT-2.

    # Reagent placeholders in tuberack/plate are not assigned from source because exact mapping is unspecified.
    # SKIPPED: Exact reagent-to-well/tube assignments were not provided in the source JSON.

    # Step 1
    protocol.comment('Step 1: Prepare antimicrobial agent stock solution at at least 1000 ug/mL or at least 10 times the highest concentration to be tested, using the manufacturer-indicated solvent.')
    # SKIPPED: volume_ul was null or ambiguous
    # SKIPPED: source_location was null or ambiguous
    # SKIPPED: destination_location was null or ambiguous

    # Step 2
    protocol.comment('Step 2: Prepare successive two-fold intermediate antimicrobial dilutions (eg 1:2, 1:4, 1:8) in sterile diluent/broth or sterile water.')
    # SKIPPED: volume_ul was null or ambiguous
    # SKIPPED: source_location was null or ambiguous
    # SKIPPED: destination_location was null or ambiguous

    # Step 3
    protocol.comment('Step 3: Dispense antimicrobial-broth solutions into a 96-well microdilution tray so each well contains 0.1 mL broth. Exact well map for concentration series is not provided.')
    # SKIPPED: source_location was null or ambiguous
    # SKIPPED: destination_location was null or ambiguous

    # Step 4
    protocol.comment('Step 4: Prepare bacterial inoculum from 3-5 well-isolated colonies from a pure overnight culture into 4-5 mL suitable broth such as tryptic soy broth.')
    # SKIPPED: volume_ul was null or ambiguous
    # SKIPPED: source_location was null or ambiguous
    # SKIPPED: destination_location was null or ambiguous

    # Step 5
    protocol.comment('Step 5: Incubate broth culture at 35 +/- 2 C until it achieves or exceeds 0.5 McFarland turbidity.')
    # SKIPPED: duration_seconds was null or ambiguous
    protocol.comment('Manual incubation required at approximately 35.0 C.')

    # Step 6
    protocol.comment('Step 6: Adjust inoculum turbidity with sterile saline or broth to 0.5 McFarland standard, approximately 1-2 x 10^8 CFU/mL.')
    # SKIPPED: volume_ul was null or ambiguous
    # SKIPPED: source_location was null or ambiguous
    # SKIPPED: destination_location was null or ambiguous

    # Step 7
    protocol.comment('Step 7: Within 15 minutes of inoculum standardization, inoculate each well. Example given: if wells contain 0.1 mL broth, add 0.01 mL inoculum so inoculum volume does not exceed 10% of well volume. Inoculum should be pre-diluted appropriately so final well concentration is approximately 5 x 10^5 CFU/mL.')
    # SKIPPED: source_location was null or ambiguous
    # SKIPPED: destination_location was null or ambiguous

    # Step 8
    protocol.comment('Step 8: Include a growth control well, a sterility (uninoculated) well, and concurrently test the corresponding quality control organism.')
    # SKIPPED: volume_ul was null or ambiguous
    # SKIPPED: source_location was null or ambiguous
    # SKIPPED: destination_location was null or ambiguous

    # Step 9
    protocol.comment('Step 9: Incubate inoculated microdilution trays within 15 minutes of adding inoculum at 35 +/- 2 C for 16-20 hours in ambient air. Do not stack more than four trays.')
    protocol.comment('Manual incubation required at approximately 35.0 C for 57600 seconds minimum (16 hours), with notes indicating 16-20 hours total.')
    protocol.delay(seconds=57600, msg='Incubation placeholder: remove plate for off-deck incubation at 35 +/- 2 C in ambient air.')

    # Step 10
    protocol.comment('Step 10: Read MIC as the lowest antimicrobial concentration showing no visible turbidity compared with the negative control. Verify QC strain MIC is within acceptable CLSI range and that growth control shows growth while sterility well remains clear.')
    # SKIPPED: volume_ul was null or ambiguous
    # SKIPPED: source_location was null or ambiguous
    # SKIPPED: destination_location was null or ambiguous

    protocol.comment('Protocol complete. This generated script preserves deck setup and explicitly skips underspecified liquid-handling steps rather than guessing values.')
