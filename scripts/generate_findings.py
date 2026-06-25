#!/usr/bin/env python3
"""
scripts/generate_findings.py — DEPRECATED

Use scripts/generate_docx.py instead:
  python scripts/generate_docx.py docs/findings_summary.md docs/findings_summary.docx
"""
import sys
from pathlib import Path
from scripts.generate_docx import build_docx


def main():
    md_path = Path("docs/findings_summary.md")
    docx_path = Path("docs/findings_summary.docx")

    if not md_path.exists():
        print(f"Source not found: {md_path}")
        print("Usage: python scripts/generate_docx.py <md_path> <docx_path>")
        sys.exit(1)

    build_docx(md_path, docx_path)


if __name__ == "__main__":
    main()
