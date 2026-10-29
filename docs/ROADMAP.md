# Remaining research and release work

Core workflows now include acquisition/review, hybrid retrieval, a bounded agent, regulatory
version resolution, and four experiment runners. See [completion status](COMPLETION_STATUS.md)
for the implementation/execution distinction and [the original completion plan](COMPLETION_PLAN.md).

Remaining work depends on actual inputs and validation:

1. Archive official PDFs, finish HCLTech tables and comparable operating-profit definitions,
   add opening equity and missing management transcripts, and verify publication dates.
2. Review difficult pages and run OCR/parser evaluations; add a second parser only if measured
   failures justify it.
3. Configure embeddings/reranker and measure retrieval against independently labeled evidence.
4. Configure a live agent model, run protocol and behavior checks, then execute A/B/C/D comparisons.
5. Expand and independently audit narrow SEBI/RBI amendment histories before extending verified dates.
6. Independently review labels; acquire distinct sources for a held-out set; freeze before tuning.
7. Publish measured results and a recorded demonstration. No live error-reduction statistic exists yet.
