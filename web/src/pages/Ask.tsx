import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Result } from "../api/client";
import { Answer } from "../components/Answer";
import { type AgentStep, Steps } from "../components/Steps";
import { elapsed, isRunning, useJob, useNow } from "../components/useJob";

const EXAMPLES = [
  "Compare Infosys and TCS net margin FY23 to FY25",
  "Infosys operating margin change FY24 to FY25",
  "Infosys ROE change FY24 to FY25",
  "Infosys operating margin FY25 and what did management say?",
];

type Mode = "rules" | "agent";

/** A per-browser setting; storage may be unavailable, in which case the default is used. */
function usePreference<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(`regulation-analyst-${key}`);
      return stored === null ? initial : (JSON.parse(stored) as T);
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(`regulation-analyst-${key}`, JSON.stringify(value));
    } catch {
      // Not remembered across visits; the page still works.
    }
  }, [key, value]);
  return [value, setValue] as const;
}

// The rule-based workflow's answer when no company in the question is in the database.
const UNKNOWN_COMPANY = "Name a covered company";

export function Ask() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = usePreference<Mode>("mode", "rules");
  const [reviewedOnly, setReviewedOnly] = useState(false);
  const [allowIngest, setAllowIngest] = usePreference("allow-ingest", true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [handedOver, setHandedOver] = useState(false);
  const trust = reviewedOnly ? "reviewed_only" : "allow_automated";

  const agent = useMutation({
    mutationFn: (ingest: boolean) => api.agent({ question, trust, allow_ingest: ingest }),
    onSuccess: (job) => setJobId(job.id),
  });
  const ask = useMutation({
    mutationFn: () => api.ask({ question, trust }),
    onSuccess: (result) => {
      // A company the database lacks: let the agent find and import it.
      if (result.status === "not_found" && result.message.startsWith(UNKNOWN_COMPANY)) {
        setHandedOver(true);
        setMode("agent");
        setJobId(null);
        agent.mutate(true);
      }
    },
  });
  const job = useJob(mode === "agent" ? jobId : null);
  const now = useNow(isRunning(job.data));
  const steps = (job.data?.progress ?? []) as unknown as AgentStep[];

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setHandedOver(false);
    if (mode === "rules") ask.mutate();
    else {
      setJobId(null);
      agent.mutate(allowIngest);
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
      {handedOver && (
        <p className="notice">
          That company isn't in the database yet, so the agent is finding, downloading, and
          importing its annual reports first. This usually takes a few minutes.
        </p>
      )}
      {mode === "agent" && job.data && job.data.status !== "done" && (
        <section className="card working">
          <p className="muted status-line">
            {job.data.status === "failed"
              ? `Agent run failed: ${job.data.error}`
              : job.data.status === "queued"
                ? "Waiting for the previous job to finish…"
                : `Agent working · ${elapsed(job.data, now)}`}
          </p>
          {steps.length > 0 && <Steps steps={steps} now={now} />}
        </section>
      )}
      {result && <Answer result={result} />}
      {mode === "agent" && job.data?.status === "done" && steps.length > 0 && (
        <details className="card how">
          <summary>
            How this answer was found ({steps.filter((s) => s.kind === "tool").length} steps,{" "}
            {elapsed(job.data, now)})
          </summary>
          <Steps steps={steps} now={now} />
        </details>
      )}
    </div>
  );
}
