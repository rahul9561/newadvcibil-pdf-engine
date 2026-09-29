"""Static fallback lookup tables for coded fields in TransUnion CIBIL JSON.

PROVENANCE / CONFIDENCE NOTE - please read before trusting a label
--------------------------------------------------------------------------
Coded fields arrive in one of two shapes depending on which part of the
JSON they come from:

* The normalised ``TrueLinkCreditReport`` object represents most coded
  fields as ``{"rank": ..., "symbol": "05", "description": "", "abbreviation": ""}``.
  When ``description``/``abbreviation`` is populated by the bureau feed
  itself, the parser always prefers it (see ``utils.coded_label``) - that
  is the authoritative source and these tables are never consulted.
* The raw ``ICRS_SubjectInquiryByTUEF_Response`` subject object represents
  the same concepts as bare strings/ints (``"accountType": "05"``) with no
  description at all - these tables are the *only* source of a
  human-readable label for that shape.

In both the sample JSON supplied with this engine and the reference PDF,
``description``/``abbreviation`` were blank for every field, so every label
that actually appears in the reference PDF had to be sourced from a code
table, not read off the JSON.

Confidence per table, from highest to lowest:

* ``ACCOUNT_TYPE`` / ``ENQUIRY_PURPOSE`` - **high confidence.** This is the
  RBI "Uniform Credit Reporting Format" Account Type table, shared by
  CIBIL/Experian/Equifax/CRIF. Two entries were directly cross-checked
  against the reference PDF (Account Type ``01`` renders as
  "Auto Loan (Personal)" on reference page 13; ``15`` renders as
  "...Loan Against Bank Deposits (LABD)..." on reference pages 5-12) and
  matched exactly.
* ``OWNERSHIP_INDICATOR``, ``ASSET_CLASSIFICATION`` - **high confidence.**
  Same RBI format; ``ASSET_CLASSIFICATION``'s STD/SUB/DBT/LSS/SMA/XXX keys
  are printed verbatim as the payment-history legend on every account page
  of the reference PDF.
* ``PAYMENT_HISTORY_SENTINEL`` - **medium confidence.** The raw numeric
  ``account[].paymentHistory`` array (only present in the
  ICRS_SubjectInquiryByTUEF_Response shape) uses small integers 0-899 for a
  literal days-past-due count and reserves 900-905 for the non-numeric
  asset-classification codes above. This mapping is inferred from the
  *distribution* of values in the sample JSON (value ``901`` occurs 110
  times, exclusively on accounts with a positive, currently-serviced
  balance and a recent ``dateOfLastPayment`` - consistent with "Standard"),
  not from bureau documentation, because the reference PDF was rendered
  from a different consumer's data and does not let us cross-check it
  directly. Override via ``ParserOptions.payment_history_sentinel_map`` if
  your feed disagrees.
* ``ADDRESS_CATEGORY``, ``DWELLING`` - **low confidence / best effort.**
  Included so the engine renders *something* readable rather than a bare
  numeric code, but could not be cross-checked against the reference PDF
  (whose underlying JSON we do not have) or fully corroborated from the
  sample. Treat these as a reasonable default, not ground truth.
* Fields for which no usable table could be assembled at all (Telephone
  Type beyond 00/01, Occupation Code, Identifier Type beyond PAN) are
  intentionally NOT guessed - ``utils.coded_label`` falls back to showing
  the raw code (e.g. "Type 07") rather than inventing a label.
"""

from __future__ import annotations

# Appendix D - Account Type Table (RBI Uniform Credit Reporting Format).
# Also reused, per the same spec, as the Enquiry Purpose code table.
ACCOUNT_TYPE: dict[str, str] = {
    "00": "Other",
    "01": "Auto Loan (Personal)",
    "02": "Housing Loan",
    "03": "Property Loan",
    "04": "Loan Against Shares/Securities",
    "05": "Personal Loan",
    "06": "Consumer Loan",
    "07": "Gold Loan",
    "08": "Education Loan",
    "09": "Loan to Professional",
    "10": "Credit Card",
    "11": "Leasing",
    "12": "Overdraft",
    "13": "Two-Wheeler Loan",
    "14": "Non-Funded Credit Facility",
    "15": "Loan Against Bank Deposits",
    "16": "Fleet Card",
    "17": "Commercial Vehicle Loan",
    "18": "Telco - Wireless",
    "19": "Telco - Broadband",
    "20": "Telco - Landline",
    "21": "Seller Financing",
    "23": "GECL Loan Secured",
    "24": "GECL Loan Unsecured",
    "31": "Secured Credit Card",
    "32": "Used Car Loan",
    "33": "Construction Equipment Loan",
    "34": "Tractor Loan",
    "35": "Corporate Credit Card",
    "36": "Kisan Credit Card",
    "37": "Loan on Credit Card",
    "38": "Prime Minister Jan Dhan Yojana - Overdraft",
    "39": "Mudra Loans - Shishu/Kishor/Tarun",
    "40": "Microfinance - Business Loan",
    "41": "Microfinance - Personal Loan",
    "42": "Microfinance - Housing Loan",
    "43": "Microfinance - Others",
    "44": "Pradhan Mantri Awas Yojana - Credit Link Subsidy Scheme",
    "45": "P2P Personal Loan",
    "46": "P2P Auto Loan",
    "47": "P2P Education Loan",
    "50": "Business Loan - Secured",
    "51": "Business Loan - General",
    "52": "Business Loan - Priority Sector - Small Business",
    "53": "Business Loan - Priority Sector - Agriculture",
    "54": "Business Loan - Priority Sector - Others",
    "55": "Business Non-Funded Credit Facility - General",
    "56": "Business Non-Funded Credit Facility - Priority Sector - Small Business",
    "57": "Business Non-Funded Credit Facility - Priority Sector - Agriculture",
    "58": "Business Non-Funded Credit Facility - Priority Sector - Others",
    "59": "Business Loan Against Bank Deposits",
    "61": "Business Loan - Unsecured",
    "69": "Short Term Personal Loan",
    "70": "Priority Sector - Gold Loan",
    "71": "Temporary Overdraft",
}

ENQUIRY_PURPOSE = ACCOUNT_TYPE

# Ownership Indicator (Account Segment).
OWNERSHIP_INDICATOR: dict[str, str] = {
    "1": "Individual",
    "2": "Authorised User",
    "3": "Guarantor",
    "4": "Joint",
    "5": "Deceased",
}

# Credit Facility / Written-off status.
CREDIT_FACILITY_STATUS: dict[str, str] = {
    "00": "Restructured Loan",
    "01": "Restructured Loan (Govt. Mandated)",
    "02": "Written-off",
    "03": "Settled",
    "04": "Post (WO) Settled",
    "05": "Account Sold",
    "06": "Written Off and Account Sold",
    "07": "Account Purchased",
    "08": "Account Purchased and Written Off",
    "09": "Account Purchased and Settled",
    "10": "Account Purchased and Restructured",
    "11": "Restructured due to Natural Calamity",
    "12": "Restructured due to COVID-19",
    "13": "Post Write Off Closed",
    "14": "Restructured & Closed",
    "15": "Auctioned & Settled",
    "16": "Repossessed & Settled",
    "17": "Guarantee Invoked",
    "99": "Clear Existing Status",
}

# Asset-classification text codes that can appear in place of a numeric
# days-past-due value in the payment history. Printed verbatim as the
# legend under every account's payment-history table.
ASSET_CLASSIFICATION: dict[str, str] = {
    "STD": "Standard",
    "SUB": "Substandard",
    "DBT": "Doubtful",
    "LSS": "Loss",
    "SMA": "Special Mention Account",
    "XXX": "Not Reported",
}

# Sentinel values >=900 seen in the raw numeric paymentHistory array,
# mapped to the ASSET_CLASSIFICATION code they stand in for. See the
# module docstring - medium confidence, overridable.
PAYMENT_HISTORY_SENTINEL: dict[int, str] = {
    900: "XXX",
    901: "STD",
    902: "SUB",
    903: "LSS",
    904: "DBT",
    905: "SMA",
}

# Payment frequency (Account Segment).
PAYMENT_FREQUENCY: dict[str, str] = {
    "01": "Weekly",
    "02": "Fortnightly",
    "03": "Monthly",
    "04": "Bi-Monthly",
    "05": "Quarterly",
    "06": "Half Yearly",
    "07": "Yearly",
    "08": "On Maturity",
    "12": "Daily",
}

# Identification/Identifier Type (raw ICRS subject.id[].idType shape).
# "01"->PAN is cross-checked against the reference PDF directly
# ("Income Tax ID Number (PAN)"). "04"/"05"/"09" are cross-checked *within
# the sample JSON itself*: the same person's identifiers appear twice -
# once here as bare idType codes, and once in the normalised
# TrueLinkCreditReport as named identifiers (IdentifierName "TaxId" /
# "DriversLicenseId" / "RationCardId" / "CkycId") carrying the exact same
# ID numbers - so "04"==DriversLicenseId, "05"==RationCardId and
# "09"==CkycId are high confidence. "02"/"03"/"06"/"07"/"08" were never
# observed and follow the general RBI table as an unverified best effort.
ID_TYPE: dict[str, str] = {
    "01": "Income Tax ID Number (PAN)",
    "02": "Passport Number",
    "03": "Voter's ID Number",
    "04": "Driving Licence Number",
    "05": "Ration Card Number",
    "06": "Universal ID Number (Aadhaar)",
    "07": "Company ID Number",
    "08": "Employee ID Number",
    "09": "CKYC",
}

# Identifier Type as named in the normalised TrueLinkCreditReport shape
# (Borrower.IdentifierPartition.Identifier[].ID.IdentifierName). "SocialId"
# is the bureau's internal correlation key (== ReferenceKey/borrowerKey),
# not a real personal-document identifier, and is deliberately excluded
# from rendering by the parser rather than mapped here - the reference
# PDF's Identification Details section only ever lists genuine document
# IDs (PAN, CKYC, ...), never an internal reference number.
IDENTIFIER_NAME_LABEL: dict[str, str] = {
    "TaxId": "Income Tax ID Number (PAN)",
    "CkycId": "CKYC",
    "DriversLicenseId": "Driving Licence Number",
    "RationCardId": "Ration Card Number",
    "PassportId": "Passport Number",
    "VoterIdCard": "Voter's ID Number",
    "VoterId": "Voter's ID Number",
    "UniversalId": "Universal ID Number (Aadhaar)",
    "UId": "Universal ID Number (Aadhaar)",
    "AadhaarId": "Universal ID Number (Aadhaar)",
}

# Identifier names that are internal bureau bookkeeping, not a consumer-
# facing document ID, and should be skipped when rendering Identification
# Details (the reference PDF never lists these).
IDENTIFIER_NAME_SKIP = {"SocialId"}

# Telephone Type. "00" -> Mobile and "01" -> Office are cross-checked
# against the reference PDF's Contact Details section; other values were
# never observed and are not guessed.
TELEPHONE_TYPE: dict[str, str] = {
    "00": "Mobile Phone",
    "01": "Office Phone",
    "02": "Residence Phone",
    "03": "Fax",
}

# Address Category. LOW CONFIDENCE - see module docstring. "01" matching
# "Residence Address" is the best-supported entry (majority code in the
# sample, majority label in the reference PDF); others are a best effort.
ADDRESS_CATEGORY: dict[str, str] = {
    "01": "Residence Address",
    "02": "Permanent Address",
    "03": "Office Address",
    "04": "Previous Residence Address",
}

# Dwelling / Residence status ("Residence Code" column in the reference
# PDF, values like "Owned"). LOW CONFIDENCE - see module docstring.
DWELLING: dict[str, str] = {
    "01": "Owned",
    "02": "Rented",
    "03": "Parental / Family",
    "04": "Company Provided",
}

# Gender code (raw subject.name.gender). Cross-checked directly against
# this sample: the same person appears as both the raw code "2" and, in
# the same JSON's normalised TrueLinkCreditReport.Borrower.Gender, the
# literal string "Male" - so "2" == Male is high confidence. "1"/"3" follow
# the same table's usual ordering but are not independently confirmed.
GENDER: dict[str, str] = {
    "1": "Female",
    "2": "Male",
    "3": "Transgender",
    "male": "Male",
    "female": "Female",
}


# --------------------------------------------------------------------------
# B2C-REPORT shape
# --------------------------------------------------------------------------
# In the B2C-REPORT shape personal/KYC data is only available as
# ``STANDARD-DATA.DEMOGS.VARIATIONS[]`` groups, each tagged with a ``TYPE``.
# The identifier-bearing groups map onto the same labels the reference PDF
# prints for document IDs. The non-identifier groups (NAME/DOB/PHONE/EMAIL/
# ADDRESS-VARIATIONS) are consumed by the parser directly, not via this
# table. An identifier group missing from this table is still rendered,
# labelled from its own TYPE (see ``parser_b2c._variation_type_label``).
B2C_ID_VARIATION_LABEL: dict[str, str] = {
    "PAN-VARIATIONS": ID_TYPE["01"],
    "PASSPORT-VARIATIONS": ID_TYPE["02"],
    "VOTER-ID-VARIATIONS": ID_TYPE["03"],
    "VOTERID-VARIATIONS": ID_TYPE["03"],
    "DRIVING-LICENSE-VARIATIONS": ID_TYPE["04"],
    "DRIVING-LICENCE-VARIATIONS": ID_TYPE["04"],
    "RATION-CARD-VARIATIONS": ID_TYPE["05"],
    "UID-VARIATIONS": ID_TYPE["06"],
    "AADHAAR-VARIATIONS": ID_TYPE["06"],
    "CKYC-VARIATIONS": ID_TYPE["09"],
}

B2C_NON_ID_VARIATIONS = {
    "NAME-VARIATIONS",
    "DOB-VARIATIONS",
    "PHONE-VARIATIONS",
    "EMAIL-VARIATIONS",
    "ADDRESS-VARIATIONS",
}

# Asset-classification codes whose presence alongside a numeric DPD value
# carries information of its own (the account is classified as stressed
# even if the DPD count alone would not show it), so the payment-history
# cell keeps both parts ("0/SUB") instead of just the DPD count.
ADVERSE_ASSET_CLASSIFICATION = {"SUB", "DBT", "LSS", "SMA", "SMA-0", "SMA-1", "SMA-2"}
