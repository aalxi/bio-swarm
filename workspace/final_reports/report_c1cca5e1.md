## Protocol summary
This extracted protocol describes the CLSI M07 broth microdilution method for antimicrobial susceptibility testing of aerobic bacteria, intended to determine minimal inhibitory concentrations (MICs) under standardized conditions. Based on the extraction JSON and bundled source text, the workflow involves preparing 2-fold antimicrobial dilutions from stock solutions in an appropriate broth, dispensing 50 µL of antimicrobial at 2X the desired final concentration into test wells, including a growth control without antibiotic, preparing a bacterial inoculum from 3-4 isolated colonies adjusted to 0.5 McFarland, and adding 50 µL inoculum to each well to reach about 100 µL total volume and an approximate final density of 5 × 10^5 CFU/mL. The protocol also notes optional frozen panel storage at ≤-20°C (preferably ≤-60°C), thawing to room temperature before use, and routine incubation at 35°C for 16-20 hours for non-fastidious organisms, with organism- and drug-specific exceptions described only in notes.

## Generated Opentrons script
```python
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
```

## Simulation result
Pass.

Coding state indicates `simulation_passed: true`, `error_log: null`, and `retry_count: 0`.

Notable warnings/messages reflected in the generated script:
- Multiple transfer and preparation actions were skipped because source locations were null.
- Destination locations such as "antibiotic test wells," "growth control well," and "all panel wells" were ambiguous because no well map was provided.
- Storage, thawing, inoculum preparation, and organism-specific incubation/environment steps are represented as comments or manual notes rather than executable robotic actions.

## Confidence notes from extraction
Null or missing fields in the protocol JSON:
- Step 1: `source_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 2: `source_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 3: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 4: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 5: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 6: `source_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 7: `volume_ul`, `source_location`, `speed_rpm`
- Step 8: `volume_ul`, `source_location`, `speed_rpm`

Extraction notes:
- Source material is a standard overview and workshop handout, not a complete bench protocol with an explicit Opentrons deck layout.
- Exact antibiotic identities, concentrations, dilution series layout, and source/destination well coordinates are not provided in the extracted text.
- Panel storage at subzero temperatures is described, but Opentrons cannot automate freezing; represented as an incubate/storage step with null duration.
- The document states 2-fold dilutions of 10X antimicrobial stock are created in broth or sterile water, but no robot-executable dilution sequence with locations is given.
- Inoculum preparation requires colony picking and McFarland standardization, which are not fully automatable on Opentrons; represented as a mix step with null volume.
- Only one generic 96-well plate labware item is inferred from broth microdilution context; exact validated Opentrons labware name for CLSI panels is not specified in source.
- Pipette model is inferred from required 50 µL transfers; exact pipette type is not stated in the source.
- Species-specific media modifications are described (eg, +2% NaCl, +0.002% Tween-80, added calcium, iron-depleted CAMHB), but applicability depends on organism/drug combination and is not fully specified for a single universal protocol.
- Incubation atmosphere requirements (ambient air, CO2, anaerobic) are described for different organisms but cannot be encoded directly in the provided schema; included in notes.
- Reading MIC endpoints, interpretation rules, skip wells, trailing, and QC are described in the source but are not represented as executable liquid-handling steps in this schema.

## Source citations
- CLSI M07 product page: https://clsi.org/shop/standards/m07/
- SCACM AST workshop handout: https://scacm.org/2025_Spring/Handouts/362-112-25-1perPg_HANDOUT-AST_Workshop.pdf
- Combined research bundle source list: https://www.slideshare.net/slideshow/m07-a10-methods-for-dilution-antimicrobial-susceptibility-tests-for-bacteria-that-grow-aerobically-10th-edition-jean-b-pate/280639424
- bioMérieux AST booklet: https://www.biomerieux.com/content/dam/biomerieux-com/medical-affairs/microbiology/new-ast/biomerieux-AST-BOOKLET-2024-FINAL.pdf
- protocols.io MIC/MBC broth microdilution protocol: https://www.protocols.io/view/minimum-inhibitory-concentration-mic-and-minimum-b-cvpyw5pw.pdf
- TestingLab overview of CLSI M07: https://www.testinglab.com/clsi-m07-dilution-methods-for-antimicrobial-susceptibility-testing
- SECO Mueller Hinton II Broth document: https://www.seco.us/ASSETS/DOCUMENTS/ITEMS/EN/212322.pdf?srsltid=AfmBOorrJOfXXYgsEqXDTk6Re-B-atFQrt4SZT5RJwRVI_3AazPJuJpw
- ScienceDirect broth dilution overview: https://www.sciencedirect.com/topics/immunology-and-microbiology/broth-dilution
- PMC QC study citing CLSI broth microdilution guidance: https://pmc.ncbi.nlm.nih.gov/articles/PMC8218745/
- NIH-hosted CLSI M100 PDF: https://www.nih.org.pk/wp-content/uploads/2021/02/CLSI-2020.pdf
- Clinical Laboratory Science review article: https://clsjournal.ascls.org/content/25/4/233.full-text.pdf
- Liofilchem Mueller Hinton II Broth IFU: https://www.liofilchem.net/login/pd/ifu/27510_IFU.pdf