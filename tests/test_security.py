import pytest
from browser_agent.policy import WorkflowPolicy, PolicyError, canonical, job_key
from browser_agent.validator import classify_title
from browser_agent.parser import Field
from browser_agent.resolver import AnswerResolver
from backend.app.ai import AIService
from backend.app.config import settings, access_code
from backend.app.memory import fingerprint
from database.models import Application
from backend.app.documents import document_payload


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8000/api/profile",
        "https://gmail.com",
        "https://jobs.lever.co/company/account",
        "https://boards.greenhouse.io/company/jobs/123/../../account",
        "https://evil.myworkdayjobs.com.attacker.test/en-US/jobs/job/Intern",
        "https://user:password@jobs.lever.co/c/00000000-0000-0000-0000-000000000000",
    ],
)
def test_reject_unapproved_urls(url):
    with pytest.raises(PolicyError):
        WorkflowPolicy(url, True)


def test_policy_guards_every_operation():
    p = WorkflowPolicy("http://127.0.0.1:8001/mock/jobs/test", True)
    with pytest.raises(PolicyError):
        p.interaction(p.initial_url)
    with pytest.raises(PolicyError):
        p.navigation("http://127.0.0.1:8001/mock/jobs/non-intern")
    with pytest.raises(PolicyError):
        p.permit_apply_link(p.initial_url + "/apply")
    with pytest.raises(PolicyError):
        p.require_submit()
    p.verified = True
    assert p.permit_apply_link(p.initial_url + "/apply")
    assert not p.request_allowed("http://127.0.0.1:8000/api/profile", "fetch")
    assert not p.request_allowed(p.initial_url + "/submit", "fetch", "POST")
    p.submission_permit = True
    assert p.request_allowed(p.initial_url + "/submit", "fetch", "POST")
    assert not p.request_allowed("http://127.0.0.1:8001/mock/jobs/another/submit", "fetch", "POST")
    assert not p.request_allowed("https://example.com/exfil", "image")
    assert not p.request_allowed("file:///etc/passwd", "document")
    p.stopped = True
    assert not p.request_allowed(p.initial_url, "document")


def test_no_authorization_sponsorship_conflation():
    assert fingerprint("Are you authorized to work in the United States?") != fingerprint(
        "Will you require sponsorship now or in the future?"
    )
    assert fingerprint("Will you require sponsorship now?") != fingerprint(
        "Will you require sponsorship in the future?"
    )
    assert fingerprint("Available May through August 2027?") != fingerprint(
        "Available May through August 2028?"
    )
    assert fingerprint("Email address?") == fingerprint("email address")


def test_title_validation_not_body_instructions():
    assert classify_title("Senior Software Engineer") == "rejected"
    assert classify_title("Summer Analyst") == "ambiguous"
    assert classify_title("Technology Internship") == "internship"
    assert classify_title("Internship Program Manager") == "rejected"


def test_api_origin_auth_upload_encryption_and_memory(client, profile_data):
    client.headers.pop("Authorization")
    client.cookies.clear()
    assert client.get("/api/profile").status_code == 401
    assert client.get("/api/session").status_code == 403
    assert (
        client.get(
            "/api/session", headers={"Origin": "http://evil.test", "X-Local-Client": "internship-ui"}
        ).status_code
        == 403
    )
    assert client.get("/api/session", headers={"X-Local-Client": "internship-ui"}).status_code == 403
    assert (
        client.get(
            "/api/session", headers={"X-Local-Client": "internship-ui", "X-Blink-Access": "wrong"}
        ).status_code
        == 403
    )
    token = client.get(
        "/api/session", headers={"X-Local-Client": "internship-ui", "X-Blink-Access": access_code()}
    ).json()["token"]
    client.headers.update({"Authorization": "Bearer " + token})
    assert client.put("/api/profile", json=profile_data).status_code == 200
    assert client.get("/api/profile").json() == profile_data
    doc = client.post(
        "/api/documents",
        files={"file": ("../resume.pdf", b"%PDF-1.4 synthetic-resume-secret", "application/pdf")},
        data={"default": "true"},
    ).json()
    assert doc["name"] == "resume.pdf"
    assert document_payload(doc["id"])["buffer"] == b"%PDF-1.4 synthetic-resume-secret"
    assert b"synthetic-resume-secret" not in (settings().data_dir / "documents" / doc["id"]).read_bytes()
    with pytest.raises(ValueError):
        document_payload("/etc/passwd")
    assert client.post("/api/documents", files={"file": ("fake.pdf", b"not a PDF")}).status_code == 400
    result = client.post("/api/memory", json={"question": "Gender", "answer": "Nonbinary"})
    assert result.status_code == 400
    assert (
        client.post(
            "/api/memory", json={"question": "Gender", "answer": "Nonbinary", "sensitive_permission": True}
        ).status_code
        == 200
    )
    for file in settings().data_dir.glob("app.sqlite3*"):
        assert b"Synthetic University" not in file.read_bytes()
        assert b"synthetic@example.test" not in file.read_bytes()
    memory = client.get("/api/memory").json()[0]
    assert client.delete("/api/memory/" + memory["id"]).status_code == 200
    assert client.get("/api/memory").json() == []


async def test_eligibility_scope_and_sensitive_never_inferred(client, profile_data):
    client.put("/api/profile", json=profile_data)
    resolver = AnswerResolver(AIService())
    app = Application(id="test", data={"answers": []})

    def field(label):
        return Field("f", label, "text", True, [])

    assert await resolver.resolve(field("Are you authorized to work in Canada?"), app) is None
    assert await resolver.resolve(field("Do you require sponsorship now?"), app) is None
    assert await resolver.resolve(field("Gender"), app) is None
    assert (
        await resolver.resolve(field("Are you legally authorized to work in the United States?"), app)
    ).answer == "Yes"
    assert (
        await resolver.resolve(
            field("Will you now or in the future require visa sponsorship in the United States?"), app
        )
    ).answer == "No"


def test_job_identity_ignores_tracking_and_workday_title_changes(monkeypatch):
    monkeypatch.setattr("browser_agent.policy.public_host", lambda _: None)
    assert job_key("https://workday.wd5.myworkdayjobs.com/en-US/Workday/job/City/Intern_R-12") == job_key(
        "https://workday.wd5.myworkdayjobs.com/en-US/Workday/job/Other/Software-Intern_R-12?source=linkedin"
    )
    assert (
        canonical("http://127.0.0.1:8001/mock/jobs/test/?utm=test") == "http://127.0.0.1:8001/mock/jobs/test"
    )


def test_duplicate_keys_cover_equivalent_portal_host_aliases():
    assert job_key("http://localhost:8001/mock/jobs/test", True) == job_key(
        "http://127.0.0.1:8001/mock/jobs/test", True
    )
    assert job_key("https://boards.greenhouse.io/example/jobs/123") == job_key(
        "https://job-boards.greenhouse.io/example/jobs/123"
    )


def test_local_pairing_secret_stays_private(client):
    import os
    import stat

    code = access_code()
    path = settings().data_dir / "access-code"
    assert path.read_text() == code
    assert len(code) >= 32
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    paired = client.get("/api/session", headers={"X-Local-Client": "internship-ui", "X-Blink-Access": code})
    assert paired.status_code == 200
    assert code not in paired.text
    assert client.get("/api/access-code").status_code == 404
