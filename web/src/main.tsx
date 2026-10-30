import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ApiError } from "./api/client";
import "./styles.css";

const queries = new QueryClient({
  defaultOptions: {
    queries: {
      // An invalid token will not become valid by retrying.
      retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queries}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
