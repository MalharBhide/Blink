"""Fail CI/commit checks if private artifacts or credential-like values enter tracked source."""

from pathlib import Path
import subprocess
import re
import sys

tracked = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
errors = []
for name in filter(None, tracked):
    p = Path(name)
    if (
        any(part in (".data", ".venv", "node_modules", "__pycache__", "test-results") for part in p.parts)
        or (p.name.startswith(".env") and p.name != ".env.example")
        or p.suffix.lower() in (".pdf", ".docx", ".db", ".sqlite", ".sqlite3", ".log")
    ):
        errors.append(f"Private/generated artifact tracked: {name}")
        continue
    if not p.is_file():
        continue
    text = p.read_text(errors="replace")
    if re.search(r"sk-(?:proj-)?[A-Za-z0-9_-]{24,}", text) or re.search(r"gh[pousr]_[A-Za-z0-9]{30,}", text):
        errors.append(f"Credential-like value detected in {name}")
if errors:
    print("\n".join(errors))
    sys.exit(1)
print(
    f"Checked {len(list(filter(None, tracked)))} tracked files: no private artifacts or credential-like values."
)
