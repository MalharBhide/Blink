"""User-facing recovery regressions. All browser traffic uses local synthetic pages."""

from types import SimpleNamespace
from urllib.parse import parse_qs
import pytest
from backend.app.main import AGENTS
from backend.app.tracker import get_application, save_answer
from browser_agent.parser import Field, parse_form
from browser_agent.resolver import AnswerResolver, Resolution, profile_value
from browser_agent.controller import BrowserController
from browser_agent.policy import WorkflowPolicy
from backend.app.ai import AIService
from database.session import session
from database.models import Application
from conftest import await_status


def test_answers_with_reused_ids_keep_page_and_question_identity(client, profile_data):
    with session() as db:
        db.add(Application(id="pages", job_key="pages", status="filling", data={"answers": []}))
        db.commit()
    for page, label, value in ((0, "First question", "First"), (1, "Second question", "Second")):
        save_answer(
            "pages",
            Field("shared", label, "text", True, [], page=page),
            Resolution(value, "user", "Provided by user."),
        )
    answers = get_application("pages").data["answers"]
    assert len(answers) == 2
    assert {x["page"] for x in answers} == {0, 1}
    assert profile_value(Field("name", "Full name", "text", True, []), profile_data) == "Test Applicant"


async def test_resolver_does_not_replay_a_different_page_question(client):
    app = Application(
        id="replay",
        data={
            "answers": [
                {
                    "key": "shared",
                    "label": "First question",
                    "page": 0,
                    "answer": "First",
                    "source": "user",
                    "explanation": "Provided",
                }
            ]
        },
    )
    resolver = AnswerResolver(AIService())
    assert await resolver.resolve(Field("shared", "Second question", "text", True, [], page=1), app) is None


async def test_radio_and_repeated_controls_are_scoped_to_the_question():
    policy = WorkflowPolicy("http://127.0.0.1:8001/mock/jobs/controls", True)
    policy.verified = True
    controller = BrowserController(policy, headless=True)
    await controller.start()
    try:
        # No network requests; the exact synthetic page is supplied locally.
        await controller.context.route(
            "**/*",
            lambda route: route.fulfill(
                content_type="text/html",
                body="""
          <h1>Data Science Intern</h1>
          <fieldset><legend>First choice?</legend><label>Yes<input type=radio name=first value=1></label><label>No<input type=radio name=first value=0 required></label></fieldset>
          <div role=radiogroup aria-label="Second choice?"><label>Yes<input type=radio name=second value=1 required></label><label>No<input type=radio name=second value=0></label></div>
          <label>College or university<input name=school></label><label>College or university<input name=school></label>
          <label>Relocation country<select><option value="">Choose</option><option>United States</option></select></label>""",
            ),
        )
        await controller.navigate(policy.initial_url)
        fields = await parse_form(controller.page)
        first, second = fields[:2]
        assert first.label == "First choice?" and first.required
        assert second.label == "Second choice?" and second.required
        await controller.fill(first, "No")
        await controller.fill(second, "Yes")
        assert await controller.page.locator('input[name=first][value="0"]').is_checked()
        assert await controller.page.locator('input[name=second][value="1"]').is_checked()
        repeated = [f for f in fields if f.label == "College or university"]
        assert len(repeated) == 2 and repeated[0].key != repeated[1].key
        assert all(f.group == "unclassified_repeat" for f in repeated)
        await controller.fill(fields[-1], "united states")
        assert await controller.page.locator("select").input_value() == "United States"
    finally:
        await controller.close()


@pytest.fixture
def staged_portal(monkeypatch):
    """Two steps reuse an input ID, and the second reveals a conditional field."""
    original = BrowserController.start
    events = []

    async def start(controller):
        await original(controller)
        await controller.context.unroute("**/*", controller._route)

        async def fixture(route):
            request = route.request

            class Transport:
                def __init__(self):
                    self.request = request

                async def abort(self, reason):
                    await route.abort(reason)

                async def fetch(self, **kwargs):
                    events.append((request.method, request.url))
                    if request.method == "POST":
                        assert parse_qs(request.post_data)["shared"] == ["Edited second answer"]
                        body = "<div data-confirmation>Application received. Confirmation FLOW-42</div>"
                    else:
                        body = r"""<h1>Data Science Intern</h1><form method=post action="/mock/jobs/reliable/submit">
                          <div id=step><label>First question<input id=shared name=shared required pattern="[A-Z]{3}"></label>
                          <button type=button onclick="advance()">Next</button></div></form>
                          <script>function advance(){document.querySelector('#step').innerHTML=
                          '<label>Second question<input id="shared" name="shared" required oninput="reveal()"></label><button type="submit">Submit application</button>';}
                          function reveal(){if(!document.querySelector('#extra'))document.querySelector('#step').insertAdjacentHTML('beforeend','<label>Conditional question<input id="extra" name="extra" required></label>');}</script>"""
                    return SimpleNamespace(status=200, headers={"content-type": "text/html"}, body=body)

                async def fulfill(self, *, response):
                    await route.fulfill(status=response.status, headers=response.headers, body=response.body)

            await controller._route(Transport())

        await controller.context.route("**/*", fixture)

    monkeypatch.setattr(BrowserController, "start", start)
    return events


def test_missing_validation_conditional_review_edit_and_approval(client, staged_portal):
    url = "http://127.0.0.1:8001/mock/jobs/reliable"
    result = client.post("/api/applications", json={"url": url})
    assert result.status_code == 201, result.text
    app_id = result.json()["id"]

    def answer(value):
        result = client.post(f"/api/applications/{app_id}/answer", json={"text": value})
        assert result.status_code == 200, result.text

    state = await_status(client, app_id, "waiting_answer")
    assert state["pending"]["label"] == "First question"
    answer("bad-format")
    state = await_status(client, app_id, "waiting_answer")
    assert state["pending"]["label"] == "First question"
    answer("ABC")
    state = await_status(client, app_id, "waiting_answer")
    assert state["pending"]["label"] == "Second question"
    answer("Second answer")
    state = await_status(client, app_id, "waiting_answer")
    assert state["pending"]["label"] == "Conditional question"
    answer("Conditional answer")
    state = await_status(client, app_id, "review")
    assert len(state["answers"]) == 3
    assert not any(method == "POST" for method, _ in staged_portal)
    context = AGENTS[app_id].controller.context
    revision = state["revision"]
    result = client.put(
        f"/api/applications/{app_id}/answers",
        json={"key": "shared", "page": 1, "answer": "Edited second answer"},
    )
    assert result.status_code == 200, result.text
    state = await_status(client, app_id, "review")
    assert AGENTS[app_id].controller.context is context
    assert next(a for a in state["answers"] if a["page"] == 0)["answer"] == "ABC"
    assert (
        next(a for a in state["answers"] if a["label"] == "Second question")["answer"]
        == "Edited second answer"
    )
    assert (
        client.post(
            f"/api/applications/{app_id}/approve", json={"approved": True, "revision": revision}
        ).status_code
        == 400
    )
    assert not any(method == "POST" for method, _ in staged_portal)
    assert (
        client.post(
            f"/api/applications/{app_id}/approve", json={"approved": True, "revision": state["revision"]}
        ).status_code
        == 200
    )
    assert await_status(client, app_id, "submitted")["confirmation"]
    assert sum(method == "POST" for method, _ in staged_portal) == 1


def test_resume_conflict_and_duplicate_have_recoverable_existing_application(client, staged_portal):
    first = client.post("/api/applications", json={"url": "http://127.0.0.1:8001/mock/jobs/reliable"}).json()[
        "id"
    ]
    await_status(client, first, "waiting_answer")
    conflict = client.post("/api/applications", json={"url": "http://127.0.0.1:8001/mock/jobs/other"})
    assert conflict.status_code == 409 and conflict.json()["detail"]["application_id"] == first
    assert conflict.json()["detail"]["code"] == "application_busy"
    assert client.post(f"/api/applications/{first}/action", json={"action": "pause"}).status_code == 200
    second = client.post("/api/applications", json={"url": "http://127.0.0.1:8001/mock/jobs/other"}).json()[
        "id"
    ]
    await_status(client, second, "waiting_answer")
    assert client.post(f"/api/applications/{first}/action", json={"action": "continue"}).status_code == 400
    assert client.post(f"/api/applications/{second}/action", json={"action": "stop"}).status_code == 200
    assert client.post(f"/api/applications/{first}/action", json={"action": "continue"}).status_code == 200
    await_status(client, first, "waiting_answer")
    duplicate = client.post("/api/applications", json={"url": "http://127.0.0.1:8001/mock/jobs/reliable"})
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["code"] == "duplicate_application"
    assert duplicate.json()["detail"]["application_id"] == first
    assert client.post(f"/api/applications/{first}/action", json={"action": "stop"}).status_code == 200


def test_first_resume_default_and_private_download(client):
    doc = client.post(
        "/api/documents",
        files={"file": ("resume.pdf", b"%PDF-1.4\nSynthetic only", "application/pdf")},
        data={"kind": "resume"},
    ).json()
    assert doc["default"] is True
    response = client.get(f"/api/documents/{doc['id']}/download")
    assert response.status_code == 200 and response.content == b"%PDF-1.4\nSynthetic only"
    assert "attachment;" in response.headers["content-disposition"]
    client.headers.pop("Authorization")
    assert client.get(f"/api/documents/{doc['id']}/download").status_code == 401


async def test_pause_preserves_new_question_and_can_answer_before_continuing(client):
    import asyncio
    from browser_agent.orchestrator import AgentOrchestrator
    from backend.app.tracker import get_application

    with session() as db:
        db.add(Application(id="pause-race", job_key="pause-race", status="filling", data={"answers": []}))
        db.commit()
    agent = AgentOrchestrator("pause-race")
    started = asyncio.Event()

    async def worker():
        await started.wait()
        return await agent.ask(Field("question", "A question that appeared during Pause", "text", True, []))

    agent.task = asyncio.create_task(worker())
    await agent.pause()
    started.set()
    await asyncio.sleep(0.05)
    assert get_application("pause-race").status == "paused"
    assert agent.prior_state == "waiting_answer"
    await agent.answer("Explicit user answer")
    assert get_application("pause-race").status == "paused"
    await agent.resume()
    result = await asyncio.wait_for(agent.task, 2)
    assert result.answer == "Explicit user answer"
    assert get_application("pause-race").status == "filling"


async def test_general_preferences_do_not_answer_position_specific_availability(client, profile_data):
    profile_data["preferences"].update({"adult": "Yes", "full_time": "Yes", "remote": "No", "hours": "40"})
    assert client.put("/api/profile", json=profile_data).status_code == 200
    resolver = AnswerResolver(AIService())
    app = Application(id="preferences", data={"answers": []})
    for label, expected in (
        ("Are you at least 18 years old?", "Yes"),
        ("Are you available full-time?", "Yes"),
        ("How many hours per week can you work?", "40"),
    ):
        answer = await resolver.resolve(Field(label, label, "text", True, []), app)
        assert answer.answer == expected and answer.source == "profile"
    for label in (
        "Are you available full-time from May through August 2027?",
        "Are you willing to work in person in Seattle?",
        "Are you at least 21 years old?",
        "Will you require sponsorship in Canada?",
    ):
        assert await resolver.resolve(Field(label, label, "text", True, []), app) is None


def test_restart_clears_stale_question_but_preserves_answers(client):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.tracker import get_application

    with session() as db:
        db.add(
            Application(
                id="restart-paused",
                job_key="restart-paused",
                status="paused",
                data={
                    "answers": [{"key": "kept", "answer": "Explicit user answer"}],
                    "pending": {"label": "Old question"},
                    "suggestion": "Old draft",
                },
            )
        )
        db.commit()
    with TestClient(app):
        state = get_application("restart-paused")
        assert state.status == "paused"
        assert state.data["pending"] is None and state.data["suggestion"] is None
        assert state.data["answers"][0]["answer"] == "Explicit user answer"
        assert "Continue" in state.data["error"]
