import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type Result, type Source } from "../api/client";

const STATUS_LABEL: Record<string, string> = {
  ok: "Answered",
  partial: "Partly answered",
  not_found: "Not found",
  ambiguous: "Needs clarification",
  invalid_request: "Invalid request",
  out_of_scope: "Out of scope",
  undefined: "Undefined",
};

const TRUST_LABEL: Record<Source["trust"], string> = {
  reviewed: "reviewed",
  automated: "automated extraction",
  llm_resolved: "LLM-resolved",
};

export function Answer({ result }: { result: Result }) {
  const data = result.data ?? {};
  const text = typeof data.answer === "string" ? data.answer : null;
  const sources = Array.isArray(data.sources) ? (data.sources as Source[]) : [];
  return (
    <section className="answer">
      <div className="answer-head">
        <span className={`badge badge-${result.status}`}>
          {STATUS_LABEL[result.status] ?? result.status}
        </span>
        {!text && <span className="muted">{result.message}</span>}
      </div>
      {text && (
        <div className="markdown">
          <Markdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ children, href }) => (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              ),
            }}
          >
            {text}
          </Markdown>
        </div>
      )}
      {sources.length > 0 && <Evidence sources={sources} />}
    </section>
  );
}

function Evidence({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <details className="evidence">
      <summary>Check the evidence ({sources.length} cited cells)</summary>
      <ul>
        {sources.map((source) => (
          <li key={source.evidence_id}>
            <div className="evidence-row">
              <span>
                {source.title}, {source.location}{" "}
                <span className={`trust trust-${source.trust}`}>{TRUST_LABEL[source.trust]}</span>
              </span>
              <span className="evidence-actions">
                {source.integrity === "local_snapshot" && (
                  <button
                    type="button"
                    className="link"
                    onClick={() => setOpen(open === source.evidence_id ? null : source.evidence_id)}
                  >
                    {open === source.evidence_id ? "Hide page" : "Show cell"}
                  </button>
                )}
                <a href={source.url} target="_blank" rel="noreferrer">
                  Official PDF
                </a>
              </span>
            </div>
            {open === source.evidence_id && <PagePreview evidenceId={source.evidence_id} />}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The archived page, rendered by the API with the cited cell outlined in red. */
function PagePreview({ evidenceId }: { evidenceId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let created: string | null = null;
    let cancelled = false;
    api
      .pageImage(evidenceId)
      .then((objectUrl) => {
        created = objectUrl;
        if (!cancelled) setUrl(objectUrl);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [evidenceId]);
  if (error) return <p className="muted">{error}</p>;
  if (!url) return <p className="muted">Rendering page…</p>;
  return <img className="page" src={url} alt="Source page with the cited cell outlined" />;
}
