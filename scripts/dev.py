"""Cross-platform local supervisor. Ctrl+C stops the API, mock portal, frontend, and agent."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if not (ROOT / ".env").exists():
    shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
    (ROOT / ".env").chmod(0o600)
manager = shutil.which("pnpm") or shutil.which("npm")
if not manager:
    sys.exit("Install Node.js 22+ and npm or pnpm first.")
processes = []
try:
    for module, port in [("backend.app.main", "8000"), ("mock_portal.main", "8001")]:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    module + ":app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    port,
                    "--no-access-log",
                ]
            )
        )
    processes.append(subprocess.Popen([manager, "run", "dev"], cwd=ROOT / "frontend", shell=os.name == "nt"))
    print("Blink: http://127.0.0.1:5173 · Local API: 8000 · Mock portal: 8001", flush=True)
    for process in processes:
        process.wait()
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
