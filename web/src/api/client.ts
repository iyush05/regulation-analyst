import type { components } from "./schema";

export type Result = components["schemas"]["Result"];
export type Job = components["schemas"]["Job"];
export type AskRequest = components["schemas"]["AskRequest"];
export type AgentRequest = components["schemas"]["AgentRequest"];
export type IngestRequest = components["schemas"]["IngestRequest"];

/** Shapes inside Result.data that the UI reads; the API types `data` as an open object. */
export interface Source {
  evidence_id: string;
  title: string;
  location: string;
  url: string;
  trust: "reviewed" | "automated" | "llm_resolved";
  integrity: "local_snapshot" | "remote_reference_only";
}
export interface Company {
  id: string;
  name: string;
  aliases: string[];
  fiscal_years: number[];
  fact_count: number;
}
export interface CoverageSlot {
  metrics: string[];
  trust: Record<string, number>;
}
export interface Filing {
  fiscal_year: number;
  status: string;
  url?: string;
  title?: string;
  download_error?: string;
  inbox_error?: string;
  map_error?: string;
  gate?: { imported: number; queued: number; restated_later: string[] };
}
export interface IngestResult {
  company: { id: string; name: string };
  filings: Filing[];
  not_found: number[];
}

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const TOKEN_KEY = "regulation-analyst-token";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Private windows may refuse storage; the token then lasts for this page only.
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(BASE + path, {
    ...init,
    headers: { Authorization: `Bearer ${getToken()}`, ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // Non-JSON error bodies keep the status text.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<{ status: string; version: string }>("/api/health"),
  companies: () => request<Result>("/api/companies"),
  coverage: (company: string) =>
    request<Result>(`/api/companies/${encodeURIComponent(company)}/coverage`),
  ask: (body: AskRequest) => request<Result>("/api/ask", json(body)),
  agent: (body: AgentRequest) => request<Job>("/api/agent", json(body)),
  ingest: (body: IngestRequest) => request<Job>("/api/ingest", json(body)),
  upload: (company: string, years: string[], file: File) => {
    const form = new FormData();
    form.append("company", company);
    form.append("years", years.join(","));
    form.append("file", file);
    return request<Job>("/api/ingest/upload", { method: "POST", body: form });
  },
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  jobs: () => request<Job[]>("/api/jobs"),
  /** Page images need the auth header, so they are fetched as blobs, not <img src>. */
  pageImage: async (evidenceId: string): Promise<string> => {
    const response = await fetch(
      `${BASE}/api/sources/${encodeURIComponent(evidenceId)}/page.png`,
      { headers: { Authorization: `Bearer ${getToken()}` } },
    );
    if (!response.ok) throw new ApiError(response.status, "No archived copy of this page");
    return URL.createObjectURL(await response.blob());
  },
};
