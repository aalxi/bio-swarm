## Protocol summary
This protocol JSON describes a CLSI M07-based broth microdilution antimicrobial susceptibility testing workflow for aerobic bacteria. The goal is to determine the minimal inhibitory concentration (MIC) of an antimicrobial agent by preparing a two-fold serial dilution series in broth, inoculating each well with a standardized bacterial suspension, incubating, and then identifying the lowest concentration with no visible turbidity.

Based on the extracted JSON, the workflow includes: preparing antimicrobial stock solution at at least 1000 ug/mL or at least 10 times the highest test concentration; preparing successive two-fold intermediate dilutions; dispensing 100 uL antimicrobial-broth solution into a 96-well plate; preparing a bacterial inoculum from 3-5 isolated colonies in suitable broth; incubating the broth culture at 35 C until it reaches or exceeds 0.5 McFarland; adjusting the inoculum to 0.5 McFarland; inoculating wells with 10 uL inoculum so the inoculum volume does not exceed 10% of well volume and the final well concentration is approximately 5 x 10^5 CFU/mL; including growth, sterility, and quality-control wells; incubating the inoculated tray at 35 C for 16-20 hours in ambient air; and reading the MIC as the lowest concentration with no visible turbidity while checking QC acceptability.

The extracted protocol is explicitly described as guideline-like rather than a fully specified robotic method. Exact plate layout, antimicrobial identities, well assignments, and some timings are not provided, so automation is partial and several steps remain manual or underspecified.

## Generated Opentrons script
```python
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
```

## Simulation result
Pass

Coding state indicates `simulation_passed: true`, with `error_log: null` and `retry_count: 0`.

Notable messages from the provided script/context:
- The script explicitly skips loading `p300_multi_gen2` because OT-2 has only two mounts and the JSON also specified two single-channel pipettes.
- Multiple liquid-handling steps are intentionally skipped because source/destination locations and other key execution details were null or ambiguous in the extracted protocol.
- Incubation is represented as a manual/off-deck placeholder rather than a true onboard incubation action.

## Confidence notes from extraction
Null or missing fields in the protocol JSON:
- Step 1: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 2: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 3: `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 4: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 5: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`
- Step 6: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 7: `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 8: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`
- Step 9: `volume_ul`, `source_location`, `destination_location`, `speed_rpm`
- Step 10: `volume_ul`, `source_location`, `destination_location`, `duration_seconds`, `speed_rpm`, `temperature_celsius`

Extraction notes:
- The source material is a guideline/standard and overview, not a single fully specified Opentrons-ready protocol.
- Exact microdilution plate layout, well identities, concentration series, and antimicrobial identities are not provided in the extracted text, so source and destination well locations are set to null.
- Step 5 incubation duration for inoculum growth to 0.5 McFarland is not explicitly specified in seconds in the provided source, so duration_seconds is null.
- The CLSI text mentions CAMHB as the default reference broth microdilution medium, while the laboratory guide also mentions Mueller-Hinton broth generally; both are listed as reagents because the scraped sources reference both.
- The exact pipettes and labware are not specified in the source and were mapped to common Opentrons-compatible equivalents for a 96-well broth microdilution workflow; this mapping is approximate.
- Quality control strain identity is not specified in the extracted source passage, so it is listed generically.
- The reading/interpretation step is represented as a dispense action because the schema does not include a 'read' action.
- Incubation duration for the plate is given as 16-20 hours; 16 hours (57600 seconds) was used as the minimum explicit bound and the range is noted in notes.
- The source notes that final inoculum concentration should be approximately 5 x 10^5 CFU/mL in each well, but the exact dilution procedure varies by delivery method and must be calculated for each setup.

## Source citations
- CLSI M07 product page: https://clsi.org/shop/standards/m07/
- CLSI/EUCAST method modification document: https://clsi.org/media/i54hohjl/modification-of-antimicrobial-susceptibility-testing-methods.pdf
- CLSI M07-A8 PDF mirror: https://simpleshowoflove.weebly.com/uploads/1/4/0/7/14073276/agar_dilution_assay.pdf
- APEC laboratory guide: https://pdb.apec.org/Supporting%20Docs/3425/Completion%20Report/CTI%2024%2017A%20Anx%203%20Laboratory%20Guide.pdf
- Clinical Laboratory Science review: https://clsjournal.ascls.org/content/25/4/233.full-text.pdf
- Difco/BBL Mueller Hinton II Broth document: https://www.seco.us/ASSETS/DOCUMENTS/ITEMS/EN/212322.pdf?srsltid=AfmBOoqHxLhbPJ7dQtYHrxuU7KYILfo0RB1UH6lvoqAU-wO5lYAH7q8g
- Difco/BBL Mueller Hinton II Broth duplicate search hit: https://www.seco.us/ASSETS/DOCUMENTS/ITEMS/EN/212322.pdf?srsltid=AfmBOooweIHpv5ipdoWanW7oT-x-11LB0qMiue0hyhL1evMqTe3XV0zZ
- Biolife Mueller Hinton Broth instructions: https://gest.joyadv.it/public/cartellina-allegati-schede-certificazioni/schede-tecniche-inglese/ts-4017412.pdf
- Interlab/Difco Mueller Hinton II Broth manual: https://cdn.media.interlabdist.com.br/uploads/2021/01/Mueller-Hinton-II-Broth-Cation-Ajustado.pdf
- General CLSI M07 service page: https://www.testinglab.com/clsi-m07-dilution-methods-for-antimicrobial-susceptibility-testing
- FDA recognized consensus standard entry for CLSI M07: https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfstandards/detail.cfm?standard__identification_no=45893
- NIH Pakistan-hosted CLSI 2020 supplement used for extraction: https://www.nih.org.pk/wp-content/uploads/2021/02/CLSI-2020.pdf
- PMC article on microdilution MIC assay plate effects: https://pmc.ncbi.nlm.nih.gov/articles/PMC6325200/