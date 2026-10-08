import asyncio
from dataclasses import asdict
from urllib.parse import urljoin
from datetime import datetime, timezone
from browser_agent.policy import WorkflowPolicy, PolicyError
from browser_agent.controller import BrowserController
from browser_agent.adapters import ADAPTERS
from browser_agent.validator import inspect_job
from browser_agent.resolver import AnswerResolver, Resolution
from backend.app.config import settings
from backend.app.ai import AIService
from backend.app.memory import get_profile, remember, SENSITIVE, APPLICATION_ONLY
from backend.app.tracker import get_application, update, log, save_answer
from database.session import session
from database.models import Application

TERMINAL = {"submitted", "cancelled", "rejected"}
TRANSITIONS = {
    "queued": {"verifying", "cancelled"},
    "verifying": {"waiting_verification", "filling", "rejected", "paused", "cancelled"},
    "waiting_verification": {"filling", "cancelled", "rejected", "paused"},
    "filling": {"waiting_answer", "manual", "review", "paused", "cancelled"},
    "waiting_answer": {"filling", "paused", "cancelled"},
    "manual": {"filling", "paused", "cancelled"},
    "review": {"submitting", "filling", "paused", "cancelled"},
    "submitting": {"submitted", "submission_unknown", "cancelled"},
    "paused": {"verifying", "filling", "waiting_answer", "review", "manual", "cancelled"},
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

    def state(self, status, **data):
        current = get_application(self.app_id).status
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
        self.task = asyncio.create_task(self.run())

    async def run(self):
        cfg = settings()
        app = get_application(self.app_id)
        try:
            self.state("verifying", error=None, pending=None, step=0)
            policy = await asyncio.wait_for(
                asyncio.to_thread(WorkflowPolicy, app.data["url"], cfg.enable_mock_portal), timeout=15
            )
            self.controller = BrowserController(policy, cfg.browser_headless)
            adapter = ADAPTERS[policy.platform]()
            log(
                self.app_id,
                "Opening an isolated browser to verify the role. Browser preview refreshes after each action.",
            )
            await self.controller.start()
            await self.controller.navigate(policy.initial_url)
            await self.controller.page.wait_for_timeout(500)
            verdict = await inspect_job(self.controller.page, adapter)
            await self.controller.snapshot()
            self.state("verifying", job=asdict(verdict), platform=policy.platform)
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
            self.state("filling", pending=None)
            log(
                self.app_id,
                f"Verified {verdict.title} at {verdict.company}. I’ll use only your profile and approved answers.",
            )
            link = await adapter.apply_link(self.controller.page)
            if link:
                target = policy.permit_apply_link(urljoin(self.controller.page.url, link))
                await self.controller.navigate(target)
            for step in range(30):
                await self.checkpoint()
                update(self.app_id, step=step)
                if await adapter.manual_challenge(self.controller.page):
                    self.state("manual", pending=None)
                    log(
                        self.app_id,
                        "Login or CAPTCHA needs your attention. Complete it in the dedicated browser and press Continue. No password is collected by this app.",
                    )
                    self.gate.clear()
                    await self.checkpoint()
                policy.interaction(self.controller.page.url)
                await adapter.expand_records(self.controller.page, get_profile())
                fields = await self.controller.inspect()
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
                        except (ValueError, PolicyError):
                            log(
                                self.app_id,
                                "The answer did not match this control. Please choose an available option or document.",
                            )
                            resolution = await self.ask(field)
                    save_answer(self.app_id, field, resolution)
                    await self.controller.snapshot()
                await self.checkpoint()
                next_button = await adapter.next_button(self.controller.page)
                if next_button:
                    before = await self.controller.page.locator("body").inner_text()
                    await self.controller.click_next(next_button)
                    await self.controller.page.wait_for_timeout(350)
                    after = await self.controller.page.locator("body").inner_text()
                    if after == before:
                        self.state("manual")
                        log(
                            self.app_id,
                            "The form did not advance. Please resolve its validation in the browser or edit answers, then Continue.",
                        )
                        self.gate.clear()
                        await self.checkpoint()
                    await self.controller.snapshot()
                    continue
                submit = await adapter.submit_button(self.controller.page)
                if submit:
                    self.state("review", pending=None, warnings=[x["reason"] for x in policy.blocked[-5:]])
                    log(
                        self.app_id,
                        "The application is ready for your review. Check every answer and document. Submission is blocked until you explicitly approve this revision.",
                    )
                    await self.controller.snapshot()
                    await self.approval.wait()
                    await self.checkpoint()
                    # Approval endpoint transitions under lock; network permit expires after the attempt.
                    await self.controller.submit(submit)
                    confirmation = None
                    for _ in range(20):
                        await asyncio.sleep(0.25)
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
                self.state("manual")
                log(
                    self.app_id,
                    "This employer’s next control or network endpoint is unsupported. I paused safely. Use the browser within this requisition and Continue, or cancel.",
                )
                self.gate.clear()
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
                        error=f"Agent paused ({type(exc).__name__}). Browser or portal operation could not safely continue.",
                    )
                log(
                    self.app_id,
                    "The browser operation could not safely continue. Your recorded answers are saved. Resume will reconstruct the form when supported.",
                )
        finally:
            if self.controller and get_application(self.app_id).status in ("cancelled", "rejected"):
                await self.controller.close()

    async def answer(self, text, save=False, sensitive_permission=False, document_id=None, origin="user"):
        async with self.lock:
            app = get_application(self.app_id)
            state = self.prior_state if app.status == "paused" else app.status
            if state not in ("waiting_answer", "waiting_verification") or self.reply.full():
                raise ValueError("There is no active question awaiting an answer.")
            if not text.strip() and not document_id:
                raise ValueError("Enter an answer or select a document.")
            if state == "waiting_verification":
                if text.casefold() not in ("yes", "no"):
                    raise ValueError("Choose Yes or No to verify this role.")
            elif self.pending:
                if self.pending.options and text not in self.pending.options:
                    raise ValueError("Choose one of the available options.")
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
            if app.status == "paused" and self.prior_state and self.task and not self.task.done():
                self.state(self.prior_state)
                self.gate.set()
            elif app.status == "manual":
                self.state("filling")
                self.gate.set()
            elif app.status == "paused" and (not self.task or self.task.done()):
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

    async def approve(self, revision):
        async with self.lock:
            app = get_application(self.app_id)
            if app.status != "review" or app.revision != revision:
                raise ValueError("Review changed or is incomplete. Refresh and approve the current revision.")
            if not self.controller or not self.task or self.task.done():
                raise ValueError("Browser disconnected. Resume and review again.")
            self.state("submitting", approved_revision=revision)
            self.controller.policy.submission_permit = True
            self.approval.set()

    async def stop(self):
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
