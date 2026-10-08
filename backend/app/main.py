import asyncio
from contextlib import asynccontextmanager
import secrets
import re
import hmac
import time
import os
from pathlib import Path
from uuid import uuid4
from fastapi import (
    FastAPI,
    Request,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from alembic.config import Config
from alembic import command
from backend.app.config import settings, access_code
from backend.app.local_access import consume_launch_ticket
from backend.app.schemas import (
    ProfileInput,
    StartInput,
    AnswerInput,
    ActionInput,
    ApproveInput,
    EditInput,
    ChatInput,
    MemoryInput,
)
from backend.app.memory import get_profile, save_profile, remember, fingerprint
from backend.app.documents import create_document, list_documents, default_resume, MAX_SIZE
from backend.app.tracker import get_application, application_view, messages, log, update
from database.models import Application, Profile, Document, SavedAnswer
from database.session import session
from browser_agent.policy import canonical, job_key
from browser_agent.orchestrator import AgentOrchestrator
from browser_agent.resolver import Resolution
from browser_agent.parser import Field

TOKEN = secrets.token_urlsafe(32)
AGENTS: dict[str, AgentOrchestrator] = {}
LOCAL_SESSIONS: dict[str, float] = {}


@asynccontextmanager
async def lifespan(app):
    access_code()
    command.upgrade(Config("alembic.ini"), "head")
    with session() as db:
        if not db.get(Profile, 1):
            db.add(Profile(id=1, data={}))
        for item in db.scalars(select(Application)):
            if item.status == "submitting":
                item.status = "submission_unknown"
                item.data = {
                    **item.data,
                    "error": "Restart interrupted submission. Verify receipt manually; repeat submission is blocked.",
                }
            elif item.status not in ("submitted", "cancelled", "rejected", "submission_unknown", "paused"):
                item.status = "paused"
                item.data = {
                    **item.data,
                    "pending": None,
                    "error": "Server restarted. Continue to reconstruct using saved answers.",
                }
        db.commit()
    yield
    for agent in AGENTS.values():
        if agent.task and not agent.task.done():
            agent.task.cancel()
        if agent.controller:
            await agent.controller.close()


app = FastAPI(
    title="Blink",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    telemetry={
        "tracing": False,
        "metrics": False,
        "logs": False,
        "operation_spans": False,
        "auto_configure": False,
    },
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Local-Client",
        "X-Blink-Access",
        "X-Blink-Launch",
        "X-Blink-Session",
    ],
)


@app.middleware("http")
async def local_only(request, call_next):
    if request.client and request.client.host not in ("127.0.0.1", "::1", "testclient"):
        return JSONResponse({"detail": "This MVP accepts only local connections."}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin not in settings().origins:
        return JSONResponse({"detail": "Untrusted origin."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    return response


@app.exception_handler(ValueError)
async def bad_input(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def auth(request: Request):
    value = request.headers.get("authorization", "")
    if not secrets.compare_digest(value, "Bearer " + TOKEN):
        raise HTTPException(401, "Local session required.")


def agent_for(app_id):
    get_application(app_id)
    if app_id not in AGENTS:
        AGENTS[app_id] = AgentOrchestrator(app_id)
    return AGENTS[app_id]


def validate_doc(doc_id):
    if doc_id:
        with session() as db:
            if not db.get(Document, doc_id):
                raise ValueError("Select an uploaded document.")


@app.get("/api/health")
def health(challenge: str = ""):
    result = {"status": "ok", "service": "blink", "pid": os.getpid()}
    if re.fullmatch(r"[a-f0-9]{64}", challenge):
        # A launcher proves it reached the owner's Blink instance without transmitting their key.
        result["proof"] = hmac.digest(
            access_code().encode(), (challenge + ":" + str(os.getpid())).encode(), "sha256"
        ).hex()
    return result


def session_response(request: Request):
    now = time.monotonic()
    LOCAL_SESSIONS.pop(request.headers.get("x-blink-session", ""), None)
    for key, expiry in list(LOCAL_SESSIONS.items()):
        if expiry <= now:
            LOCAL_SESSIONS.pop(key, None)
    if len(LOCAL_SESSIONS) >= 64:
        LOCAL_SESSIONS.pop(next(iter(LOCAL_SESSIONS)))
    tab_session = secrets.token_urlsafe(32)
    LOCAL_SESSIONS[tab_session] = now + 8 * 60 * 60
    return {
        "token": TOKEN,
        "session": tab_session,
        "ai_enabled": bool(settings().openai_api_key),
        "model": settings().openai_model,
        "mock_enabled": settings().enable_mock_portal,
    }


def local_client(request: Request):
    if request.headers.get("x-local-client") != "internship-ui":
        raise HTTPException(403, "Use the local application UI.")


@app.get("/api/session")
def bootstrap(request: Request):
    local_client(request)
    supplied = request.headers.get("x-blink-access", "")
    valid_session = LOCAL_SESSIONS.get(request.headers.get("x-blink-session", ""), 0) > time.monotonic()
    if not (secrets.compare_digest(supplied, access_code()) or (not supplied and valid_session)):
        raise HTTPException(403, "Open Blink with the launcher or enter your private access code.")
    return session_response(request)


@app.post("/api/session/launch")
def launch_session(request: Request):
    local_client(request)
    if not consume_launch_ticket(request.headers.get("x-blink-launch", "")):
        raise HTTPException(
            403, "This opening link expired or was already used. Open Blink with the launcher again."
        )
    return session_response(request)


@app.delete("/api/session", dependencies=[Depends(auth)])
def lock_workspace(request: Request):
    LOCAL_SESSIONS.pop(request.headers.get("x-blink-session", ""), None)
    return {"locked": True}


@app.get("/api/profile", dependencies=[Depends(auth)])
def profile():
    return get_profile()


@app.put("/api/profile", dependencies=[Depends(auth)])
def put_profile(body: ProfileInput):
    return save_profile(body.model_dump())


@app.get("/api/documents", dependencies=[Depends(auth)])
def documents():
    return list_documents()


@app.post("/api/documents", dependencies=[Depends(auth)])
async def upload(file: UploadFile = File(...), kind: str = Form("resume"), default: bool = Form(False)):
    content = await file.read(MAX_SIZE + 1)
    return create_document(file.filename or "document", content, kind, default)


@app.put("/api/documents/{doc_id}/default", dependencies=[Depends(auth)])
def set_default(doc_id: str):
    with session() as db:
        chosen = db.get(Document, doc_id)
        if not chosen or chosen.data["kind"] != "resume":
            raise ValueError("Choose a resume.")
        for doc in db.scalars(select(Document)):
            doc.data = {**doc.data, "default": doc.id == doc_id}
        db.commit()
    return list_documents()


@app.delete("/api/documents/{doc_id}", dependencies=[Depends(auth)])
def delete_doc(doc_id: str):
    with session() as db:
        doc = db.get(Document, doc_id)
        if not doc:
            raise HTTPException(404)
        db.delete(doc)
        db.commit()
        (settings().data_dir / "documents" / doc.id).unlink(missing_ok=True)
    return {"deleted": True}


@app.get("/api/memory", dependencies=[Depends(auth)])
def memory():
    with session() as db:
        return [{"id": x.id, **x.data} for x in db.scalars(select(SavedAnswer))]


@app.post("/api/memory", dependencies=[Depends(auth)])
def create_memory(body: MemoryInput):
    return remember(body.question, body.answer, explicit_sensitive=body.sensitive_permission)


@app.put("/api/memory/{memory_id}", dependencies=[Depends(auth)])
def edit_memory(memory_id: str, body: MemoryInput):
    with session() as db:
        item = db.get(SavedAnswer, memory_id)
        if not item:
            raise HTTPException(404)
        if item.data["question"] != body.question:
            raise ValueError("Delete and recreate memory to change its question.")
    return remember(body.question, body.answer, explicit_sensitive=body.sensitive_permission)


@app.delete("/api/memory/{memory_id}", dependencies=[Depends(auth)])
def forget(memory_id: str):
    with session() as db:
        item = db.get(SavedAnswer, memory_id)
        if item:
            db.delete(item)
            db.commit()
    return {"deleted": True}


@app.get("/api/applications", dependencies=[Depends(auth)])
def applications():
    with session() as db:
        return [
            application_view(x)
            for x in db.scalars(select(Application).order_by(Application.created_at.desc()))
        ]


@app.post("/api/applications", dependencies=[Depends(auth)], status_code=201)
async def start_application(body: StartInput):
    url = canonical(body.url.strip())
    key = job_key(url, settings().enable_mock_portal)
    resume_id = body.resume_id or default_resume()
    validate_doc(resume_id)
    with session() as db:
        existing = db.scalar(select(Application).where(Application.job_key == key))
        if not existing:
            # Employer links and their user-confirmed ATS destinations represent
            # one tracked application, even when their domains are different.
            existing = next(
                (
                    row
                    for row in db.scalars(select(Application))
                    if job_key(row.data["url"], settings().enable_mock_portal) == key
                    or any(
                        not dest["submission"] and job_key(dest["url"], settings().enable_mock_portal) == key
                        for dest in row.data.get("workflow_destinations", [])
                    )
                ),
                None,
            )
        if existing:
            raise HTTPException(
                409,
                {
                    "message": "This position already exists. Resume it in History rather than applying twice.",
                    "application_id": existing.id,
                },
            )
        # One dedicated application at a time avoids conflicting user attention / visible browsers.
        active = db.scalar(
            select(Application).where(
                Application.status.not_in(
                    ["submitted", "rejected", "cancelled", "paused", "submission_unknown"]
                )
            )
        )
        if active:
            raise HTTPException(
                409, {"message": "Pause or stop your current application first.", "application_id": active.id}
            )
        item = Application(
            id=str(uuid4()),
            job_key=key,
            status="queued",
            revision=0,
            data={"url": url, "resume_id": resume_id, "answers": [], "warnings": [], "pending": None},
        )
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "This position is already tracked.")
        result = application_view(item)
    await agent_for(item.id).start()
    return result


@app.get("/api/applications/{app_id}", dependencies=[Depends(auth)])
def application(app_id: str):
    return {**application_view(get_application(app_id)), "messages": messages(app_id)}


@app.get("/api/applications/{app_id}/preview", dependencies=[Depends(auth)])
def preview(app_id: str):
    get_application(app_id)
    agent = AGENTS.get(app_id)
    data = agent.controller.screenshot if agent and agent.controller else None
    if not data:
        return Response(status_code=204)
    return Response(data, media_type="image/jpeg")


@app.post("/api/applications/{app_id}/answer", dependencies=[Depends(auth)])
async def answer(app_id: str, body: AnswerInput):
    validate_doc(body.document_id)
    await agent_for(app_id).answer(
        body.text, body.remember, body.sensitive_permission, body.document_id, body.origin
    )
    return {"accepted": True}


@app.post("/api/applications/{app_id}/action", dependencies=[Depends(auth)])
async def action(app_id: str, body: ActionInput):
    agent = agent_for(app_id)
    await {
        "pause": agent.pause,
        "continue": agent.resume,
        "cancel": agent.stop,
        "stop": agent.stop,
        "retry": agent.retry,
    }[body.action]()
    return application_view(get_application(app_id))


@app.post("/api/applications/{app_id}/approve", dependencies=[Depends(auth)])
async def approve(app_id: str, body: ApproveInput):
    await agent_for(app_id).approve(body.revision)
    return {"approved": True}


@app.put("/api/applications/{app_id}/answers", dependencies=[Depends(auth)])
async def edit_answer(app_id: str, body: EditInput):
    agent = agent_for(app_id)
    validate_doc(body.document_id)
    async with agent.lock:
        item = get_application(app_id)
        if item.status != "review":
            raise ValueError("Answers can be edited when the application reaches review.")
        selected = next(
            (
                x
                for x in item.data.get("answers", [])
                if x["key"] == body.key
                and x.get("group", "") == body.group
                and x.get("index", 0) == body.index
            ),
            None,
        )
        if not selected:
            raise ValueError("Field not found in completed answers.")
        from backend.app.tracker import save_answer

        field = Field(
            **{k: selected[k] for k in ("key", "label", "kind", "required", "options", "group", "index")}
        )
        save_answer(
            app_id,
            field,
            Resolution(
                body.answer,
                "user",
                "Edited by you during application review.",
                body.document_id or selected.get("document_id"),
            ),
        )
        # Reconstruct all steps so earlier page edits really reach the portal before reapproval.
        if agent.task:
            agent.task.cancel()
            try:
                await agent.task
            except asyncio.CancelledError:
                pass
        if agent.controller:
            await agent.controller.close()
        agent.state("paused")
        agent.prior_state = None
    await agent.resume()
    return {
        "updated": True,
        "message": "Replaying the form with your updated answer. Review again before approval.",
    }


@app.post("/api/applications/{app_id}/draft", dependencies=[Depends(auth)])
async def draft(app_id: str):
    agent = agent_for(app_id)
    if not agent.pending or agent.pending.kind not in ("textarea", "text"):
        raise ValueError("Drafts are available only for the current written question.")
    p = get_profile()
    # Explicit user action; no contact data, grades, eligibility, or documents are sent.
    minimal = {
        "projects": [{k: x.get(k, "") for k in ("name", "description", "skills")} for x in p["projects"]],
        "experience": [{k: x.get(k, "") for k in ("title", "description")} for x in p["employment"]],
    }
    try:
        text = await agent.ai.draft(agent.pending.label, minimal)
    except Exception:
        raise ValueError(
            "Draft generation is unavailable. Check your local OpenAI configuration or write your answer directly."
        ) from None
    return {"draft": text, "source": "draft", "requires_review": True}


@app.post("/api/applications/{app_id}/chat", dependencies=[Depends(auth)])
async def chat(app_id: str, body: ChatInput):
    agent = agent_for(app_id)
    text = body.message.strip()
    lower = text.casefold().rstrip(".! ")
    fixed = {
        "pause": "pause",
        "pause the application": "pause",
        "continue": "continue",
        "resume": "continue",
        "cancel this application": "cancel",
        "cancel": "cancel",
        "stop": "cancel",
        "show me what you filled out": "show",
        "why did you choose that answer": "why",
        "don’t remember that answer": "forget",
        "don't remember that answer": "forget",
    }
    action_name = fixed.get(lower)
    value = None
    graduation = re.fullmatch(
        r"(?:change|update|set) (?:my )?(?:expected )?graduation(?: date)?(?: to| is)? (\d{4}-\d{2})", lower
    )
    resume_command = re.fullmatch(r"use (?:my )?(?:resume )?(.+\.(?:pdf|docx))", text, re.I)
    if graduation:
        action_name, value = "graduation", graduation.group(1)
    elif resume_command:
        action_name, value = "resume", resume_command.group(1)
    if action_name:
        reply = "Done."
    elif get_application(app_id).status in ("waiting_answer", "waiting_verification", "waiting_workflow"):
        await agent.answer(text)
        return {
            "reply": "I’ve entered your answer for this application. Use Saved answers to explicitly approve reuse."
        }
    else:
        try:
            command_result = await agent.ai.chat(text)
        except Exception:
            raise ValueError(
                "AI help is unavailable. Check your local API configuration or use the profile and application controls."
            ) from None
        action_name, value, reply = command_result.action, command_result.value, command_result.reply
    log(app_id, text, "user")
    if action_name in ("pause", "continue", "cancel"):
        await {"pause": agent.pause, "continue": agent.resume, "cancel": agent.stop}[action_name]()
    elif action_name in ("show", "why"):
        reply = (
            "\n".join(
                f"{x['label']}: {x['answer']} — {x['explanation']}"
                for x in get_application(app_id).data.get("answers", [])
            )
            or "No fields have been completed yet."
        )
    elif action_name == "graduation":
        if not value or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise ValueError("Specify graduation as YYYY-MM, or edit Education.")
        p = get_profile()
        if not p["education"]:
            raise ValueError("Add an education record first.")
        p["education"][0]["graduation"] = value
        save_profile(p)
        reply = "Updated your first education record. Existing application answers remain in review for you to edit."
    elif action_name == "resume":
        if get_application(app_id).status not in ("paused", "review", "waiting_answer"):
            raise ValueError("Pause the application before switching resumes.")
        doc = next((d for d in list_documents() if d["name"] == value and d["kind"] == "resume"), None)
        if not doc:
            raise ValueError("Use the Documents panel to select an uploaded resume.")
        await change_resume(app_id, doc["id"])
        reply = "Resume changed. The form will reconstruct and require a fresh review."
    elif action_name == "forget":
        answers = get_application(app_id).data.get("answers", [])
        if answers:
            last = answers[-1]
            with session() as db:
                item = db.scalar(
                    select(SavedAnswer).where(SavedAnswer.fingerprint == fingerprint(last["label"]))
                )
                if item:
                    db.delete(item)
                    db.commit()
            reply = "Removed reusable memory for the latest answered question. The application’s own answer remains in its review."
    log(app_id, reply)
    return {"reply": reply}


@app.put("/api/applications/{app_id}/resume/{doc_id}", dependencies=[Depends(auth)])
async def change_resume(app_id: str, doc_id: str):
    validate_doc(doc_id)
    agent = agent_for(app_id)
    if get_application(app_id).status not in ("paused", "review", "waiting_answer"):
        raise ValueError("Pause or review before changing the resume.")
    async with agent.lock:
        if agent.task:
            agent.task.cancel()
            try:
                await agent.task
            except asyncio.CancelledError:
                pass
        if agent.controller:
            await agent.controller.close()
        current = get_application(app_id)
        answers = [x for x in current.data.get("answers", []) if x["kind"] != "file"]
        update(app_id, resume_id=doc_id, answers=answers, pending=None)
        agent.state("paused")
        agent.prior_state = None
    await agent.resume()
    return {"updated": True}


@app.websocket("/api/ws/{app_id}")
async def events(ws: WebSocket, app_id: str):
    protocols = ws.headers.get("sec-websocket-protocol", "").split(",")
    token = protocols[-1].strip() if len(protocols) == 2 and protocols[0].strip() == "internship" else ""
    if (
        ws.client.host not in ("127.0.0.1", "::1", "testclient")
        or ws.headers.get("origin") not in settings().origins
        or not secrets.compare_digest(token, TOKEN)
    ):
        await ws.close(code=1008)
        return
    await ws.accept(subprotocol="internship")
    try:
        last = None
        while True:
            data = application(app_id)
            signature = (data["revision"], len(data["messages"]))
            if signature != last:
                await ws.send_json(data)
                last = signature
            await asyncio.sleep(0.4)
    except (WebSocketDisconnect, RuntimeError):
        pass


# Packaged mode: the website and API share one localhost server. No source/data directory is exposed.
_frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="website")
