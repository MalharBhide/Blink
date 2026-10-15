import asyncio
from dataclasses import asdict
from urllib.parse import urljoin
from datetime import datetime, timezone
from browser_agent.policy import WorkflowPolicy, PolicyError, canonical, platform_for
from browser_agent.controller import BrowserController
from browser_agent.adapters import ADAPTERS
from browser_agent.validator import inspect_job, application_matches_job
from browser_agent.resolver import AnswerResolver, Resolution
from backend.app.config import settings
from backend.app.ai import AIService
from backend.app.memory import get_profile, remember, SENSITIVE, APPLICATION_ONLY
from backend.app.tracker import get_application, update, log, save_answer
from database.session import session
from database.models import Application
from sqlalchemy import select
from playwright.async_api import Error as PlaywrightError

TERMINAL = {"submitted", "cancelled", "rejected"}
TRANSITIONS = {
    "queued": {"verifying", "cancelled"},
    "rejected": {"paused"},
    "verifying": {"waiting_verification", "waiting_workflow", "filling", "rejected", "paused", "cancelled"},
    "waiting_verification": {"filling", "cancelled", "rejected", "paused"},
    "filling": {"waiting_answer", "waiting_workflow", "manual", "review", "paused", "cancelled", "rejected"},
    "waiting_workflow": {"verifying", "filling", "submitting", "paused", "cancelled"},
    "waiting_answer": {"filling", "paused", "cancelled"},
    "manual": {"filling", "paused", "cancelled"},
    "review": {"submitting", "filling", "paused", "cancelled"},
    "submitting": {"waiting_workflow", "submitted", "submission_unknown", "cancelled"},
    "paused": {"verifying", "filling", "waiting_answer", "waiting_workflow", "review", "manual", "cancelled"},
    "submission_unknown": {"cancelled"},
}


class AgentOrchestrator:
    def __init__(self, app_id):
        self.app_id = app_id
        self.ai = AIService()
        self.resolver = AnswerResolver(self.ai)
        self.controller = None
        self.task = None
        self.gate = asyncio.Event()
        self.gate.set()
        self.reply = asyncio.Queue(maxsize=1)
        self.lock = asyncio.Lock()
        self.prior_state = None
        self.approval = asyncio.Event()
        self.pending = None
        self.review_refresh = False

    def ensure_slot(self):
        with session() as db:
            other = db.scalar(
                select(Application).where(
                    Application.id != self.app_id,
                    Application.status.not_in(
                        ["submitted", "cancelled", "rejected", "paused", "submission_unknown"]
                    ),
                )
            )
            if other:
                raise ValueError("Pause or stop your current application before continuing another one.")

    def state(self, status, **data):
        current = get_application(self.app_id).status
        if (
            current == "paused"
            and not self.gate.is_set()
            and self.task
            and asyncio.current_task() is self.task
            and status
            not in ("paused", "cancelled", "rejected", "submitted", "submission_unknown", "submitting")
        ):
            # An in-flight operation may finish after Pause. Keep the UI paused
            # and remember where Continue should resume, rather than hiding it.
            self.prior_state = status
            return update(self.app_id, **data)
        if status != current and status not in TRANSITIONS.get(current, set()):
            raise ValueError(f"Cannot transition from {current} to {status}.")
        return update(self.app_id, status, **data)

    async def checkpoint(self):
        await self.gate.wait()
        if get_application(self.app_id).status == "cancelled":
            raise asyncio.CancelledError()

    async def ask(self, field, suggestion=None):
        self.pending = field
        self.state(
            "waiting_answer", pending=field.dict(), suggestion=suggestion.answer if suggestion else None
        )
        log(
            self.app_id,
            f"This application asks “{field.label}”. Please choose one of the shown options or answer in chat. You can save it for reuse explicitly; otherwise it stays with this application.",
        )
        answer = await self.reply.get()
        await self.checkpoint()
        self.pending = None
        self.state("filling", pending=None, suggestion=None)
        return answer

    async def start(self):
        if self.task and not self.task.done():
            raise ValueError("This application is already running.")
        self.ensure_slot()
        # Reserve the single active slot before yielding to browser startup.
        self.state("verifying")
        self.reply = asyncio.Queue(maxsize=1)
        self.pending = None
        self.prior_state = None
        self.review_refresh = False
        self.approval.clear()
        self.gate.set()
        self.task = asyncio.create_task(self.run())

    async def confirm_destination(self, policy, url, reason, *, submission=False):
        target = await asyncio.to_thread(policy.validate_destination, url)
        prior = get_application(self.app_id).status
        self.state(
            "waiting_workflow",
            pending={
                "kind": "workflow",
                "label": f"{reason}\n{target}\nIs this destination part of this internship application?",
                "options": ["Yes", "No"],
            },
        )
        log(
            self.app_id,
            "A new destination is blocked until you confirm its association with this internship. Only this exact URL can be approved; account and private-network destinations remain blocked.",
        )
        answer = await self.reply.get()
        await self.checkpoint()
        self.state(prior, pending=None)
        if answer.answer.casefold() != "yes":
            raise PolicyError("You declined this workflow destination.")
        policy.approve_destination(target, user_confirmed=True, submission=submission)
        # Stored only inside this encrypted application, never reusable across roles.
        item = get_application(self.app_id)
        approved = item.data.get("workflow_destinations", [])
        if {"url": target, "submission": submission} not in approved:
            update(self.app_id, workflow_destinations=[*approved, {"url": target, "submission": submission}])
        return target

    async def navigate_workflow(self, url):
        """Follow confirmed redirects one exact URL at a time, never an entire domain."""
        for _ in range(6):
            try:
                await self.controller.navigate(url)
                return
            except Exception:
                target = self.controller.pending_navigation
                if not target:
                    raise
                if canonical(target) in self.controller.policy.allowed_pages:
                    url = target
                else:
                    url = await self.confirm_destination(
                        self.controller.policy, target, "The link redirects to a new page."
                    )
        raise PolicyError("Too many workflow redirects; review the link manually.")

    async def run(self):
        cfg = settings()
        app = get_application(self.app_id)
        phase = "preparing the application"
        try:
            await self.checkpoint()
            self.state("verifying", error=None, pending=None, step=0)
            policy = await asyncio.wait_for(
                asyncio.to_thread(WorkflowPolicy, app.data["url"], cfg.enable_mock_portal), timeout=15
            )
            # These permissions came from the authenticated user's confirmation,
            # not from website content, and remain scoped to this application.
            destinations = app.data.get("workflow_destinations", [])
            for dest in destinations:
                if not dest["submission"]:
                    await asyncio.wait_for(
                        asyncio.to_thread(policy.approve_destination, dest["url"], user_confirmed=True),
                        timeout=15,
                    )
            self.controller = BrowserController(policy, cfg.browser_headless)
            adapter = ADAPTERS[policy.platform]()
            log(
                self.app_id,
                "Opening an isolated browser to verify the role. Browser preview refreshes after each action.",
            )
            phase = "starting the isolated browser"
            await self.controller.start()
            phase = "loading the approved page"
            await self.navigate_workflow(policy.verification_url)
            # An approved redirect selects the ATS adapter and its scoped public resource rules.
            detected = "mock" if policy.platform == "mock" else platform_for(self.controller.page.url)
            adapter = ADAPTERS[detected]()
            await self.controller.snapshot()
            phase = "waiting for the portal to render"
            rendered = await adapter.wait_ready(self.controller.page)
            await self.checkpoint()
            phase = "reading the job title"
            verdict = await inspect_job(self.controller.page, adapter)
            await self.controller.snapshot()
            self.state("verifying", job=asdict(verdict), platform=detected)
            if not verdict.title or not rendered:
                self.state(
                    "paused",
                    error="This portal did not expose a readable job title. Paste the employer's direct internship listing. The portal may be unavailable or need a resource this adapter does not yet support. No fields were filled.",
                )
                return
            if verdict.status == "rejected":
                self.state(
                    "rejected",
                    error="The job title does not identify an internship. No form interaction was permitted.",
                )
                log(self.app_id, "I could not verify an internship title, so this application was rejected.")
                return
            if verdict.status == "ambiguous":
                self.state(
                    "waiting_verification",
                    pending={
                        "kind": "verification",
                        "label": f"Is “{verdict.title}” an internship?",
                        "options": ["Yes", "No"],
                    },
                )
                log(
                    self.app_id,
                    "This title is ambiguous. Confirm that this specific role is an internship before I can interact with its form.",
                )
                answer = await self.reply.get()
                await self.checkpoint()
                if answer.answer.casefold() != "yes":
                    self.state("rejected", pending=None)
                    return
            policy.verified = True
            for dest in destinations:
                if dest["submission"]:
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            policy.approve_destination, dest["url"], user_confirmed=True, submission=True
                        ),
                        timeout=15,
                    )
            phase = "completing the application"
            self.state("filling", pending=None)
            log(
                self.app_id,
                f"Verified {verdict.title} at {verdict.company}. I’ll use only your profile and approved answers.",
            )
            link = await adapter.apply_link(self.controller.page)
            if link:
                target = canonical(urljoin(self.controller.page.url, link))
                if target not in policy.allowed_pages:
                    target = await self.confirm_destination(
                        policy, target, "Apply opens a new application page."
                    )
                policy.permit_apply_link(target)
                await self.navigate_workflow(target)
                adapter = ADAPTERS[
                    "mock" if policy.platform == "mock" else platform_for(self.controller.page.url)
                ]()
            else:
                entry = await adapter.apply_button(self.controller.page)
                if entry:
                    try:
                        await self.controller.click_apply(entry)
                    except Exception:
                        target = self.controller.pending_navigation
                        if not target:
                            raise
                        if canonical(target) not in policy.allowed_pages:
                            target = await self.confirm_destination(
                                policy, target, "Apply opens a new application page."
                            )
                        await self.navigate_workflow(target)
                    adapter = ADAPTERS[
                        "mock" if policy.platform == "mock" else platform_for(self.controller.page.url)
                    ]()
            await adapter.wait_ready(self.controller.page)
            page_index = 0
            for _ in range(60):
                await self.checkpoint()
                update(self.app_id, step=page_index)
                choice = await adapter.application_choice(self.controller.page)
                if choice:
                    try:
                        await self.controller.choose_application(choice)
                    except Exception:
                        target = self.controller.pending_navigation
                        if not target:
                            raise
                        if canonical(target) not in policy.allowed_pages:
                            target = await self.confirm_destination(
                                policy, target, "The manual application opens this job's application page."
                            )
                        await self.navigate_workflow(target)
                    await self.controller.page.wait_for_timeout(500)
                if await adapter.manual_challenge(self.controller.page):
                    await self.controller.snapshot()
                    self.gate.clear()
                    self.state("manual", pending=None)
                    log(
                        self.app_id,
                        adapter.manual_message,
                    )
                    await self.checkpoint()
                    continue  # Recheck the challenge before parsing or filling login fields.
                policy.interaction(self.controller.page.url)
                if policy.platform != "mock" and not await application_matches_job(
                    self.controller.page, adapter, verdict
                ):
                    self.state(
                        "rejected",
                        error="This page identifies a different or non-internship role. No further fields were filled.",
                    )
                    return
                await adapter.expand_records(self.controller.page, get_profile())
                fields = await self.controller.inspect(page_index)
                for field in fields:
                    await self.checkpoint()
                    resolution = await self.resolver.resolve(field, get_application(self.app_id))
                    if resolution is None and not field.required and not SENSITIVE.search(field.label):
                        continue
                    if SENSITIVE.search(field.label) and resolution is None and not field.required:
                        continue  # optional self-ID remains empty by default
                    if resolution is None or (resolution.source == "draft" and not resolution.reviewed):
                        resolution = await self.ask(field, resolution)
                    while True:
                        await self.checkpoint()
                        try:
                            if field.kind == "file":
                                await self.controller.upload(field, resolution.document_id)
                            else:
                                await self.controller.fill(field, resolution.answer)
                            break
                        except (ValueError, PolicyError, PlaywrightError):
                            log(
                                self.app_id,
                                "The answer did not match this control. Please choose an available option or document.",
                            )
                            resolution = await self.ask(field)
                    save_answer(self.app_id, field, resolution)
                    await self.controller.snapshot()
                await self.checkpoint()
                # Conditional questions may appear after a preceding answer.
                current_fields = await self.controller.inspect(page_index)
                completed = {
                    (x["key"], x.get("group", ""), x.get("index", 0), x.get("page", 0), x["label"])
                    for x in get_application(self.app_id).data.get("answers", [])
                }
                if any(
                    field.required
                    and (field.key, field.group, field.index, field.page, field.label) not in completed
                    for field in current_fields
                ):
                    continue
                invalid = await self.controller.invalid_fields(current_fields)
                if invalid:
                    field = invalid[0]
                    log(
                        self.app_id,
                        f"The portal needs a valid answer for “{field.label}”. Please check its format or available options.",
                    )
                    resolution = await self.ask(field)
                    try:
                        if field.kind == "file":
                            await self.controller.upload(field, resolution.document_id)
                        else:
                            await self.controller.fill(field, resolution.answer)
                        save_answer(self.app_id, field, resolution)
                    except (ValueError, PolicyError, PlaywrightError):
                        pass  # Ask again on the next pass; never advance an invalid form.
                    continue
                next_button = await adapter.next_button(self.controller.page)
                if next_button:
                    before = await self.controller.page.locator("body").inner_text()
                    before_url = self.controller.page.url
                    self.controller.pending_navigation = None
                    try:
                        await self.controller.click_next(next_button)
                    except Exception:
                        target = self.controller.pending_navigation
                        if not target:
                            raise
                        if canonical(target) not in policy.allowed_pages:
                            target = await self.confirm_destination(
                                policy, target, "The next application step opens a new page."
                            )
                        await self.navigate_workflow(target)
                        adapter = ADAPTERS[
                            "mock" if policy.platform == "mock" else platform_for(self.controller.page.url)
                        ]()
                    await self.controller.page.wait_for_timeout(350)
                    after = await self.controller.page.locator("body").inner_text()
                    if after != before or self.controller.page.url != before_url:
                        page_index += 1
                    else:
                        self.gate.clear()
                        self.state("manual")
                        log(
                            self.app_id,
                            "The form did not advance. Please resolve its validation in the browser or edit answers, then Continue.",
                        )
                        await self.checkpoint()
                    await self.controller.snapshot()
                    continue
                submit = await adapter.submit_button(self.controller.page)
                if submit:
                    form_target = await self.controller.submission_form(submit)
                    if policy.platform != "mock" and form_target:
                        action = canonical(form_target["url"])
                        if form_target["method"] != "POST":
                            raise PolicyError("This form does not use a supported POST submission.")
                        if (
                            action not in policy.allowed_pages
                            and (action, "POST") not in policy.submission_targets
                        ):
                            await self.confirm_destination(
                                policy,
                                action,
                                "This form sends your application to the following endpoint.",
                                submission=True,
                            )
                        policy.prepare_submission(self.controller.page.url, action, "POST")
                    # Do not accept a success message present before the approved attempt.
                    if await adapter.confirmation(self.controller.page):
                        raise PolicyError(
                            "A confirmation was already present before submission; verify this application manually."
                        )
                    update(
                        self.app_id,
                        submission_destination=canonical(form_target["url"]) if form_target else None,
                    )
                    self.state("review", pending=None, warnings=[x["reason"] for x in policy.blocked[-5:]])
                    log(
                        self.app_id,
                        "The application is ready for your review. Check every answer and document. Submission is blocked until you explicitly approve this revision.",
                    )
                    await self.controller.snapshot()
                    await self.approval.wait()
                    await self.checkpoint()
                    if self.review_refresh:
                        self.review_refresh = False
                        self.approval.clear()
                        continue
                    # Approval endpoint transitions under lock; network permit expires after the attempt.
                    await self.controller.validate_submission_form(submit, form_target)
                    policy.submission_permit = True
                    await self.controller.submit(submit)
                    confirmation = None
                    for _ in range(20):
                        await asyncio.sleep(0.25)
                        receipt = self.controller.pending_confirmation
                        if receipt:
                            self.controller.pending_confirmation = None
                            if canonical(receipt) not in policy.allowed_pages:
                                receipt = await self.confirm_destination(
                                    policy,
                                    receipt,
                                    "The portal returned a confirmation-page redirect after your approved submission.",
                                )
                            # Receipt redirects are read-only GET; never replay a POST.
                            await self.navigate_workflow(receipt)
                        status = self.controller.submission_response_status
                        if status and 200 <= status < 304:
                            confirmation = await adapter.confirmation(self.controller.page)
                        if confirmation:
                            break
                    policy.submission_permit = False
                    if confirmation:
                        self.state("submitted", confirmation=confirmation)
                        with session() as db:
                            row = db.get(Application, self.app_id)
                            row.submitted_at = datetime.now(timezone.utc)
                            db.commit()
                        log(self.app_id, "The portal confirmed that your application was received.")
                    else:
                        self.state(
                            "submission_unknown",
                            error="No recognized confirmation was found. Check the dedicated browser manually. Do not submit again until status is known.",
                        )
                        log(
                            self.app_id,
                            "I clicked Submit after approval, but could not verify receipt. This role stays locked against duplicate submission.",
                        )
                    await self.controller.snapshot()
                    return
                await self.controller.snapshot()
                self.gate.clear()
                self.state("manual")
                log(
                    self.app_id,
                    adapter.unsupported_message,
                )
                await self.checkpoint()
            self.state("paused", error="Step limit reached. Review this application manually.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status = get_application(self.app_id).status
            if status not in TERMINAL:
                # Avoid recording potentially sensitive Playwright call logs or DOM text.
                if status == "submitting":
                    self.state(
                        "submission_unknown",
                        error="Submission was interrupted. Verify receipt manually before doing anything else.",
                    )
                elif "paused" in TRANSITIONS.get(status, set()):
                    self.state(
                        "paused",
                        error=f"Agent paused: {exc}"
                        if isinstance(exc, PolicyError)
                        else f"Agent paused while {phase} ({type(exc).__name__}). Browser or portal operation could not safely continue.",
                    )
                log(
                    self.app_id,
                    "The browser operation could not safely continue. Your recorded answers are saved. Resume will reconstruct the form when supported.",
                )
        finally:
            if self.controller:
                self.controller.policy.submission_permit = False
            if self.controller and get_application(self.app_id).status in ("cancelled", "rejected"):
                await self.controller.close()

    async def answer(self, text, save=False, sensitive_permission=False, document_id=None, origin="user"):
        async with self.lock:
            app = get_application(self.app_id)
            state = self.prior_state if app.status == "paused" else app.status
            if (
                not self.task
                or self.task.done()
                or state not in ("waiting_answer", "waiting_verification", "waiting_workflow")
                or self.reply.full()
            ):
                raise ValueError("There is no active question awaiting an answer.")
            if not text.strip() and not document_id:
                raise ValueError("Enter an answer or select a document.")
            if state in ("waiting_verification", "waiting_workflow"):
                if origin != "user":
                    raise ValueError("Workflow and role confirmation must come explicitly from you.")
                if text.casefold() not in ("yes", "no"):
                    raise ValueError("Choose Yes or No to confirm this role or destination.")
            elif self.pending:
                if self.pending.kind == "file" and not document_id:
                    raise ValueError("Choose an uploaded document for this question.")
                choices = (
                    [value.strip() for value in text.split(";")]
                    if self.pending.kind == "select-multiple"
                    else [text]
                )
                if self.pending.options and any(value not in self.pending.options for value in choices):
                    raise ValueError("Choose from the available options.")
                if save and APPLICATION_ONLY.search(self.pending.label):
                    log(
                        self.app_id,
                        "This employer-specific answer will remain with this application; it will not be reused universally.",
                    )
                elif save:
                    remember(
                        self.pending.label,
                        text,
                        explicit_sensitive=sensitive_permission,
                        source=origin,
                        reviewed=origin == "draft",
                    )
            log(self.app_id, text if not document_id else "Selected a registered document.", "user")
            await self.reply.put(
                Resolution(
                    text,
                    origin,
                    "AI draft reviewed and explicitly accepted by you."
                    if origin == "draft"
                    else "Explicitly provided by you for this question.",
                    document_id,
                    reviewed=origin == "draft",
                )
            )

    async def pause(self):
        async with self.lock:
            app = get_application(self.app_id)
            if app.status in TERMINAL | {"submission_unknown", "submitting", "paused"}:
                raise ValueError("This application cannot be paused now.")
            self.prior_state = app.status
            self.gate.clear()
            self.state("paused")
            log(
                self.app_id,
                "Paused. The current browser action may finish; no subsequent action will start until Continue.",
            )

    async def resume(self):
        async with self.lock:
            app = get_application(self.app_id)
            self.ensure_slot()
            if app.status == "paused" and self.prior_state and self.task and not self.task.done():
                self.state(self.prior_state)
                self.gate.set()
            elif app.status == "manual":
                self.state("filling")
                self.gate.set()
            elif app.status == "paused" and (not self.task or self.task.done()):
                self.state("verifying")
                if self.controller:
                    await self.controller.close()
                self.prior_state = None
                self.gate.set()
                self.approval.clear()
                await self.start()
            else:
                raise ValueError("Only paused or manual applications can continue.")
            log(
                self.app_id,
                "Continuing with saved answers. Login and CAPTCHA may need to be repeated after a restart.",
            )

    async def retry(self):
        async with self.lock:
            app = get_application(self.app_id)
            if app.status != "rejected" or (self.task and not self.task.done()):
                raise ValueError("Only a finished rejected attempt can be checked again.")
            if self.controller:
                await self.controller.close()
            with session() as db:
                other = db.scalar(
                    select(Application).where(
                        Application.id != self.app_id,
                        Application.status.not_in(
                            ["submitted", "rejected", "cancelled", "paused", "submission_unknown"]
                        ),
                    )
                )
                if other:
                    raise ValueError(
                        "Pause or stop your current application before checking this link again."
                    )
            # Preserve prior attempt data in encrypted history; it does not
            # authorize the new run or supply automatically reused answers.
            previous = app.data.get("previous_attempts", [])
            previous.append(
                {
                    "job": app.data.get("job"),
                    "answers": app.data.get("answers", []),
                    "warnings": app.data.get("warnings", []),
                    "error": app.data.get("error"),
                    "revision": app.revision,
                }
            )
            # Revalidate from the listing; no earlier submission or workflow
            # permission is carried into this new verification attempt.
            self.state(
                "paused",
                previous_attempts=previous,
                pending=None,
                answers=[],
                warnings=[],
                job=None,
                workflow_destinations=[],
                approved_revision=None,
            )
            self.prior_state = None
            self.approval.clear()
            self.gate.set()
            log(self.app_id, "Checking the original listing again with fresh verification and permissions.")
            await self.start()

    async def approve(self, revision):
        async with self.lock:
            app = get_application(self.app_id)
            if app.status != "review" or app.revision != revision:
                raise ValueError("Review changed or is incomplete. Refresh and approve the current revision.")
            if not self.controller or not self.task or self.task.done():
                raise ValueError("Browser disconnected. Resume and review again.")
            self.state("submitting", approved_revision=revision)
            self.approval.set()

    async def stop(self):
        # Stop new network actions immediately, even if an edit owns the lock.
        if get_application(self.app_id).status != "submitted":
            if self.controller:
                self.controller.policy.stopped = True
            if self.task and not self.task.done():
                self.task.cancel()
        async with self.lock:
            app = get_application(self.app_id)
            if app.status == "submitted":
                raise ValueError("Already submitted. It cannot be undone by stopping.")
            self.state("cancelled", pending=None)
            if self.controller:
                self.controller.policy.stopped = True
            if self.task:
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
            if self.controller:
                await self.controller.stop()
            log(self.app_id, "Stopped. The browser context is closed and further requests are blocked.")
