# Demo source audit

Checked 2026-10-27 using official source text. No complete PDF is redistributed. The source
URLs remain remote references because direct downloads were unavailable in the build sandbox.
No original-file hash or independent human review is claimed.

## Infosys financial data

[Integrated Annual Report 2024–25](https://www.infosys.com/investors/reports-filings/annual-report/annual/documents/infosys-ar-25.pdf)

- PDF page 346 (one-based), printed page 374: note 2.27, consolidated function-wise profit
  and loss. FY25 and FY24 columns; INR crore; Ind AS. Distinguish total profit from the amount
  attributable to owners and from operating profit.
- PDF page 15 (one-based), printed spread 30–31: five-year financial highlights. FY23–FY25
  revenue and owners' profit. The footnote explicitly identifies IFRS consolidated figures.
- The report's exact publication date was not independently established. The financial
  statements' signature date and AGM notice date are not substituted for it.
- FY24 and FY23 entries in this report are comparative disclosures; the demo does not claim
  to have the corresponding original-year report figures.

## Infosys management commentary

[Q4 FY25 earnings call](https://www.infosys.com/investors/reports-filings/quarterly-results/2024-2025/q4/documents/transcripts/earningscall.pdf)

PDF/printed page 6: CFO Jayesh Sanghrajka discusses annual operating-margin drivers. The
stored narrative is a short reviewed paraphrase. It is restricted to the `operating_margin`
topic and FY25. The call date is known; the transcript's publication date remains unverified.

## RBI historical amendment example

[KYC Amendment Directions, 12 June 2025](https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12866)

Paragraph 3(ii) establishes immediate commencement. The imported summary covers that fact
only. `verified_through` is 2025-06-12 because subsequent amendments and the full master
direction have not been reconstructed. The HTML source has a clause locator and no invented
PDF page. It is not an answer to today's KYC obligations.

## Remaining review work

Archive permitted originals and verify hashes; visually audit table cells and page labels;
establish publication dates through official filing records; obtain independent human
verification; expand original-year reports and transcript coverage. Keep automatic extraction
quality separate from quality after review in the eventual evaluation report.

## Research expansion (2026-10-27)

The additive `research-expansion.json` bundle contains 19 further financial facts, two management
summaries and two SEBI clauses. It does not modify the original demo records. Reproducible data
authoring is in `scripts/build_research_bundle.py`; independent human audit remains pending.

| Official document | Checked locations | Included facts / interpretation |
|---|---|---|
| [Infosys FY24 consolidated statements](https://www.infosys.com/investors/reports-filings/annual-report/annual/documents/2023-24/consolidated.pdf) | PDF p.79 / printed365; PDF p.12 / printed298 | FY23 comparative revenue146767, operating profit30905, owners' profit24095, total profit24108; owners' equity75407 |
| [Infosys FY25 consolidated statements](https://www.infosys.com/investors/reports-filings/annual-report/annual/documents/2024-25/consolidated.pdf) | PDF p.12 / printed303 | Owners' equity95818 for FY25 and88116 for FY24 |
| [TCS FY24 consolidated statements](https://www.tcs.com/content/dam/tcs/investor-relations/financial-statements/2023-24/q4/IND%20AS/Consolidated.pdf) | PDF/printed pp.1–2 | FY23 comparative revenue225458, owners' profit42147, total profit42303, owners' equity90424 |
| [TCS FY25 consolidated statements](https://www.tcs.com/content/dam/tcs/investor-relations/financial-statements/2024-25/q4/IND%20AS/Consolidated.pdf) | PDF/printed pp.1–2 | FY25/FY24 revenue255324/240893, owners' profit48553/45908, total profit48797/46099, owners' equity94756/90489 |
| [TCS FY25 results release](https://www.tcs.com/who-we-are/newsroom/press-release/tcs-financial-results-q4-fy-2025) | CFO Samir Seksaria's statement | Paraphrased explanation of margin discipline and continuing investment; published2025-04-10; press release, not call transcript |
| [HCLTech FY25 results release](https://www.hcltech.com/en-us/press-releases/hcltech-delivers-another-year-industry-leading-growth) | CEO C Vijayakumar's statement | Paraphrased AI/go-to-market explanation of bookings; published2025-04-22; no financial table values imported |
| [SEBI circular2023/123](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2023/1689245602256.pdf) | PDF/printed p.1 paragraph5; p.18 AnnexureII paragraph1 | Commencement and material-event deadline framework; published2023-07-13; verified only for2023-07-15 |

All financial amounts above are consolidated Ind AS INR crore. PDF publication dates remain
unknown: signatures alone do not prove public availability. TCS's FY24 reported owners' profit
includes the legal-settlement impact; the adjusted number is deliberately not substituted.
Its segment "operating income" is not assumed to share Infosys's before-finance-cost definition.

Source acquisition manifests are provided for all included PDFs and the pending HCLTech FY24/FY25
results. Network acquisition in the local shell failed DNS resolution; HCLTech's financial links
also returned unsupported MIME types through browsing, and its annual reports exceeded the browser
PDF size limit. No placeholder financial figures, source hashes, or archive claims were inserted.
