import { useQuery } from "@tanstack/react-query";
import { api, type Job } from "../api/client";

/** Polls a background job until it finishes. */
export function useJob(jobId: string | null) {
  return useQuery<Job>({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId!),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "failed" ? false : 1500;
    },
  });
}

export function elapsed(job: Job): string {
  const end = job.finished_at ?? Date.now() / 1000;
  const seconds = Math.max(0, Math.round(end - (job.started_at ?? job.created_at)));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
