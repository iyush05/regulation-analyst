import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  api,
  type Company,
  type CoverageSlot,
  type Filing,
  type IngestResult,
  type Job,
} from "../api/client";
import { elapsed, useJob } from "../components/useJob";

const YEAR_CHOICES = ["FY22", "FY23", "FY24", "FY25", "FY26"];

export function Companies() {
  const companies = useQuery({ queryKey: ["companies"], queryFn: api.companies });
  const [selected, setSelected] = useState<string | null>(null);
  const list = (companies.data?.data?.companies ?? []) as Company[];
  return (
    <div className="page-body two-column">
      <section className="card">
        <h2>Companies</h2>
        {companies.isPending && <p className="muted">Loading…</p>}
        {companies.error && <p className="error">{(companies.error as Error).message}</p>}
        <ul className="company-list">
          {list.map((company) => (
            <li key={company.id}>
              <button
                type="button"
                className={selected === company.id ? "row on" : "row"}
                onClick={() => setSelected(company.id)}
              >
                <strong>{company.name}</strong>
                <span className="muted">
                  {company.fiscal_years.length
                    ? `FY${company.fiscal_years[0] % 100}–FY${company.fiscal_years.at(-1)! % 100}`
                    : "no figures"}{" "}
                  · {company.fact_count} figures
                </span>
              </button>
            </li>
          ))}
        </ul>
        <AddCompany />
      </section>
      <section className="card">
        {selected ? <Coverage company={selected} /> : <p className="muted">Select a company.</p>}
      </section>
    </div>
  );
}

function Coverage({ company }: { company: string }) {
  const coverage = useQuery({
    queryKey: ["coverage", company],
    queryFn: () => api.coverage(company),
  });
  if (coverage.isPending) return <p className="muted">Loading…</p>;
  if (coverage.error) return <p className="error">{(coverage.error as Error).message}</p>;
  const data = coverage.data.data ?? {};
  const years = (data.years ?? {}) as Record<string, Record<string, CoverageSlot>>;
  return (
    <>
      <h2>{(data.company as { name: string } | undefined)?.name ?? company}</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Year</th>
              <th>Statements</th>
              <th>Line items</th>
              <th>Verification</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(years).map(([year, selections]) =>
              Object.entries(selections).map(([selection, slot]) => (
                <tr key={`${year}-${selection}`}>
                  <td>FY{Number(year) % 100}</td>
                  <td>{selection}</td>
                  <td title={slot.metrics.join(", ")}>{slot.metrics.length}</td>
                  <td>
                    {Object.entries(slot.trust)
                      .map(([trust, count]) => `${count} ${trust.replace("_", "-")}`)
                      .join(", ")}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

function AddCompany() {
  const [name, setName] = useState("");
  const [years, setYears] = useState<string[]>(["FY24", "FY25"]);
  const [jobId, setJobId] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => api.ingest({ company: name.trim(), years }),
    onSuccess: (job) => setJobId(job.id),
  });
  return (
    <div className="add-company">
      <h3>Add a company</h3>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setJobId(null);
          start.mutate();
        }}
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Company name or NSE symbol, e.g. Wipro"
          required
          minLength={2}
        />
        <div className="year-picks">
          {YEAR_CHOICES.map((year) => (
            <label key={year} className="check">
              <input
                type="checkbox"
                checked={years.includes(year)}
                onChange={(e) =>
                  setYears(
                    e.target.checked
                      ? [...years, year].sort()
                      : years.filter((y) => y !== year),
                  )
                }
                disabled={!years.includes(year) && years.length >= 3}
              />
              {year}
            </label>
          ))}
        </div>
        <button type="submit" disabled={start.isPending || !name.trim() || years.length === 0}>
          Find and import reports
        </button>
      </form>
      {start.error && <p className="error">{(start.error as Error).message}</p>}
      {jobId && <IngestProgress jobId={jobId} company={name.trim()} years={years} onJob={setJobId} />}
    </div>
  );
}

const FILING_LABEL: Record<string, string> = {
  imported: "Imported",
  imported_with_queue: "Imported; some values need review",
  review_required: "Mapped; awaiting import",
  needs_manual_pdf: "Download refused — upload the PDF",
  map_failed: "Statements not recognised",
  archived: "Downloaded",
};

function IngestProgress(props: {
  jobId: string;
  company: string;
  years: string[];
  onJob: (id: string) => void;
}) {
  const job = useJob(props.jobId);
  const queries = useQueryClient();
  const finished = job.data?.status === "done";
  useEffect(() => {
    if (finished) queries.invalidateQueries({ queryKey: ["companies"] });
  }, [finished, queries]);
  if (!job.data) return <p className="muted">Starting…</p>;
  if (job.data.status === "failed") return <p className="error">{job.data.error}</p>;
  const result = job.data.result as IngestResult | null | undefined;
  return (
    <div className="progress">
      <p className="muted">
        {finished ? "Finished" : `Working (${job.data.status})`} · {elapsed(job.data)}
      </p>
      {!finished && <Steps job={job.data} />}
      {result && (
        <ul className="filings">
          {result.filings.map((filing) => (
            <FilingRow key={filing.fiscal_year} filing={filing} {...props} />
          ))}
          {result.not_found.map((year) => (
            <li key={year}>FY{year % 100}: no official annual report link found</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Steps({ job }: { job: Job }) {
  const steps = (job.progress ?? []).filter((p) => p.item !== "company");
  if (!steps.length) return <p className="muted">Identifying the company and its filings…</p>;
  return (
    <ul className="steps">
      {steps.map((step) => (
        <li key={String(step.item)}>
          {String(step.item)}: {String(step.stage)} · {String(step.status)}
        </li>
      ))}
    </ul>
  );
}

function FilingRow({
  filing,
  company,
  years,
  onJob,
}: {
  filing: Filing;
  company: string;
  years: string[];
  onJob: (id: string) => void;
}) {
  const upload = useMutation({
    mutationFn: (file: File) => api.upload(company, years, file),
    onSuccess: (job) => onJob(job.id),
  });
  return (
    <li>
      <strong>FY{filing.fiscal_year % 100}</strong>: {FILING_LABEL[filing.status] ?? filing.status}
      {filing.gate && (
        <span className="muted">
          {" "}
          · {filing.gate.imported} imported
          {filing.gate.queued ? `, ${filing.gate.queued} queued for review` : ""}
          {filing.gate.restated_later?.length ? `, ${filing.gate.restated_later.length} restated later` : ""}
        </span>
      )}
      {filing.status === "needs_manual_pdf" && filing.url && (
        <div className="upload">
          <a href={filing.url} target="_blank" rel="noreferrer">
            Open the official PDF
          </a>
          , save it, then upload it here:{" "}
          <input
            type="file"
            accept="application/pdf"
            disabled={upload.isPending}
            onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])}
          />
          {upload.error && <p className="error">{(upload.error as Error).message}</p>}
        </div>
      )}
      {filing.map_error && <p className="error">{filing.map_error}</p>}
    </li>
  );
}
