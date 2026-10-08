"""Public portal contracts reproduced locally; never sends data to employers."""

from urllib.parse import urlencode
import json
from types import SimpleNamespace
import pytest
from playwright.async_api import async_playwright
from browser_agent.policy import WorkflowPolicy, PolicyError, job_key, platform_for
from browser_agent.controller import BrowserController
from browser_agent.adapters import WorkdayAdapter, AvatureAdapter, BaseAdapter
from browser_agent.validator import inspect_job

WORKDAY = "https://example.wd503.myworkdayjobs.com/en-US/Careers/details/Data-Science-Intern_R29251"
ORACLE = "https://careers.example.test/hcmUI/CandidateExperience/en/sites/careers/job/299978/apply/email"
AVATURE = "https://example.avature.net/en_US/careers/JobDetail/195341"


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr("browser_agent.policy.public_host", lambda _: None)
    monkeypatch.setattr("browser_agent.controller.public_host", lambda _: None)


def test_platforms_verify_listing_before_application(public_dns):
    assert platform_for(WORKDAY) == "workday"
    assert WorkflowPolicy(WORKDAY + "/apply/applyManually").verification_url == WORKDAY
    oracle = WorkflowPolicy(ORACLE)
    assert oracle.verification_url == ORACLE.removesuffix("/apply/email")
    assert job_key(ORACLE) == job_key(oracle.verification_url)
    assert job_key(WORKDAY) == job_key(WORKDAY + "/apply/applyManually")
    avature = WorkflowPolicy(AVATURE)
    assert avature.job_login_url == "https://example.avature.net/en_US/careers/Login?jobId=195341"
    assert job_key(avature.job_login_url) == job_key(AVATURE)
    assert WorkflowPolicy(avature.job_login_url).verification_url == AVATURE
    with pytest.raises(PolicyError):
        avature.navigation(avature.job_login_url)
    avature.verified = True
    avature.navigation(avature.job_login_url)
    for url in (
        "https://example.avature.net/en_US/careers/Login",
        avature.job_login_url + "&next=/account",
        "https://example.avature.net/en_US/careers/account",
    ):
        with pytest.raises(PolicyError):
            avature.validate_destination(url)
    assert not avature.request_allowed(avature.job_login_url.replace("195341", "195342"), "document")
    assert not avature.request_allowed(avature.job_login_url, "document", "POST")


def test_workday_assets_and_metadata_never_grant_accounts_or_other_jobs(public_dns):
    p = WorkflowPolicy(WORKDAY)
    base = "https://wd503.myworkday.com/wday/asset/candidate-experience-jobs/"
    for path in ("compiled-lang/generic/en-US.json", "2026.40.17/compiled-lang/generic/en-US.json"):
        assert p.request_allowed(base + path, "fetch")
        assert p.static_redirect(base + path, "fetch")
        assert not p.request_allowed(base + path + "?email=secret", "fetch")
    assert p.request_allowed(
        base.replace("candidate-experience-jobs", "candidate-experience-apply-flow")
        + "2026.40.17/compiled-lang/cxs_apply_flow/en-US.json",
        "fetch",
    )
    assert not p.request_allowed(base + "account/profile.json", "fetch")
    info = "https://example.wd503.myworkdayjobs.com/wday/calypso/cxs/jobdetails/example/job/Data-Science-Intern_R29251/info"
    assert p.request_allowed(info, "fetch")
    assert not p.request_allowed(info.replace("R29251", "R29252"), "fetch")
    assert not p.request_allowed(info, "fetch", "POST")
    assert not p.request_allowed(
        base.replace("https://wd503.myworkday.com", "https://wd503.myworkday.com:444") + "x.js", "script"
    )
    api = "https://example.wd503.myworkdayjobs.com/wday/cxs/example/Careers/"
    for path in ("approot", "job/Data-Science-Intern_R29251", "sidebar/Data-Science-Intern_R29251"):
        assert p.request_allowed(api + path, "fetch")
        assert not p.request_allowed(api + path, "fetch", "POST")
    for path in ("userprofile", "jobs", "job/Senior-Engineer_R29252", "sidebar/Other-Intern_R29253"):
        assert not p.request_allowed(api + path, "fetch")


def test_oracle_only_exact_public_requisition_reads(public_dns):
    p = WorkflowPolicy(ORACLE)
    p.configure_oracle_site("CX_1001")
    base = "https://careers.example.test/hcmRestApi/resources/latest/"
    query = {
        "expand": "locations,organization",
        "onlyData": "true",
        "finder": 'ById;Id="299978",siteNumber=CX_1001',
    }
    url = base + "recruitingCEJobRequisitionDetails?" + urlencode(query)
    assert p.request_allowed(url, "fetch")
    for bad in (url.replace("299978", "299979"), url.replace("CX_1001", "CX_1002"), url + "&finder=all"):
        assert not p.request_allowed(bad, "fetch")
    assert not p.request_allowed(url, "fetch", "POST")
    assert not p.request_allowed(base + "recruitingCEUserSettings/private", "fetch")
    assert not p.request_allowed(base + "recruitingCEJobRequisitions?finder=all", "fetch")
    p.configure_oracle_site("../../account")
    assert p.oracle_site == "CX_1001"


async def test_translation_redirects_checked_every_hop(public_dns):
    p = WorkflowPolicy(WORKDAY)
    c = BrowserController(p)
    source = (
        "https://wd503.myworkday.com/wday/asset/candidate-experience-jobs/compiled-lang/generic/en-US.json"
    )
    target = source.replace("/compiled-lang/", "/2026.40.17/compiled-lang/")
    events = []

    class Route:
        request = SimpleNamespace(url=source, resource_type="fetch", method="GET", headers={})
        destination = target

        async def fetch(self, **kwargs):
            events.append(kwargs.get("url", source))
            return SimpleNamespace(
                status=307 if "url" not in kwargs else 200,
                headers={"location": self.destination} if "url" not in kwargs else {},
            )

        async def fulfill(self, **kwargs):
            events.append("fulfilled")

        async def abort(self, reason):
            events.append("blocked")

    await c._guard_request(Route())
    assert events == [source, target, "fulfilled"]
    events.clear()
    unsafe = Route()
    unsafe.destination = "https://attacker.test/account/profile"
    await c._guard_request(unsafe)
    assert events == [source, "blocked"]
    assert not c.pending_navigation  # API redirects do not acquire navigation permission.


async def test_delayed_rendering_titles_and_application_choice(public_dns):
    p = WorkflowPolicy(WORKDAY)
    p.verified = True
    c = BrowserController(p, headless=True)
    await c.start()
    try:
        # All public requests fulfilled locally only after production policy.
        async def fixture(route):
            assert p.request_allowed(route.request.url, route.request.resource_type, route.request.method)
            meta = json.dumps({"@type": "JobPosting", "title": "Data Science Intern &amp; Research"})
            await route.fulfill(
                body=f"""<script type="application/ld+json">{meta}</script>
              <h1>Career site</h1><input type="password" hidden>
              <script>setTimeout(()=>{{document.body.insertAdjacentHTML('beforeend',
              '<h2 data-automation-id="jobPostingHeader">Data Science Intern &amp; Research</h2>'+
              '<div role="button" tabindex="0" aria-label="Apply" onclick="show()">Apply</div>');}},500);
              function show(){{document.body.insertAdjacentHTML('beforeend',
              '<div role="dialog"><div role="button" tabindex="0" onclick="document.body.innerHTML=\\\'<h1>Sign In</h1><input type=password>\\\'">Apply Manually</div></div>');}}
              </script>""",
                content_type="text/html",
            )

        await c.context.unroute("**/*", c._route)
        await c.context.route("**/*", fixture)
        await c.navigate(WORKDAY)
        adapter = WorkdayAdapter()
        assert not await adapter.manual_challenge(c.page)  # hidden login is not a challenge
        assert await adapter.wait_ready(c.page, timeout=3)
        assert await adapter.title(c.page) == "Data Science Intern & Research"
        assert await adapter.apply_link(c.page) is None
        await c.click_apply(await adapter.apply_button(c.page))
        await c.choose_application(await adapter.application_choice(c.page))
        assert await adapter.manual_challenge(c.page)
        with pytest.raises(PolicyError):
            await c.choose_application(c.page.locator("input"))
    finally:
        await c.close()


async def test_avature_job_title_not_site_header():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content(
            '<div data-job-company>Example</div><header><h1>Koch Home Page</h1></header><main><article class="article__header"><h2 class="article__header__text__title">Data Science Internship</h2></article></main>'
        )
        verdict = await inspect_job(page, AvatureAdapter())
        assert verdict.title == "Data Science Internship"
        assert verdict.status == "internship"
        assert await BaseAdapter().wait_ready(page, timeout=1)
        await page.set_content(
            '<script type="application/ld+json">{"@type":"JobPosting","title":"Data Science Internship"}</script><div data-job-company>Example</div><header><h1>Koch Home Page</h1></header><main><article class="article__header"><h2 class="article__header__text__title">Senior Data Scientist</h2></article></main>'
        )
        assert (await inspect_job(page, AvatureAdapter())).status == "rejected"
        await browser.close()


@pytest.fixture
def dynamic_workday(public_dns, monkeypatch):
    """Employer-independent SPA fixture, served via the real request guard."""
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
                    events.append(("blocked", request.method, request.url))
                    await route.abort(reason)

                async def fetch(self, **kwargs):
                    events.append(("allowed", request.method, request.url))
                    if request.url.endswith("/apply/applyManually"):
                        body = "<h1>Sign In</h1><form method=post><label>Email<input type=email></label><label>Password<input type=password></label><button>Sign In</button></form>"
                    else:
                        body = r"""<h1>Career site</h1><script>setTimeout(()=>{document.body.insertAdjacentHTML('beforeend',
                          '<h2 data-automation-id="jobPostingHeader">Data Science Intern</h2>'+
                          '<div role="button" tabindex="0" onclick="show()">Apply</div>');},400);
                          function show(){document.body.insertAdjacentHTML('beforeend',
                          '<div role="dialog"><div role="button" tabindex="0" onclick="location.href=\'/en-US/Careers/job/City/Data-Science-Intern_R29251/apply/applyManually\'">Apply Manually</div></div>');}
                          </script>"""
                    return SimpleNamespace(status=200, headers={"content-type": "text/html"}, body=body)

                async def fulfill(self, *, response):
                    await route.fulfill(status=response.status, headers=response.headers, body=response.body)

            await controller._route(Transport())

        await controller.context.route("**/*", fixture)

    monkeypatch.setattr(BrowserController, "start", start)
    return events


def test_real_orchestrator_workday_entry_and_manual_gate(client, profile_data, dynamic_workday):
    from test_agent_flow import prepare, answer
    from conftest import await_status
    from backend.app.main import AGENTS

    prepare(client, profile_data)
    result = client.post("/api/applications", json={"url": WORKDAY})
    assert result.status_code == 201, result.text
    app_id = result.json()["id"]
    state = await_status(client, app_id, "waiting_workflow")
    assert "/apply/applyManually" in state["pending"]["label"]
    assert not state["answers"]
    answer(client, app_id, "Yes", remember=False)
    state = await_status(client, app_id, "manual")
    assert state["platform"] == "workday"
    assert not state["answers"]
    assert AGENTS[app_id].controller.screenshot
    previous_step = state["step"]
    assert client.post(f"/api/applications/{app_id}/action", json={"action": "continue"}).status_code == 200
    state = await_status(client, app_id, "manual")
    assert state["step"] > previous_step
    assert not state["answers"]  # Continue cannot turn an unfinished login into profile filling.
    assert all(method == "GET" for _, method, _ in dynamic_workday)
    assert (
        client.post(
            f"/api/applications/{app_id}/approve", json={"revision": state["revision"], "approved": True}
        ).status_code
        == 400
    )
    assert client.post(f"/api/applications/{app_id}/action", json={"action": "stop"}).status_code == 200


def test_retry_preserves_history_and_cannot_retry_a_submission(client, profile_data, dynamic_workday):
    from uuid import uuid4
    from database.session import session
    from database.models import Application
    from conftest import await_status
    from backend.app.tracker import get_application
    from test_agent_flow import prepare

    prepare(client, profile_data)
    app_id = str(uuid4())
    old_answers = [{"label": "Availability", "answer": "May 2027", "key": "availability"}]
    with session() as db:
        db.add(
            Application(
                id=app_id,
                status="rejected",
                revision=7,
                job_key=job_key(WORKDAY),
                data={
                    "url": WORKDAY,
                    "answers": old_answers,
                    "warnings": ["Prior warning"],
                    "job": {"title": "Career site"},
                    "workflow_destinations": [],
                },
            )
        )
        db.commit()
    result = client.post(f"/api/applications/{app_id}/action", json={"action": "retry"})
    assert result.status_code == 200, result.text
    state = await_status(client, app_id, "waiting_workflow")
    saved = get_application(app_id).data["previous_attempts"][0]
    assert saved["answers"] == old_answers
    assert saved["warnings"] == ["Prior warning"]
    assert not state["answers"]
    assert client.post(f"/api/applications/{app_id}/action", json={"action": "retry"}).status_code == 400
    assert client.post(f"/api/applications/{app_id}/action", json={"action": "stop"}).status_code == 200
    from backend.app.tracker import update

    update(app_id, "submitted")
    assert client.post(f"/api/applications/{app_id}/action", json={"action": "retry"}).status_code == 400


def test_duplicate_identity_covers_legacy_generic_classification(client, profile_data, public_dns):
    from uuid import uuid4
    from database.session import session
    from database.models import Application
    from test_agent_flow import prepare

    prepare(client, profile_data)
    app_id = str(uuid4())
    with session() as db:
        db.add(
            Application(
                id=app_id,
                status="paused",
                revision=0,
                job_key="old-generic-identity",
                data={"url": ORACLE, "answers": []},
            )
        )
        db.commit()
    result = client.post("/api/applications", json={"url": ORACLE.removesuffix("/apply/email")})
    assert result.status_code == 409
    assert result.json()["detail"]["application_id"] == app_id


@pytest.mark.parametrize("destination", [WORKDAY, ORACLE, AVATURE])
def test_employer_transition_selects_portal_only_after_exact_approval(public_dns, destination):
    p = WorkflowPolicy("https://careers.example.test/position/123")
    with pytest.raises(PolicyError):
        p.activate_portal(destination)
    p.approve_destination(destination, user_confirmed=True)
    p.activate_portal(destination)
    if p.platform != "workday":
        if p.platform == "avature":
            assert p.validate_destination(p.job_login_url)
        assert not p.submission_permit
        return
    assert p.platform == "workday"
    assert p.request_allowed(
        "https://wd503.myworkday.com/wday/asset/candidate-experience-jobs/cx-jobs.min.js", "script"
    )
    assert not p.request_allowed(WORKDAY.replace("R29251", "R29252"), "document")
    assert not p.request_allowed("https://wd503.myworkday.com/account", "fetch")
    assert not p.submission_permit


@pytest.mark.parametrize("url", [WORKDAY, ORACLE, AVATURE])
def test_confirmation_cannot_switch_known_job_id(public_dns, url):
    p = WorkflowPolicy(url)
    p.verified = True
    different = url.replace("29251", "29252").replace("299978", "299979").replace("195341", "195342")
    with pytest.raises(PolicyError):
        p.approve_destination(different, user_confirmed=True)
    if p.platform == "avature":
        with pytest.raises(PolicyError):
            p.approve_destination(p.job_login_url.replace("195341", "195342"), user_confirmed=True)


async def test_approved_get_retries_only_internal_error_page_race(public_dns):
    from unittest.mock import AsyncMock
    from playwright.async_api import Error as PlaywrightError

    p = WorkflowPolicy(WORKDAY)
    c = BrowserController(p)
    c.page = SimpleNamespace(
        url=WORKDAY,
        goto=AsyncMock(side_effect=[PlaywrightError("interrupted by chrome-error://chromewebdata/"), None]),
    )
    await c.navigate(WORKDAY)
    assert c.page.goto.await_count == 2
    assert all(call.args == (WORKDAY,) for call in c.page.goto.await_args_list)
    assert not p.submission_permit
    c.page.goto = AsyncMock(side_effect=PlaywrightError("unrelated network error"))
    with pytest.raises(PlaywrightError):
        await c.navigate(WORKDAY)
    assert c.page.goto.await_count == 1


async def test_preview_error_is_nonfatal_and_clears_stale_image(public_dns):
    from unittest.mock import AsyncMock
    from playwright.async_api import Error as PlaywrightError

    p = WorkflowPolicy(WORKDAY)
    c = BrowserController(p)
    c.screenshot = b"previous-frame"
    c.page = SimpleNamespace(
        is_closed=lambda: False,
        screenshot=AsyncMock(side_effect=PlaywrightError("preview renderer unavailable")),
    )
    assert await c.snapshot() is None
    assert c.screenshot is None
    assert not p.stopped
    assert not p.submission_permit
    assert p.allowed_pages == WorkflowPolicy(WORKDAY).allowed_pages
