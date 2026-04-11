from opentrons import protocol_api

metadata = {
    "protocolName": "CLSI M07 Broth Microdilution Antimicrobial Susceptibility Test for Aerobic Bacteria",
    "author": "OpenAI",
    "description": "Generated from JSON specification. Includes executable deck setup and comments for non-automatable or ambiguous steps.",
    "apiLevel": "2.13"
}


def run(protocol: protocol_api.ProtocolContext):
    # Labware setup
    plate = protocol.load_labware('opentrons_96_wellplate_200ul_pcr_full_skirt', '1')
    tiprack_300 = protocol.load_labware('opentrons_96_tiprack_300ul', '2')

    # Pipette setup
    p300 = protocol.load_instrument('p300_single_gen2', mount='right', tip_racks=[tiprack_300])

    # Reagents noted in source JSON (not all have defined deck positions in the extracted protocol)
    protocol.comment('Reagents referenced by source: cation-adjusted Mueller-Hinton broth, iron-depleted cation-adjusted Mueller-Hinton broth, Mueller-Hinton fastidious broth, lysed horse blood, NaCl, Tween-80, calcium, magnesium, zinc, sterile water, saline, tryptic soy broth, antimicrobial stock solutions, bacterial inoculum.')

    # Step 1
    protocol.comment('Step 1: Dispense 50 uL of antimicrobial agent at 2X the desired final concentration into test wells.')
    protocol.comment('# SKIPPED: source_location was null for antimicrobial agent transfer')
    protocol.comment('# SKIPPED: destination_location "antibiotic test wells" is ambiguous and no well map was provided')

    # Step 2
    protocol.comment('Step 2: Include a growth control well with no antibiotic.')
    protocol.comment('# SKIPPED: source_location was null for growth control transfer')
    protocol.comment('# SKIPPED: destination_location "growth control well" is ambiguous and no exact well was provided')

    # Step 3
    protocol.comment('Step 3: Storage/incubation step for prepared panels.')
    protocol.comment('# SKIPPED: source_location was null for incubate/storage step')
    protocol.comment('# SKIPPED: destination_location was null for incubate/storage step')
    protocol.comment('# SKIPPED: duration_seconds was null for incubate/storage step')
    protocol.comment('# SKIPPED: temperature_celsius was null or incompletely specified for incubate/storage step')
    protocol.comment('Manual step note: Prepared panels may be stored sealed in plastic bags at <= -20C, preferably <= -60C, for several months.')

    # Step 4
    protocol.comment('Step 4: Thaw frozen panels before inoculation.')
    protocol.comment('# SKIPPED: source_location was null for thaw/incubate step')
    protocol.comment('# SKIPPED: destination_location was null for thaw/incubate step')
    protocol.comment('# SKIPPED: duration_seconds was null for thaw/incubate step')
    protocol.comment('# SKIPPED: temperature_celsius was null for thaw/incubate step')
    protocol.comment('Manual step note: If frozen panels are used, thaw completely to room temperature before inoculation; inoculate within 4 hours and do not refreeze.')

    # Step 5
    protocol.comment('Step 5: Prepare bacterial suspension and adjust to 0.5 McFarland.')
    protocol.comment('# SKIPPED: volume_ul was null for mix step')
    protocol.comment('# SKIPPED: source_location was null for mix step')
    protocol.comment('# SKIPPED: destination_location was null for mix step')
    protocol.comment('Manual step note: Prepare bacterial suspension from 3-4 isolated colonies from an 18-24 hour culture on non-selective media and adjust to 0.5 McFarland.')

    # Step 6
    protocol.comment('Step 6: Add 50 uL inoculum to each well of the panel.')
    protocol.comment('# SKIPPED: source_location was null for inoculum transfer to all panel wells')
    protocol.comment('# SKIPPED: destination_location "all panel wells" is ambiguous because no specific plate map or well set was provided')
    protocol.comment('Manual step note: Add inoculum within 15 minutes of inoculum preparation or McFarland adjustment. Final target concentration is approximately 5 x 10^5 CFU/mL in 100 uL total volume.')

    # Step 7
    protocol.comment('Step 7: Incubate inoculated microdilution panel.')
    protocol.comment('Manual incubation required: 35.0C for 57600 seconds (16 hours) in ambient air for routine non-fastidious organisms unless organism/drug-specific conditions apply.')
    protocol.delay(seconds=57600)

    # Step 8
    protocol.comment('Step 8: Upper end of standard incubation window.')
    protocol.comment('Manual incubation note: 35.0C for 72000 seconds (20 hours) may be used as the upper end of the standard window depending on organism/drug-specific conditions.')
    protocol.delay(seconds=72000)

    # Additional extraction notes
    protocol.comment('Additional extraction notes: Exact antibiotic identities, concentrations, dilution series layout, and source/destination well coordinates were not provided. Species-specific media modifications and atmospheric requirements depend on organism/drug combination and are not encoded as executable liquid-handling steps here.')
