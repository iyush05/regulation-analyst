"""Write a consistent copy of the research database for deployment seeding.

Usage: .venv/bin/python scripts/snapshot_seed.py [data/research.sqlite3] [deploy/seed.sqlite3]

The deployed API copies the snapshot into place when it starts without a database (see
REGULATION_SEED_DB in the Dockerfile). Archived PDFs are not included; answers keep their page,
row, and cell citations, but page images are unavailable on the server.
"""

import sqlite3
import sys
from pathlib import Path


def main() -> int:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "data/research.sqlite3")
    target = Path(sys.argv[2] if len(sys.argv) > 2 else "deploy/seed.sqlite3")
    if not source.is_file():
        print(f"Database not found: {source}", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    # VACUUM INTO writes a compact, transaction-consistent copy, even while the API is running.
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as connection:
        connection.execute("VACUUM INTO ?", (str(target),))
    with sqlite3.connect(target) as connection:
        companies = [row[0] for row in connection.execute("SELECT id FROM companies ORDER BY id")]
        facts = connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    print(
        f"Wrote {target} ({target.stat().st_size // 1024} KB): {facts} facts;",
        ", ".join(companies),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
