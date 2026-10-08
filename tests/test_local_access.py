"""Access stays owner-paired despite simpler launch/reload behavior."""

import hmac
import json
import time
import os
import stat
from pathlib import Path
from backend.app.config import settings, access_code
from backend.app.main import LOCAL_SESSIONS
from scripts.launch import private_json, issue_link, compatible_python, owner_health


def ticket(value="synthetic-launch-ticket", expiry=None):
    path = settings().data_dir / "launch-ticket"
    private_json(path, {"ticket": value, "expires_at": expiry or time.time() + 120})
    return path


def test_launch_pairing_is_one_use_and_origin_restricted(client):
    client.cookies.clear()
    headers = {"X-Local-Client": "internship-ui", "X-Blink-Launch": "synthetic-launch-ticket"}
    p = ticket()
    assert (
        client.post("/api/session/launch", headers={**headers, "Origin": "https://evil.test"}).status_code
        == 403
    )
    assert p.exists()  # A rejected origin cannot consume the owner's link.
    assert (
        client.post("/api/session/launch", headers={**headers, "X-Blink-Launch": "wrong"}).status_code == 403
    )
    assert p.exists()
    result = client.post("/api/session/launch", headers=headers)
    assert result.status_code == 200
    assert not p.exists()
    assert "synthetic-launch-ticket" not in result.text
    assert access_code() not in result.text
    assert client.post("/api/session/launch", headers=headers).status_code == 403


def test_expired_corrupt_and_unbounded_tickets_fail_closed(client):
    headers = {"X-Local-Client": "internship-ui", "X-Blink-Launch": "synthetic-launch-ticket"}
    p = ticket(expiry=time.time() - 1)
    assert client.post("/api/session/launch", headers=headers).status_code == 403
    ticket(expiry=time.time() + 1000)
    assert client.post("/api/session/launch", headers=headers).status_code == 403
    p.write_text("not json")
    assert client.post("/api/session/launch", headers=headers).status_code == 403
    p.write_text("x" * 600)
    assert client.post("/api/session/launch", headers=headers).status_code == 403


def test_tab_session_does_not_bypass_auth_origin_or_lock(client):
    first = client.get(
        "/api/session", headers={"X-Local-Client": "internship-ui", "X-Blink-Access": access_code()}
    )
    assert "set-cookie" not in first.headers
    headers = {"X-Local-Client": "internship-ui", "X-Blink-Session": first.json()["session"]}
    restored = client.get("/api/session", headers=headers)
    assert restored.status_code == 200
    assert "set-cookie" not in restored.headers
    assert client.get("/api/session", headers=headers).status_code == 403  # Old tab secret rotates out.
    headers["X-Blink-Session"] = restored.json()["session"]
    assert client.get("/api/session").status_code == 403
    assert client.get("/api/session", headers={**headers, "Origin": "https://evil.test"}).status_code == 403
    assert (
        client.get(
            "/api/profile", headers={"Authorization": "", "X-Blink-Session": headers["X-Blink-Session"]}
        ).status_code
        == 401
    )
    assert client.delete("/api/session", headers=headers).status_code == 200
    assert client.get("/api/session", headers=headers).status_code == 403
    headers["X-Blink-Session"] = "invented"
    assert client.get("/api/session", headers=headers).status_code == 403
    LOCAL_SESSIONS["expired-synthetic-session"] = time.monotonic() - 1
    headers["X-Blink-Session"] = "expired-synthetic-session"
    assert client.get("/api/session", headers=headers).status_code == 403


def test_launcher_proof_reveals_no_private_code(client):
    challenge = "a" * 64
    response = client.get("/api/health", params={"challenge": challenge})
    d = response.json()
    expected = hmac.digest(access_code().encode(), (challenge + ":" + str(d["pid"])).encode(), "sha256").hex()
    assert d["proof"] == expected
    assert access_code() not in response.text
    assert "proof" not in client.get("/api/health", params={"challenge": "bad"}).json()


def test_launch_link_uses_a_short_lived_private_file(tmp_path):
    link = issue_link(tmp_path)
    d = json.loads((tmp_path / "launch-ticket").read_text())
    assert link.startswith("http://127.0.0.1:8000/#launch=")
    assert access_code() not in link
    assert len(d["ticket"]) >= 32
    assert time.time() < d["expires_at"] <= time.time() + 120
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "launch-ticket").stat().st_mode) == 0o600
    assert not compatible_python(Path("/nonexistent/python"))


def test_launcher_rejects_an_unverified_local_service(tmp_path, monkeypatch):
    import io
    import urllib.request

    (tmp_path / "access-code").write_text("a" * 43)
    fake = json.dumps({"pid": 123, "service": "blink", "proof": "not-an-owner-proof"}).encode()
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(fake))
    assert owner_health(tmp_path) is None


def test_private_opener_keeps_credentials_out_of_process_arguments(tmp_path, monkeypatch):
    import scripts.launch as launcher
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    control = tmp_path / "private"
    monkeypatch.setattr(launcher, "CONTROL", control)
    uri = launcher.opening_file(tmp_path)
    ticket_data = json.loads((tmp_path / "launch-ticket").read_text())
    assert ticket_data["ticket"] not in uri
    assert access_code() not in uri
    assert urlparse(uri).scheme == "file"
    body = Path(url2pathname(urlparse(uri).path)).read_text()
    assert 'http-equiv="refresh"' in body and "default-src 'none'" in body
    assert "<script" not in body
    assert ticket_data["ticket"] in body
    assert access_code() not in body
    if os.name != "nt":
        assert stat.S_IMODE((control / "open.html").stat().st_mode) == 0o600
