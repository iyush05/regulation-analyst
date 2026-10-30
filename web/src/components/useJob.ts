import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Job } from "../api/client";

/** Polls a background job until it finishes. */
export function useJob(jobId: string | null) {
  return useQuery<Job>({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId!),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "failed" ? false : 1000;
    },
  });
}

/** The current time, re-rendering every second while `active`, so timers visibly tick. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    setNow(Date.now() / 1000);
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

/** Download progress recorded by the pipeline, e.g. "8.4 MB of 52.0 MB". */
export function downloaded(detail: unknown): string {
  const d = detail as { downloaded_bytes?: number; total_bytes?: number | null } | undefined;
  if (!d?.downloaded_bytes) return "";
  const mb = (bytes: number) => `${(bytes / 1e6).toFixed(1)} MB`;
  return ` · ${mb(d.downloaded_bytes)}${d.total_bytes ? ` of ${mb(d.total_bytes)}` : ""}`;
}

export function duration(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return whole < 60 ? `${whole}s` : `${Math.floor(whole / 60)}m ${whole % 60}s`;
}

export function elapsed(job: Job, now: number): string {
  const end = job.finished_at ?? now;
  return duration(end - (job.started_at ?? job.created_at));
}

export function isRunning(job: Job | undefined): boolean {
  return job?.status === "queued" || job?.status === "running";
}
