import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Result } from "../api/client";
import { Answer } from "../components/Answer";
import { elapsed, useJob } from "../components/useJob";

const EXAMPLES = [
  "Compare Infosys and TCS net margin FY23 to FY25",
  "Infosys operating margin change FY24 to FY25",
  "Infosys ROE change FY24 to FY25",
  "Infosys operating margin FY25 and what did management say?",
];

type Mode = "rules" | "agent";

export function Ask() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<Mode>("rules");
  const [reviewedOnly, setReviewedOnly] = useState(false);
  const [allowIngest, setAllowIngest] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const trust = reviewedOnly ? "reviewed_only" : "allow_automated";

  const ask = useMutation({ mutationFn: () => api.ask({ question, trust }) });
  const agent = useMutation({
    mutationFn: () => api.agent({ question, trust, allow_ingest: allowIngest }),
    onSuccess: (job) => setJobId(job.id),
  });
  const job = useJob(mode === "agent" ? jobId : null);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    if (mode === "rules") ask.mutate();
    else {
      setJobId(null);
      agent.mutate();
    }
  }

  const running = ask.isPending || agent.isPending || job.data?.status === "queued" ||
    job.data?.status === "running";
  const error = (mode === "rules" ? ask.error : agent.error) as Error | null;
  const result: Result | undefined =
    mode === "rules" ? ask.data : (job.data?.result as Result | undefined);

  return (
    <div className="page-body">
      <form onSubmit={submit} className="card ask">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. How did Tata Motors' net margin change from FY24 to FY25?"
          rows={3}
          maxLength={2000}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
        />
        <div className="controls">
          <div className="segmented" role="radiogroup" aria-label="Answering mode">
            {(
              [
                ["rules", "Rule-based", "Instant, no model; one metric per question"],
                ["agent", "Agent", "OpenAI plans the steps; numbers are still computed and cited"],
              ] as const
            ).map(([value, label, hint]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={mode === value}
                title={hint}
                className={mode === value ? "on" : ""}
                onClick={() => setMode(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="check">
            <input
              type="checkbox"
              checked={reviewedOnly}
              onChange={(e) => setReviewedOnly(e.target.checked)}
            />
            Reviewed figures only
          </label>
          {mode === "agent" && (
            <label className="check" title="Finds, downloads, validates, and imports reports">
              <input
                type="checkbox"
                checked={allowIngest}
                onChange={(e) => setAllowIngest(e.target.checked)}
              />
              Add missing companies
            </label>
          )}
          <button type="submit" disabled={running || !question.trim()}>
            {running ? "Working…" : "Ask"}
          </button>
        </div>
        <div className="examples">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="chip"
              onClick={() => setQuestion(example)}
            >
              {example}
            </button>
          ))}
        </div>
      </form>

      {error && <p className="error">{error.message}</p>}
      {mode === "agent" && job.data && job.data.status !== "done" && (
        <p className="muted status-line">
          {job.data.status === "failed"
            ? `Agent run failed: ${job.data.error}`
            : `Agent ${job.data.status}… ${elapsed(job.data)}${allowIngest ? " (adding a company can take a few minutes)" : ""}`}
        </p>
      )}
      {result && <Answer result={result} />}
    </div>
  );
}
