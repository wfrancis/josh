"""Standard Interiors terms and conditions (5/16/2023).

One source for the proposal editor's default Terms list (proposal_bundler)
and the customer Estimate PDF (pdf_generator), so the editor shows what
prints. No third-party imports.
"""

SI_TERMS_TITLE = "Standard Interiors Terms and Conditions 5/16/2023"

SI_TERMS_PREAMBLE = (
    "Material pricing is very volatile at this time. Upon award Standard Interiors will "
    "provide dates that material pricing is secured until. Approval to order material must "
    "be provided from Contractor to avoid price impacts by those dates. If material is "
    "required to be purchased more than three months prior to installation Standard "
    "Interiors will require a change order to cover extended material storage costs."
)

# Plain text of each clause. Clause 7 carries extra markup (bold sentence and
# the T&M rate lines) that pdf_generator._si_terms_markup() adds.
SI_TERMS: list[str] = [
    "This proposal is valid for 30 days, should prices increase after this time period "
    "Standard Interiors (SI) reserves the right to re-negotiate pricing.",
    "Standard Interiors is not responsible for delays in shipping or discontinued products.",
    "Areas to receive flooring shall be clear of debris, materials and any contaminants which "
    "may inhibit the flooring installation. SI will remove leftover material and do a "
    "construction clean however are not responsible for vacuuming or final clean.",
    "Standard Interiors will exercise due caution and care around existing finishes however "
    "some dust, clean and touch up of paint, trim, etc. should be expected after completion "
    "of flooring/tile installation, and is not the responsibility of Standard Interiors.",
    "Standard Interiors excludes removal of any concrete curing compounds, sealing compounds, "
    "solvents, cleaners, or any materials that could affect the bonding of flooring/tile to "
    "the concrete. It is the GC/Owners responsibility to inform Standard Interiors of the use "
    "of these materials on concrete slabs.",
    "Prior to installation of flooring/tile, it is the responsibility of the GC/Owner to test "
    "the concrete for vapor emission and alkalinity per ASTM F2170 and/or F1869, to confirm "
    "it is within the manufacturer’s allowable tolerances. If the GC/Owner has not "
    "completed testing within two (2) weeks of installation Standard Interiors can test the "
    "areas to be installed at the GC/Owners expense or the warranty may be waived. If the "
    "results are outside of the manufacturers recommendations mitigation measures will be "
    "priced separately by SI. The GC/Owner may choose to waive the warranty",
    "Standard Interiors is assuming that substrates are within acceptable tolerances and "
    "typical floor prep is included.  Typical floor prep is defined as light skimcoating of "
    "hairline cracks or small (less than 2\" in diameter and 1/2\" in depth) recesses. "
    "Anything above is not typical & will incur additional floor prep costs which are to be "
    "performed on T&M basis. Floor prep can be expensive and very time consuming.",
    "Unless specifically called out, waterproofing at tile is excluded. TCNA detail B419-22 "
    "without a membrane has been priced and a suitable substrate per this detail is to be "
    "provided by others.",
    "Unless specifically called out, sound underlayment is excluded and by others if required.",
    "No sealers, primers, cleaners, chemicals, or additives are to be used on concrete that is "
    "to receive flooring without review and consent from Standard Interiors. These may cause "
    "a loss of bond to flooring, and will void warranty.",
    "All work is installed to industry standards as listed in the TCNA/CRI/RFCI/NWFA",
    "If Standard Interiors incurs any costs or expenses to enforce its rights under this "
    "agreement or to collect any amounts due, purchaser agrees to pay Standard Interiors for "
    "all such costs and expenses, including reasonable attorney’s fees and monthly "
    "interest of 1.5%.",
    "Code compliance with all Authorities Having Jurisdiction is the responsibility of the "
    "Architect and GC. Standard Interiors is not responsible for checking work of others on "
    "the plans or as constructed in the field for compliance with code requirements.",
    "Standard Interiors will assign a Superintendent to the project who will make daily "
    "visits to the project site, attend weekly subcontractor meetings and be available to "
    "make decisions daily. Full time on site supervision will be by the individual crew "
    "foremen.",
    "Standard Interiors has allocated manpower to this project based upon the schedule "
    "provided at time of contract. If project schedule delays manpower may be allocated to "
    "other projects resulting in Standard Interiors not being able to perform the work at "
    "the new schedule dates and/or requiring a change order for increased labor costs to "
    "staff the project.",
    "Standard Interiors reserves the right to stop work if payment is greater than thirty "
    "(30) days past due at any point during the project without any recourse from the "
    "GC/Owner and/or Purchaser for delay or similar damages.",
]


# The proposal editor's default Terms list: the preamble, then clauses 1-16.
DEFAULT_PROPOSAL_TERMS: list[str] = [SI_TERMS_PREAMBLE, *SI_TERMS]

# The tool's earlier default Terms list (preamble plus 16 clauses, some of
# them replaced in the 5/16/2023 set). A job whose saved Terms are exactly
# this list was never edited, so its PDF prints the 5/16/2023 terms.
LEGACY_PROPOSAL_TERMS: list[str] = [
    (
        "Material pricing is very volatile at this time. Upon award Standard "
        "Interiors will provide dates that material pricing is secured until. "
        "Approval to order material must be provided from Contractor to avoid "
        "price impacts by those dates. If material is required to be purchased "
        "more than three months prior to installation Standard Interiors will "
        "require a change order to cover extended material storage costs."
    ),
    (
        "This proposal is valid for 30 days, should prices increase after this "
        "time period Standard Interiors (SI) reserves the right to re-negotiate "
        "pricing."
    ),
    (
        "Standard Interiors is not responsible for delays in shipping or "
        "discontinued products."
    ),
    (
        "Areas to receive flooring shall be clear of debris, materials and any "
        "contaminants which may inhibit the flooring installation. SI will "
        "remove leftover material and do a construction clean however are not "
        "responsible for vacuuming or final clean."
    ),
    (
        "Standard Interiors will exercise due caution and care around existing "
        "finishes however some dust, clean and touch up of paint, trim, etc. "
        "should be expected after completion of flooring/tile installation, and "
        "is not the responsibility of Standard Interiors."
    ),
    (
        "Standard Interiors excludes removal of any concrete curing compounds, "
        "sealing compounds, solvents, cleaners, or any materials that could "
        "affect the bonding of flooring/tile to the concrete. It is the "
        "GC/Owners responsibility to inform Standard Interiors of the use of "
        "these materials on concrete slabs."
    ),
    (
        "Prior to installation of flooring/tile, it is the responsibility of "
        "the GC/Owner to test the concrete for vapor emission and alkalinity "
        "per ASTM F2170 and/or F1869, to confirm it is within the "
        "manufacturer's allowable tolerances. If the GC/Owner has not completed "
        "testing within two (2) weeks of installation Standard Interiors can "
        "test the areas to be installed at the GC/Owners expense or the "
        "warranty may be waived. If the results are outside of the "
        "manufacturers recommendations mitigation measures will be priced "
        "separately by SI. The GC/Owner may choose to waive the warranty"
    ),
    (
        "Standard Interiors is assuming that substrates are within acceptable "
        "tolerances and typical floor prep is included. Typical floor prep is "
        "defined as light skimcoating of hairline cracks or small (less than "
        '2" in diameter and 1/2" in depth) recesses. Anything above is not '
        "typical and will incur additional floor prep costs which are to be "
        "performed on T&M basis. Floor prep can be expensive and very time "
        "consuming."
    ),
    (
        "Standard Interiors will store excess material for 30 days from punch "
        "list completion. After that any excess material will be removed from "
        "the jobsite and disposed of. The GC/Owner needs to provide attic "
        "stock storage and submit quantities for each product."
    ),
    (
        "Standard Interiors is not responsible for the color variation of "
        "material. Color should be verified by the architect and/or owner's "
        "representative by samples and/or mockups prior to ordering material."
    ),
    (
        "Standard Interiors is not responsible for leveling of concrete "
        "substrate. Leveling will be performed on a T&M basis. Acceptable "
        'tolerances per ASTM are 3/16" in 10\' for commercial flooring and '
        '1/8" in 10\' for tile flooring.'
    ),
    (
        "If Standard Interiors incurs any costs or expenses to enforce its "
        "rights under this agreement or to collect any amounts due, purchaser "
        "agrees to pay Standard Interiors for all such costs and expenses, "
        "including reasonable attorney's fees and monthly interest of 1.5%."
    ),
    (
        "Code compliance with all Authorities Having Jurisdiction is the "
        "responsibility of the Architect and GC. Standard Interiors is not "
        "responsible for checking work of others on the plans or as "
        "constructed in the field for compliance with code requirements."
    ),
    (
        "Standard Interiors will assign a Superintendent to the project who "
        "will make daily visits to the project site, attend weekly "
        "subcontractor meetings and be available to make decisions daily. Full "
        "time on site supervision will be by the individual crew foremen."
    ),
    (
        "Standard Interiors has allocated manpower to this project based upon "
        "the schedule provided at time of contract. If project schedule delays "
        "manpower may be allocated to other projects resulting in Standard "
        "Interiors not being able to perform the work at the new schedule "
        "dates and/or requiring a change order for increased labor costs to "
        "staff the project."
    ),
    (
        "Standard Interiors reserves the right to stop work if payment is "
        "greater than thirty (30) days past due at any point during the "
        "project without any recourse from the GC/Owner and/or Purchaser for "
        "delay or similar damages."
    ),
    (
        "Price increases due to tariffs or trade disputes may result in "
        "additional costs."
    ),
]
