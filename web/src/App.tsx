import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getToken, setToken } from "./api/client";
import { Login } from "./components/Login";
import { Ask } from "./pages/Ask";
import { Companies } from "./pages/Companies";

type Page = "ask" | "companies";

export default function App() {
  const [signedIn, setSignedIn] = useState(() => Boolean(getToken()));
  const [page, setPage] = useState<Page>("ask");
  const queries = useQueryClient();

  if (!signedIn) return <Login onLogin={() => setSignedIn(true)} />;

  return (
    <>
      <header className="top">
        <span className="brand">Regulation Analyst</span>
        <nav>
          {(
            [
              ["ask", "Ask"],
              ["companies", "Companies"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={page === value ? "on" : ""}
              aria-current={page === value ? "page" : undefined}
              onClick={() => setPage(value)}
            >
              {label}
            </button>
          ))}
        </nav>
        <button
          type="button"
          className="link"
          onClick={() => {
            setToken("");
            queries.clear();
            setSignedIn(false);
          }}
        >
          Sign out
        </button>
      </header>
      {page === "ask" ? <Ask /> : <Companies />}
    </>
  );
}
