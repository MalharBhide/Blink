import time
from uuid import uuid4
from conftest import await_status

PDF = b"%PDF-1.4\n1 0 obj<</Type /Catalog>>endobj\n%%EOF"


def prepare(client, profile):
    assert client.put("/api/profile", json=profile).status_code == 200
    response = client.post(
        "/api/documents",
        files={"file": ("resume.pdf", PDF, "application/pdf")},
        data={"kind": "resume", "default": "true"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def start(client, slug, resume=None):
    result = client.post(
        "/api/applications", json={"url": f"http://127.0.0.1:8001/mock/jobs/{slug}", "resume_id": resume}
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


def answer(client, app_id, text, remember=True):
    result = client.post(f"/api/applications/{app_id}/answer", json={"text": text, "remember": remember})
    assert result.status_code == 200, result.text


def test_complete_reuse_review_upload_and_duplicate(client, portal, profile_data):
    doc = prepare(client, profile_data)
    slug = "flow-" + uuid4().hex[:8]
    app_id = start(client, slug)
    state = await_status(client, app_id, "waiting_answer")
    assert "May through August 2027" in state["pending"]["label"]
    assert any(x["answer"] == "Test" and x["source"] == "profile" for x in state["answers"])
    assert any(x.get("document_id") == doc for x in state["answers"])
    assert sum(x["label"] == "College or university" for x in state["answers"]) == 2
    assert any(x["label"].startswith("Will you") and x["answer"] == "No" for x in state["answers"])
    assert client.post(f"/api/applications/{app_id}/action", json={"action": "pause"}).status_code == 200
    assert client.get(f"/api/applications/{app_id}").json()["status"] == "paused"
    time.sleep(0.2)
    assert client.post(f"/api/applications/{app_id}/action", json={"action": "continue"}).status_code == 200
    answer(client, app_id, "Yes")
    state = await_status(client, app_id, "waiting_answer")
    assert "learn" in state["pending"]["label"]
    answer(client, app_id, "I would like to learn collaborative software development.")
    state = await_status(client, app_id, "review")
    assert not any("Gender" in x["label"] for x in state["answers"])
    # Final submission gate and revision protection.
    assert (
        client.post(
            f"/api/applications/{app_id}/approve", json={"revision": state["revision"] - 1, "approved": True}
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/applications/{app_id}/approve", json={"revision": state["revision"], "approved": False}
        ).status_code
        == 422
    )
    time.sleep(0.3)
    assert client.get(f"/api/applications/{app_id}").json()["status"] == "review"
    assert (
        client.post(
            f"/api/applications/{app_id}/approve", json={"revision": state["revision"], "approved": True}
        ).status_code
        == 200
    )
    state = await_status(client, app_id, "submitted")
    assert "Confirmation NS-" in state["confirmation"]
    assert state["submitted_at"]
    duplicate = client.post(
        "/api/applications", json={"url": f"http://127.0.0.1:8001/mock/jobs/{slug}?source=another"}
    )
    assert duplicate.status_code == 409
    assert len(client.get("/api/memory").json()) == 2
    second = start(client, "reuse-" + uuid4().hex[:8])
    state = await_status(client, second, "review")
    assert any(
        x["label"].startswith("Are you available") and "approved for reuse" in x["explanation"]
        for x in state["answers"]
    )
    assert state["status"] == "review"
    assert client.post(f"/api/applications/{second}/action", json={"action": "stop"}).status_code == 200
    assert client.get(f"/api/applications/{second}").json()["status"] == "cancelled"


def test_review_edit_replays_and_confirmation(client, portal, profile_data):
    prepare(client, profile_data)
    client.post(
        "/api/memory",
        json={"question": "Are you available full-time from May through August 2027?", "answer": "Yes"},
    )
    client.post(
        "/api/memory",
        json={"question": "What would you like to learn during this internship?", "answer": "Testing."},
    )
    app_id = start(client, "edit-" + uuid4().hex[:8])
    state = await_status(client, app_id, "review")
    result = client.put(
        f"/api/applications/{app_id}/answers",
        json={"key": "first_name", "answer": "Edited", "group": "", "index": 0},
    )
    assert result.status_code == 200, result.text
    state = await_status(client, app_id, "review")
    assert next(x for x in state["answers"] if x["key"] == "first_name")["answer"] == "Edited"
    assert (
        client.post(
            f"/api/applications/{app_id}/approve", json={"revision": state["revision"], "approved": True}
        ).status_code
        == 200
    )
    assert await_status(client, app_id, "submitted")["confirmation"]


def test_non_internship_and_ambiguous_role(client, portal, profile_data):
    prepare(client, profile_data)
    app_id = start(client, "non-intern")
    state = await_status(client, app_id, "rejected")
    assert state["answers"] == []
    app_id = start(client, "ambiguous")
    state = await_status(client, app_id, "waiting_verification")
    assert state["answers"] == []
    answer(client, app_id, "No", False)
    assert await_status(client, app_id, "rejected")["answers"] == []


def test_malicious_content_does_not_expand_permissions(client, portal, profile_data):
    prepare(client, profile_data)
    app_id = start(client, "malicious")
    state = await_status(client, app_id, "waiting_answer")
    agent = __import__("backend.app.main", fromlist=["AGENTS"]).AGENTS[app_id]
    assert agent.controller.policy.verified
    assert len(agent.controller.policy.blocked) >= 3
    assert any(x["kind"] == "fetch" for x in agent.controller.policy.blocked)
    assert all("example.com" not in url for url in agent.controller.policy.allowed_pages)
    assert state["pending"]["label"].startswith("Are you available")
    assert client.post(f"/api/applications/{app_id}/action", json={"action": "stop"}).status_code == 200
    assert agent.controller.browser is None
