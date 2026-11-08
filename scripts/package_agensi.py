"""Build the text-only marketplace ZIP from an explicit file allowlist."""

import argparse
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "SKILL.md",
    "references/connection.md",
    "references/tool-guide.md",
    "templates/research-report.md",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist" / "regulation-analyst-agensi.zip"
    )
    args = parser.parse_args()
    source = ROOT / "marketplace" / "regulation-analyst"
    contents = {}
    for name in FILES:
        path = source / name
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError(f"Package member must be a local regular file: {name}")
        contents[name] = path.read_text(encoding="utf-8").encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(contents.items()):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f"Built {args.output} ({len(contents)} text files)")
    print(f"SHA256 {digest}")


if __name__ == "__main__":
    main()
