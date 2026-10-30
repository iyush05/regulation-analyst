import { downloaded, duration } from "./useJob";

export interface AgentStep {
  kind: "model" | "tool";
  tool?: string;
  label: string;
  status: string;
  summary?: string;
  started_at: number;
  finished_at?: number;
  detail?: { item: string; stage: string; status: string; detail?: unknown }[];
}

const ICON: Record<string, string> = {
  running: "",
  done: "✓",
  ok: "✓",
  partial: "◐",
  not_found: "–",
  rejected: "↺",
  failed: "✕",
  invalid_request: "✕",
  ambiguous: "?",
};

/** The agent's steps as reported by the API. Model turns appear only while in progress. */
export function Steps({ steps, now }: { steps: AgentStep[]; now: number }) {
  const shown = steps.filter((s, i) => s.kind === "tool" || i === steps.length - 1);
  return (
    <ol className="agent-steps">
      {shown.map((step, index) => {
        const running = step.status === "running";
        const seconds = (step.finished_at ?? (running ? now : step.started_at)) - step.started_at;
        return (
          <li key={`${index}-${step.started_at}`} className={`step step-${step.status}`}>
            <span className="step-icon" aria-hidden>
              {running ? <span className="spinner" /> : (ICON[step.status] ?? "•")}
            </span>
            <span className="step-body">
              <span className="step-label">
                {step.label}
                {running ? "…" : ""}
              </span>
              {step.summary && <span className="step-summary">{step.summary}</span>}
              {step.detail && step.detail.length > 0 && (
                <ul className="step-detail">
                  {step.detail
                    .filter((d) => d.item !== "company")
                    .map((d) => (
                      <li key={d.item}>
                        {d.item.replace("-annual-report", " annual report")}:{" "}
                        {d.stage === "acquire" && d.status === "running" ? "downloading" : d.stage}{" "}
                        · {d.status.replaceAll("_", " ")}
                        {downloaded(d.detail)}
                      </li>
                    ))}
                </ul>
              )}
            </span>
            {(running || seconds >= 1) && <span className="step-time">{duration(seconds)}</span>}
          </li>
        );
      })}
    </ol>
  );
}
