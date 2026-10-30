# Layout benchmark

Measures how many key figures automatic extraction gets right across differently laid-out
annual reports, so layout changes are judged by numbers rather than by fixing one company at a
time.

- **Reports:** FY2025 annual reports of 11 listed non-financial companies across IT, autos,
  pharma, steel, metals, cement, consumer, and telecom
  ([`benchmarks/layout-reports.json`](../benchmarks/layout-reports.json)). Banks and insurers are
  excluded; their statements need a different set of line items.
- **Gold labels:** 84 consolidated Ind AS figures (revenue, total income, profit before tax,
  total profit, profit attributable to owners, basic EPS, total assets, owners' equity) in
  [`benchmarks/layout-gold.json`](../benchmarks/layout-gold.json). They were read from each
  report's raw page text, independently of the extractor's parsing and row mapping, by the
  coding assistant. **They still need a human spot-check** (list below). Metrics with no single
  printed line are null and not scored.
- **Scoring:** each report goes through `automap` and the validation gates (without the LLM
  resolver, so layout reading is measured alone). Only figures the gates accept count. A
  *wrong* accepted figure is the critical failure; *blocked* means the gates stopped it.

```sh
# PDFs are archived under data/benchmark/sources (see layout-reports.json for the URLs).
.venv/bin/regulation-analyst benchmark-layout --layout rules
.venv/bin/regulation-analyst benchmark-layout --layout llm     # needs a configured model (OpenAI or Bedrock)
.venv/bin/regulation-analyst benchmark-layout --layout auto
```

Results are written to `artifacts/layout-benchmark/results-<layout>.{json,md}`.

## Baseline: label rules (30 October 2026)

| | |
|---|---|
| Correct | **63 / 84 (75%)** |
| Wrong and accepted | **1** |
| Blocked by gates | 0 |
| Not extracted | 20 |
| Time | 113 s for 11 reports; no model tokens |

| Company | Correct | Wrong | Missing | What went wrong |
|---|---:|---:|---:|---|
| Infosys | 8 | 0 | 0 | |
| Wipro | 8 | 0 | 0 | |
| Sun Pharma | 7 | **1** | 0 | Total profit taken from "profit for the year *before share of associates*" (109,801.0) instead of 109,647.5. PBT − tax equals that line too, so the gates cannot catch it. |
| Titan | 7 | 0 | 1 | |
| Tata Motors | 6 | 0 | 1 | |
| Tata Steel | 6 | 0 | 2 | |
| UltraTech | 6 | 0 | 1 | |
| Cipla | 6 | 0 | 2 | "Net profit for the year" not recognised |
| HCLTech | 5 | 0 | 3 | Owners' profit and EPS sit on the continuation page |
| Bharti Airtel | 2 | 0 | 5 | Balance sheet and P&L printed side by side on one page |
| Hindalco | 2 | 0 | 5 | Same side-by-side layout |

These failures are what the model-led layout (`--layout llm`) is meant to fix without per-company
rules. Its results will be added here once run with a configured model.

**Keep the benchmark honest:** do not tune label rules to these specific reports. Add new
companies to measure generalisation instead; fixes judged only on the benchmark they were tuned
on overstate accuracy.

## Spot-check list

Please confirm these against the PDFs (page numbers are PDF pages). They are the values most
likely to be misread, either because the report has several similar lines or an unusual layout.

| Company | Figure | Gold value | Unit | PDF page |
|---|---|---|---|---:|
| Sun Pharma | Total profit (before non-controlling interests) | 109,647.5 | ₹ million | 226 |
| Sun Pharma | Profit attributable to owners | 109,290.4 | ₹ million | 226 |
| Tata Motors | Basic EPS, continuing and discontinued | 78.80 | ₹ | 314 |
| Tata Motors | Profit for the year (XV) | 28,149 | ₹ crore | 313 |
| Tata Steel | Profit attributable to owners | 3,420.51 | ₹ crore | 407 |
| HCLTech | Profit attributable to owners | 17,390 | ₹ crore | 338 |
| Cipla | Net profit for the year | 5,269.20 | ₹ crore | 331 |
| Cipla | Profit before tax and share of associates | 6,820.81 | ₹ crore | 331 |
| UltraTech | Profit before tax | 7,528.13 | ₹ crore | 417 |
| Bharti Airtel | Profit attributable to owners of the parent | 335,561 | ₹ million | 199 |
| Hindalco | Profit before tax | 22,337 | ₹ crore | 14 |
| Wipro | Profit attributable to equity holders | 131,354 | ₹ million | 273 |

After checking, set `label_source` in the gold file to say so, and correct any value that differs.
