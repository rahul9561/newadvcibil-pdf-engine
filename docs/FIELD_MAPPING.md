# JSON → PDF Field Mapping

## B2C-REPORT format (current - `input/sample.json`)

Parsed by `newadv_cibil_pdf_engine/parser_b2c.py`. Paths are relative to
the `B2C-REPORT` object; `STD` = `REPORT-DATA.STANDARD-DATA`,
`T` = one `STD.TRADELINES[]` entry. Every field is optional: blank, `null`
or missing renders `-` (or an empty-state message for whole sections).

| PDF section | PDF label | JSON source |
|---|---|---|
| Title | Control Number | `HEADER-SEGMENT.REPORT-ID` |
| Title | Date | `HEADER-SEGMENT.DATE-OF-ISSUE` (fallback `DATE-OF-REQUEST`) |
| Score | value / factors | `STD.SCORE[0].VALUE` / `.FACTORS[].DESC`; date = report date |
| Personal | Name | latest `NAME-VARIATIONS` value; fallback `REQUEST-DATA.APPLICANT-SEGMENT` FIRST/MIDDLE/LAST-NAME |
| Personal | Date Of Birth | latest `DOB-VARIATIONS` value; fallback `APPLICANT-SEGMENT.DOB` |
| Personal | Gender | `APPLICANT-SEGMENT.GENDER` |
| Identification | type / number | every identifier `*-VARIATIONS` group (`PAN-` → "Income Tax ID Number (PAN)", see `codes.B2C_ID_VARIATION_LABEL`) |
| Address | Address / Date Reported | `ADDRESS-VARIATIONS[].VALUE` / `.REPORTED-DT`, newest first |
| Contact | Telephone Number | `PHONE-VARIATIONS[].VALUE`; fallback `APPLICANT-SEGMENT.PHONES` |
| Email | Email ID | `EMAIL-VARIATIONS[].VALUE` |
| Employment | Account Type / Date Reported / Occupation | latest `STD.EMPLOYMENT-DETAILS[].EMPLOYMENT-DETAIL` `ACCT-TYPE` / `LAST-REPORTED-DT` / `OCCUPATION` |
| Account summary | Member Name / Account Type / Account Number / Ownership | `T.CREDIT-GRANTOR` / `ACCT-TYPE` / `ACCT-NUMBER` / `OWNERSHIP-TYPE` |
| Account | open vs closed | closed if `T.CLOSED-DT` set or `ACCOUNT-STATUS` = Closed |
| Account Details | Credit Limit / Cash Limit | `T.CREDIT-LIMIT` / `T.CASH-LIMIT` |
| Account Details | Sanctioned Amount | `T.DISBURSED-AMT` |
| Account Details | Current Balance / Amount Overdue | `T.CURRENT-BAL` / `T.OVERDUE-AMT` |
| Account Details | Rate of Interest / Repayment Tenure | `T.INTEREST-RATE` / `T.REPAYMENT-TENURE` |
| Account Details | EMI Amount / Payment Frequency | `T.INSTALLMENT-AMT` (`"194/Monthly"`) / `T.INSTALLMENT-FREQUENCY` |
| Account Details | Actual Payment Amount | `T.ACTUAL-PAYMENT` |
| Account Details | Date Opened / Closed / Last Payment / Reported | `T.DISBURSED-DT` / `CLOSED-DT` / `LAST-PAYMENT-DT` / `REPORTED-DT` |
| Account Details | Value of Collateral | sum of `T.SECURITY-DETAILS[].SECURITY-VALUATION` |
| Account Details | Credit Facility Status | `T.WRITTEN-OFF-SETTLED-STATUS` |
| Account Details | Written-off (Total / Principal) / Settlement | `T.WRITE-OFF-AMT` / `PRINCIPAL-WRITE-OFF-AMT` / `SETTLEMENT-AMT` |
| Account Details (extra rows, only if reported) | Account Status, Security Status, Suit Filed / Wilful Default, Account Remarks, Account in Dispute, Security Type, Suit Filed Date, Date Written-off, Last Paid Amount | `ACCOUNT-STATUS`, `SECURITY-STATUS`, `SUIT-FILED-WILFUL-DEFAULT-STATUS`, `ACCOUNT-REMARKS`, `ACCT-IN-DISPUTE`, `SECURITY-DETAILS[].SECURITY-TYPE`, `SUIT-FILED-DT`, `WRITE-OFF-DT`, `LAST-PAID-AMOUNT` |
| Payment Status | Start / End Date | first / last month of the payment history (`01/MM/YYYY`) |
| Payment History | grid | `T.HISTORY[NAME=COMBINED-PAYMENT-HISTORY]` `DATES` x `VALUES`, via `utils.format_payment_status` |
| Enquiry | Member Name / Date / Purpose / Amount | `STD.INQUIRY-HISTORY[]` `LENDER-NAME` / `INQUIRY-DT` / `CREDIT-INQ-PURPS-TYPE` (fallback `LOAN-TYPE`, then "Other") / `AMOUNT` |

Not rendered (no place in the reference layout): `REPORT-DATA.ACCOUNTS-SUMMARY`,
`TRENDS` (score history), the other `HISTORY` series (high credit, balance,
amount paid), `ALERTS`.

---

## Legacy TrueLink / raw-subject formats

Every row below traces to an actual line in `newadv_cibil_pdf_engine/parser.py` -
none of these JSON paths are invented. Two JSON shapes are supported (see
`parser.py`'s module docstring and `README.md` §1); most fields exist in
both, with the same normalized field feeding the same PDF label either
way. Paths are relative to the object `locate_report_root()` finds
(`TrueLinkCreditReport` for the "tlcr" shape, the `subject` object for the
"raw_subject" shape) - not to the whole input document, since that root
can be nested arbitrarily deep inside an API envelope.

Legend: **Req** = Required (report fails to parse a *usable* document
without it - currently only the consumer/borrower record itself, raised
as `MissingRequiredField`). Everything else is **Optional** - absent in
the JSON, it renders as `-` or an empty-state message, never raises.

## Header / running footer

| JSON Path (tlcr) | JSON Path (raw_subject) | Normalized Field | PDF Section | PDF Label | Req/Opt |
|---|---|---|---|---|---|
| `ReferenceKey` | `ecn` (response wrapper) | `ReportMeta.control_number` | Header | Control Number | Optional |
| `Borrower.CreditScore.Source.InquiryDate` (falls back to `Borrower.Birth.Source.InquiryDate`) | `timestamp` (response wrapper) | `ReportMeta.report_date` | Header | Date | Optional |
| *(generated at render time, not sourced from JSON)* | *(same)* | `ReportMeta.generated_at` | Running header/footer | top-left timestamp | n/a |

## Score

| JSON Path (tlcr) | JSON Path (raw_subject) | Normalized Field | PDF Section | PDF Label | Req/Opt |
|---|---|---|---|---|---|
| `Borrower.CreditScore.riskScore` | `scores[0].score` | `Score.value` | CIBIL Score & Report | the big score number + gauge needle | Optional (section omitted if absent) |
| `Borrower.CreditScore.scoreName` | `scores[0].scoreName` | `Score.name` | *(not printed - reserved field)* | - | Optional |
| `Borrower.CreditScore.Source.InquiryDate` | `scores[0].scoreDate` (DDMMYYYY, normalised) | `Score.date` | CIBIL Score & Report | "as of Date : ..." | Optional |
| *(constant: `GenerateOptions.score_range`, default 300-900)* | *(same)* | `Score.range_min` / `Score.range_max` | CIBIL Score & Report | gauge end labels ("300"/"900") | n/a (fixed scale property, not customer data) |
| `Borrower.CreditScore.CreditScoreFactor[].FactorText[]` | *(not parsed on this path)* | `Score.factors` | *(parsed but not rendered - reference PDF doesn't show per-factor text)* | - | Optional |

## Personal Details

| JSON Path (tlcr) | JSON Path (raw_subject) | Normalized Field | PDF Section | PDF Label | Req/Opt |
|---|---|---|---|---|---|
| `Borrower.BorrowerName.Name.Forename` | `subject.name.name1` | `Consumer.name` | Personal Details | Name | **Required** |
| `Borrower.Birth.date` | `subject.name.dob` | `Consumer.date_of_birth` | Personal Details | Date Of Birth | Optional |
| `Borrower.Gender` (literal string) | `subject.name.gender` (coded via `codes.GENDER`) | `Consumer.gender` | Personal Details | Gender | Optional |

## Identification Details

| JSON Path (tlcr) | JSON Path (raw_subject) | Normalized Field | PDF Section | PDF Label | Req/Opt |
|---|---|---|---|---|---|
| `Borrower.IdentifierPartition.Identifier[].ID.IdentifierName` (via `codes.IDENTIFIER_NAME_LABEL`; `"SocialId"` entries skipped) | `subject.id[].idType` (via `codes.ID_TYPE`) | `Identification.id_type_label` | Identification Details | Identification Type | Optional |
| `Borrower.IdentifierPartition.Identifier[].ID.Id` | `subject.id[].idNumber` | `Identification.id_number` | Identification Details | ID Number | Optional |
| `Borrower.IdentifierPartition.Identifier[].dateIssued` (field inspected; not present in the sample) | *(no equivalent field found)* | `Identification.issue_date` | Identification Details | Issue Date | Optional - **not sourceable from either sample shape**, always `-` |
| `Borrower.IdentifierPartition.Identifier[].dateExpired` (field inspected; not present in the sample) | *(no equivalent field found)* | `Identification.expiry_date` | Identification Details | Expiry Date | Optional - **not sourceable from either sample shape**, always `-` |

## Address Details

| JSON Path (tlcr) | JSON Path (raw_subject) | Normalized Field | PDF Section | PDF Label | Req/Opt |
|---|---|---|---|---|---|
| `Borrower.BorrowerAddress[].CreditAddress.{StreetAddress,City,Region,PostalCode}` (joined) | `subject.address[].{line1..line5,pinCode}` (joined) | `Address.lines` | Address Details | Address | Optional |
| `Borrower.BorrowerAddress[].CreditAddress.AddressType` (always blank in the sample - see "Known gaps" below) | `subject.address[].addressCategory` (via `codes.ADDRESS_CATEGORY`) | `Address.category_label` | Address Details | Category | Optional - low-confidence table, see `data/codes.py` |
| `Borrower.BorrowerAddress[].Dwelling` (via `codes.DWELLING`) | `subject.address[].residenceCode` (via `codes.DWELLING`) | `Address.residence_code_label` | Address Details | Residence Code | Optional - low-confidence table |
| `Borrower.BorrowerAddress[].dateReported` | `subject.address[].reportedDate` | `Address.date_reported` | Address Details | Date Reported | Optional |

## Contact / Email Details

| JSON Path (tlcr) | JSON Path (raw_subject) | Normalized Field | PDF Section | PDF Label | Req/Opt |
|---|---|---|---|---|---|
| `Borrower.BorrowerTelephone[].PhoneType` (via `codes.TELEPHONE_TYPE`) | `subject.telephone[].telephoneType` (via `codes.TELEPHONE_TYPE`) | `Phone.type_label` | Contact Details | Telephone Number Type | Optional |
| `Borrower.BorrowerTelephone[].PhoneNumber.Number` | `subject.telephone[].telephoneNumber` | `Phone.number` | Contact Details | Telephone Number | Optional |
| `Borrower.BorrowerTelephone[].extension` (field inspected; not present in the sample) | *(no equivalent field found)* | `Phone.extension` | Contact Details | Telephone Extension | Optional - always `-` in the sample |
| `Borrower.BorrowerEmail` / `Borrower.EmailAddress` (neither present in the sample) | `subject.email[]` (empty in the sample) | `Email.address` | Email Details | Email ID | Optional - section renders its empty state for this sample (no email data in either shape) |

## Employment Details

| JSON Path (tlcr) | JSON Path (raw_subject) | Normalized Field | PDF Section | PDF Label | Req/Opt |
|---|---|---|---|---|---|
| `Borrower.Employer.account` (via `codes.ACCOUNT_TYPE`) | `subject.employment.accountType` (via `codes.ACCOUNT_TYPE`) | `Employment.account_type_label` | Employment Details | Account Type | Optional |
| `Borrower.Employer.dateReported` | `subject.employment.reportedDate` | `Employment.date_reported` | Employment Details | Date Reported | Optional |
| `Borrower.Employer.name` (blank in the sample) | *(no occupation-category field found)* | `Employment.occupation` | Employment Details | Occupation | Optional - **not sourceable from either sample shape**, always `-` |
| *(no income-amount field found in either shape)* | *(same)* | `Employment.income` | Employment Details | Income | Optional - **not sourceable from either sample shape**, always `-` |
| `Borrower.Employer.IncomeFreqIndicator` (blank in the sample) | *(field not parsed on this path)* | `Employment.monthly_annual_income_indicator` | Employment Details | Monthly / Annual Income Indicator | Optional |
| `Borrower.Employer.NetGrossIndicator` (blank in the sample) | *(field not parsed on this path)* | `Employment.net_gross_income_indicator` | Employment Details | Net / Gross Income Indicator | Optional |

## Accounts (per entry, repeated for every account)

| JSON Path (tlcr) | JSON Path (raw_subject) | Normalized Field | PDF Section | PDF Label | Req/Opt |
|---|---|---|---|---|---|
| `TradeLinePartition[].Tradeline.creditorName` | `subject.account[].memberShortName` | `Account.member_name` | All Accounts (summary row) | Member Name | Optional |
| `...Tradeline.GrantedTrade.AccountType` (via `codes.ACCOUNT_TYPE`) | `subject.account[].accountType` (via `codes.ACCOUNT_TYPE`) | `Account.account_type_label` | All Accounts (summary row) | Account Type | Optional |
| `...Tradeline.accountNumber` | `subject.account[].accountNumber` | `Account.account_number` | All Accounts (summary row) | Account Number | Optional; masked when `mask_account_numbers=True` |
| `...Tradeline.AccountDesignator` (via `codes.OWNERSHIP_INDICATOR`) | `subject.account[].ownershipIndicator` (via `codes.OWNERSHIP_INDICATOR`) | `Account.ownership_label` | All Accounts (summary row) | Ownership | Optional |
| `...Tradeline.dateClosed` present/absent | `subject.account[].dateClosed` present/absent | `Account.is_open` | Open Accounts / Closed Accounts grouping | *(section grouping, not a printed field)* | Optional |
| `...GrantedTrade.CreditLimit` | `subject.account[].creditLimit` | `Account.credit_limit` | Account Details | Credit Limit | Optional |
| `...Tradeline.highBalance` | `subject.account[].highCreditAmount` | `Account.sanctioned_amount` | Account Details | Sanctioned Amount | Optional |
| `...Tradeline.currentBalance` | `subject.account[].currentBalance` | `Account.current_balance` | Account Details | Current Balance | Optional |
| `...GrantedTrade.CashLimit` | `subject.account[].cashLimit` | `Account.cash_limit` | Account Details | Cash Limit | Optional |
| `...GrantedTrade.amountPastDue` | `subject.account[].amountOverdue` | `Account.amount_overdue` | Account Details | Amount Overdue | Optional |
| `...GrantedTrade.interestRate` | `subject.account[].rateOfInterest` | `Account.rate_of_interest` | Account Details | Rate of Interest | Optional |
| `...GrantedTrade.termMonths` | `subject.account[].repaymentTenure` | `Account.repayment_tenure` | Account Details | Repayment Tenure | Optional |
| `...GrantedTrade.EMIAmount` | `subject.account[].EMIAmount` | `Account.emi_amount` | Account Details | EMI Amount | Optional |
| `...GrantedTrade.PaymentFrequency` (via `codes.PAYMENT_FREQUENCY`) | `subject.account[].paymentFrequency` (via `codes.PAYMENT_FREQUENCY`) | `Account.payment_frequency` | Account Details | Payment Frequency | Optional |
| `...GrantedTrade.actualPaymentAmount` | `subject.account[].actualPaymentAmount` | `Account.actual_payment_amount` | Account Details | Actual Payment Amount | Optional |
| `...Tradeline.dateOpened` | `subject.account[].dateOpened` | `Account.date_opened` | Account Details | Date Opened / Disbursed | Optional |
| `...Tradeline.dateClosed` | `subject.account[].dateClosed` | `Account.date_closed` | Account Details | Date Closed | Optional |
| *(not present on this shape - see README §1; opportunistically enriched from the embedded raw shape, matched by account number, when both are present in the same document)* | `subject.account[].dateOfLastPayment` | `Account.date_of_last_payment` | Account Details | Date of Last Payment | Optional - `-` on tlcr-only input |
| `...Tradeline.dateReported` | `subject.account[].reportedDate` | `Account.date_reported` | Account Details | Date Reported And Certified | Optional |
| `...GrantedTrade.collateral` | `subject.account[].valueOfCollateral` | `Account.value_of_collateral` | Account Details | Value of Collateral | Optional |
| `...Tradeline.AccountCondition` (via `codes.CREDIT_FACILITY_STATUS`) | `subject.account[].creditFacilityStatus` (via `codes.CREDIT_FACILITY_STATUS`) | `Account.credit_facility_status` | Account Details | Credit Facility Status | Optional |
| `...Tradeline.writtenOffAmtTotal` | `subject.account[].writtenOffAmtTotal` | `Account.written_off_total` | Account Details | Written-off Amount (Total) | Optional |
| `...Tradeline.writtenOffPrincipal` | `subject.account[].writtenOffAmtPrincipal` | `Account.written_off_principal` | Account Details | Written-off Amount (Principal) | Optional |
| `...Tradeline.settlementAmount` | `subject.account[].settlementAmount` | `Account.settlement_amount` | Account Details | Settlement Amount | Optional |
| `...GrantedTrade.PayStatusHistory.startDate` | `subject.account[].paymentHistStartDate` | `Account.payment_start_date` | Payment Status | Payment Start Date | Optional |
| `...GrantedTrade.PayStatusHistory.endDate` | `subject.account[].paymentHistEndDate` | `Account.payment_end_date` | Payment Status | Payment End Date | Optional |
| `...GrantedTrade.PayStatusHistory.MonthlyPayStatus[].{date,status}` (literal STD/SUB/...) | `subject.account[].paymentHistory[]` (numeric; decoded via `codes.PAYMENT_HISTORY_SENTINEL`, see README §1 confidence note) | `Account.payment_history` | Payment History | the calendar grid | Optional - section omitted if no history |

## Enquiries (per entry, repeated for every enquiry)

| JSON Path (tlcr) | JSON Path (raw_subject) | Normalized Field | PDF Section | PDF Label | Req/Opt |
|---|---|---|---|---|---|
| `InquiryPartition[].Inquiry.subscriberName` | `subject.inquiry[].memberShortName` | `Enquiry.member_name` | Enquiry Details | Member Name | Optional |
| `InquiryPartition[].Inquiry.inquiryDate` | `subject.inquiry[].dateOfInquiry` | `Enquiry.date_of_enquiry` | Enquiry Details | Date Of Enquiry | Optional |
| `InquiryPartition[].Inquiry.inquiryType` (via `codes.ENQUIRY_PURPOSE`) | `subject.inquiry[].inquiryPurpose` (via `codes.ENQUIRY_PURPOSE`) | `Enquiry.purpose_label` | Enquiry Details | Enquiry Purpose | Optional |
| `InquiryPartition[].Inquiry.amount` | `subject.inquiry[].inquiryAmount` | `Enquiry.amount` | Enquiry Details | Enquiry Amount | Optional |

## Visible in the reference PDF but not found in either JSON shape

These fields render as `-` (or their section's empty state) not because
of a parser bug, but because no corresponding field exists anywhere in
`input/sample.json`, in either the normalised or raw shape. Confirmed by
grepping the full decoded JSON (see `analysis/decoded_original.json` from
the original reverse-engineering pass) - not asserted from memory:

* **Identification Details → Issue Date / Expiry Date** - the reference
  shows `-` for these too on the one sample checked, consistent with the
  field being absent upstream, not a bureau-side blank.
* **Employment Details → Occupation** - the reference PDF shows a real
  value ("Self Employed Professional"); no occupation-category field
  exists in `input/sample.json` to source that from.
* **Employment Details → Income** - no income-amount field exists in
  either JSON shape.
* **Contact Details → Telephone Extension** - no extension field exists
  in either JSON shape; both consistently show `-`.

## Summary/statistics

The reference PDF has **no distinct Summary/Statistics page or section** -
open/closed account counts and totals are only ever implicit in the "All
Accounts" listing itself. `renderers/summary.py::summary_context()` computes
these aggregates (`total_accounts`, `open_accounts`, `closed_accounts`,
`total_current_balance`, `total_enquiries`) from the same `NormalizedReport`
every other renderer uses, entirely from real parsed fields - but it is not
wired into any template, since there is no reference section to reproduce.
See its module docstring for how to use it if you add one.
