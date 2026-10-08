"""Double-click entry point. Standard-library only, compatible with bootstrap Python 3.9+."""

import argparse
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / ".data" / "launcher"
URL = "http://127.0.0.1:8000"


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_name(path.name + "." + secrets.token_hex(4))
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
    os.replace(temporary, path)


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def output(command, env=None, timeout=30):
    return (
        subprocess.check_output(command, cwd=ROOT, env=env, stderr=subprocess.DEVNULL, timeout=timeout)
        .decode()
        .strip()
    )


def compatible_python(candidate):
    try:
        return (
            bool(candidate)
            and output(
                [str(candidate), "-c", "import sys; print(int(sys.version_info >= (3,12)))"], timeout=10
            )
            == "1"
        )
    except (OSError, subprocess.SubprocessError):
        return False


def compatible_node(candidate):
    try:
        parts = output([str(candidate), "--version"], timeout=10).lstrip("v").split(".")
        return tuple(map(int, parts[:2])) >= (22, 12)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def runtime():
    cfg = read_json(CONTROL / "runtime.json")
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
    candidates = [
        cfg.get("python"),
        ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),
        sys.executable,
    ]
    candidates += [
        shutil.which(name) for name in ("python3.14", "python3.13", "python3.12", "python3", "python")
    ]
    candidates += [bundled / "python/bin/python3"]
    if os.name == "nt" and shutil.which("py"):
        try:
            candidates.append(output(["py", "-3", "-c", "import sys; print(sys.executable)"]))
        except subprocess.SubprocessError:
            pass
    python = next((str(p) for p in candidates if compatible_python(p)), None)
    node = next(
        (
            str(p)
            for p in [cfg.get("node"), shutil.which("node"), bundled / "node/bin/node"]
            if compatible_node(p)
        ),
        None,
    )
    if not python:
        raise RuntimeError(
            "Python 3.12 or newer is missing. Install it from https://www.python.org/downloads/, then open Launch Blink again."
        )
    if not node:
        raise RuntimeError(
            "Node.js 22.12 or newer is missing. Install the LTS version from https://nodejs.org/, then open Launch Blink again."
        )
    # Reuse a deliberately configured environment; otherwise isolate downloaded dependencies.
    if cfg.get("python") != python and not (Path(python).parent.parent / "pyvenv.cfg").exists():
        venv = ROOT / ".venv"
        print("Preparing Blink's private Python environment…", flush=True)
        subprocess.run([python, "-m", "venv", str(venv)], cwd=ROOT, check=True)
        python = str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    env = dict(os.environ)
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    pnpm = cfg.get("pnpm") or shutil.which("pnpm", path=env["PATH"])
    if not pnpm and (bundled / "bin/fallback/pnpm").exists():
        pnpm = str(bundled / "bin/fallback/pnpm")
    if pnpm and Path(pnpm).exists():
        manager = [pnpm]
    else:
        npm = shutil.which("npm", path=env["PATH"])
        if not npm:
            raise RuntimeError(
                "Node.js was found but npm is missing. Reinstall Node.js LTS, then open Launch Blink again."
            )
        manager = [npm, "exec", "--yes", "--package=pnpm@11", "--", "pnpm"]
    cfg = {"python": python, "node": node, "manager": manager}
    if pnpm:
        cfg["pnpm"] = pnpm
    private_json(CONTROL / "runtime.json", cfg)
    return cfg, env


def digest(paths):
    total = hashlib.sha256()
    for p in sorted(paths):
        total.update(str(p.relative_to(ROOT)).encode())
        total.update(p.read_bytes())
    return total.hexdigest()


def install(cfg, env):
    if not (ROOT / ".env").exists():
        shutil.copyfile(ROOT / ".env.example", ROOT / ".env")
        (ROOT / ".env").chmod(0o600)
    state = read_json(CONTROL / "setup.json")
    lock = ROOT / "backend/requirements.lock.txt"
    stamp = hashlib.sha256(lock.read_bytes()).hexdigest() + cfg["python"]
    if state.get("python") != stamp:
        # Existing configured environments may already have exactly the locked packages.
        probe = 'import importlib.metadata as m; from pathlib import Path; exec(\'for line in Path("backend/requirements.lock.txt").read_text().splitlines():\\n if line and not line.startswith("uvloop"):\\n  name,version=line.split(";")[0].strip().split("=="); assert m.version(name)==version\')'
        try:
            output([cfg["python"], "-c", probe], env, timeout=30)
        except (OSError, subprocess.SubprocessError):
            print("First-time setup: downloading Blink's Python components…", flush=True)
            subprocess.run(
                [cfg["python"], "-m", "pip", "install", "-r", str(lock)], cwd=ROOT, env=env, check=True
            )
        state["python"] = stamp
    pkg = ROOT / "frontend/package.json"
    front_stamp = digest([pkg, ROOT / "frontend/pnpm-lock.yaml"])
    if state.get("frontend") != front_stamp:
        probe = "const fs=require('fs');const p=require('./frontend/package.json');for(const [n,v] of Object.entries({...p.dependencies,...p.devDependencies}))if(JSON.parse(fs.readFileSync('./frontend/node_modules/'+n+'/package.json')).version!==v)process.exit(1)"
        try:
            output([cfg["node"], "-e", probe], env)
        except (OSError, subprocess.SubprocessError):
            print("First-time setup: downloading the website components…", flush=True)
            subprocess.run(
                cfg["manager"] + ["install", "--frozen-lockfile"], cwd=ROOT / "frontend", env=env, check=True
            )
        state["frontend"] = front_stamp
    sources = list((ROOT / "frontend/src").rglob("*"))
    source_stamp = digest(
        [p for p in sources if p.is_file()]
        + [pkg, ROOT / "frontend/index.html", ROOT / "frontend/vite.config.ts"]
    )
    if state.get("build") != source_stamp or not (ROOT / "frontend/dist/index.html").exists():
        print("Preparing your website…", flush=True)
        subprocess.run(
            [cfg["node"], str(ROOT / "frontend/node_modules/typescript/bin/tsc"), "-b"],
            cwd=ROOT / "frontend",
            env=env,
            check=True,
        )
        subprocess.run(
            [cfg["node"], str(ROOT / "frontend/node_modules/vite/bin/vite.js"), "build"],
            cwd=ROOT / "frontend",
            env=env,
            check=True,
        )
        state["build"] = source_stamp
    if state.get("browser") != stamp:
        print("Checking the application browser…", flush=True)
        subprocess.run(
            [cfg["python"], "-m", "playwright", "install", "chromium"], cwd=ROOT, env=env, check=True
        )
        state["browser"] = stamp
    private_json(CONTROL / "setup.json", state)
    values = json.loads(
        output(
            [
                cfg["python"],
                "-c",
                "from backend.app.config import settings; import json; s=settings(); print(json.dumps({'data_dir':str(s.data_dir.resolve()),'mock':s.enable_mock_portal}))",
            ],
            env,
        )
    )
    return values


def owner_health(data_dir):
    try:
        challenge = secrets.token_hex(32)
        with urllib.request.urlopen(URL + "/api/health?challenge=" + challenge, timeout=2) as response:
            data = json.load(response)
        code = (data_dir / "access-code").read_text().strip()
        expected = hmac.digest(code.encode(), (challenge + ":" + str(data["pid"])).encode(), "sha256").hex()
        return (
            data
            if data.get("service") == "blink" and hmac.compare_digest(expected, data.get("proof", ""))
            else None
        )
    except (OSError, ValueError, KeyError):
        return None


def occupied(port):
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def supervise(cfg, env, values):
    children = []
    instance = secrets.token_hex(16)
    try:
        if occupied(8000) or (values["mock"] and occupied(8001)):
            raise RuntimeError(
                "Another program is using Blink's local port (8000 or 8001). Close an earlier development server, then launch Blink again."
            )
        modules = [("backend.app.main", 8000)]
        if values["mock"]:
            modules.append(("mock_portal.main", 8001))
        for module, port in modules:
            children.append(
                subprocess.Popen(
                    [
                        cfg["python"],
                        "-m",
                        "uvicorn",
                        module + ":app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                    ],
                    cwd=ROOT,
                    env=env,
                )
            )
        private_json(CONTROL / "running.json", {"instance": instance, "pid": children[0].pid})
        while True:
            stop = read_json(CONTROL / "stop.json")
            if stop.get("instance") == instance:
                break
            if any(child.poll() is not None for child in children):
                raise RuntimeError(
                    "Blink stopped because a local service could not stay running. See .data/launcher/server.log for setup diagnostics."
                )
            time.sleep(0.3)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        current = read_json(CONTROL / "running.json")
        if current.get("instance") == instance:
            (CONTROL / "running.json").unlink(missing_ok=True)
        (CONTROL / "stop.json").unlink(missing_ok=True)


def issue_link(data_dir):
    ticket = secrets.token_urlsafe(32)
    private_json(data_dir / "launch-ticket", {"ticket": ticket, "expires_at": time.time() + 120})
    return URL + "/#launch=" + ticket


def opening_file(data_dir):
    # Opening a raw ticket URL can expose it in OS process arguments. Instead pass only
    # an owner-readable local file path to the browser; its own redirect consumes the ticket.
    link = issue_link(data_dir)
    target = html.escape(link, quote=True)
    body = f"""<!doctype html><meta charset="utf-8"><title>Opening Blink</title>
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; form-action 'none'">
<meta http-equiv="refresh" content="0; url={target}">
<p>Opening your private Blink workspace…</p><p><a href="{target}">Open Blink</a> if it doesn't open automatically.</p>"""
    path = CONTROL / "open.html"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(body)
    path.chmod(0o600)
    return path.resolve().as_uri()


def main():
    parser = argparse.ArgumentParser(description="Open your private Blink workspace.")
    parser.add_argument("--no-open", action="store_true", help="Start without opening a browser.")
    parser.add_argument("--stop", action="store_true", help="Stop only services owned by this launcher.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check Python and Node.js without installing or starting anything.",
    )
    parser.add_argument("--supervise", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.stop:
        current = read_json(CONTROL / "running.json")
        if not current:
            print("Blink is already stopped, or was started using a different launcher.")
            return
        private_json(CONTROL / "stop.json", {"instance": current["instance"]})
        for _ in range(50):
            if not (CONTROL / "running.json").exists():
                print("Blink is stopped. Your saved profile and documents are unchanged.")
                return
            time.sleep(0.3)
        raise RuntimeError(
            "The launcher could not confirm a stop. Check the launcher's terminal or server.log."
        )
    cfg, env = runtime()
    if args.check:
        print("Python and Node.js are ready. Open Launch Blink to set up and start your workspace.")
        return
    values = install(cfg, env) if not args.supervise else read_json(CONTROL / "settings.json")
    if args.supervise:
        supervise(cfg, env, values)
        return
    data_dir = Path(values["data_dir"])
    if not owner_health(data_dir):
        if occupied(8000):
            raise RuntimeError(
                "Port 8000 is occupied by a service this launcher cannot verify. Close the earlier server and try again; Blink will not send an opening ticket to it."
            )
        private_json(CONTROL / "settings.json", values)
        log = CONTROL / "server.log"
        fd = os.open(log, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "a") as stream:
            kwargs = (
                {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            supervisor = subprocess.Popen(
                [cfg["python"], str(Path(__file__).resolve()), "--supervise"],
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=stream,
                **kwargs,
            )
        print("Starting your private workspace…", flush=True)
        for _ in range(120):
            if owner_health(data_dir):
                break
            if supervisor.poll() is not None:
                raise RuntimeError(
                    "Blink could not start. Check .data/launcher/server.log; a local port may already be in use."
                )
            time.sleep(0.5)
        else:
            raise RuntimeError(
                "Blink is taking longer than expected to start. Try Launch Blink again in a moment."
            )
    print("Blink is ready at " + URL, flush=True)
    if not args.no_open:
        if not webbrowser.open(opening_file(data_dir)):
            raise RuntimeError(
                "Your browser could not open automatically. Open http://127.0.0.1:8000 and use your private access code, or try Launch Blink again."
            )
    print("You can close this launcher window. Blink stays running. Use Stop Blink to close it.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print("\nBlink couldn't open: " + str(exc), file=sys.stderr)
        print("Your saved information has not been deleted. See README.md for help.", file=sys.stderr)
        sys.exit(1)
