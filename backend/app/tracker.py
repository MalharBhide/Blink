from sqlalchemy import select
import re
from database.session import session
from database.models import Application, ApplicationAnswer, ExecutionLog, Document


def application_view(app):
    return {
        "id": app.id,
        "status": app.status,
        "revision": app.revision,
        "created_at": app.created_at.isoformat(),
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        **app.data,
    }


def get_application(app_id):
    with session() as db:
        app = db.get(Application, app_id)
        if not app:
            raise ValueError("Application not found.")
        return app


def update(app_id, status=None, **data):
    with session() as db:
        app = db.get(Application, app_id)
        if status:
            app.status = status
        app.revision += 1
        app.data = {**app.data, **data}
        db.commit()
        return app


def log(app_id, message, role="agent"):
    # Only curated events/user answers; never DOM dumps, secrets, passwords, or exceptions.
    with session() as db:
        db.add(ExecutionLog(application_id=app_id, data={"role": role, "message": message[:5000]}))
        db.commit()


def messages(app_id):
    with session() as db:
        return [
            {"id": x.id, "time": x.created_at.isoformat(), **x.data}
            for x in db.scalars(
                select(ExecutionLog).where(ExecutionLog.application_id == app_id).order_by(ExecutionLog.id)
            )
        ]


def save_answer(app_id, field, resolution):
    with session() as db:
        app = db.get(Application, app_id)
        answer = {
            **field.dict(),
            "answer": resolution.answer,
            "source": resolution.source,
            "explanation": resolution.explanation,
            "document_id": resolution.document_id,
            "reviewed": resolution.reviewed,
            "page": field.page,
        }
        existing = [
            x
            for x in app.data.get("answers", [])
            if not (
                x["key"] == field.key
                and x.get("group", "") == field.group
                and x.get("index", 0) == field.index
                and x.get("page", 0) == field.page
                and x.get("label") == field.label
            )
        ]
        data = {**app.data, "answers": [*existing, answer]}
        if (
            field.kind == "file"
            and resolution.document_id
            and re.search(r"\b(?:resume|résumé|cv|curriculum vitae)\b", field.label, re.I)
        ):
            doc = db.get(Document, resolution.document_id)
            if doc and doc.data["kind"] == "resume":
                data["resume_id"] = doc.id
        app.data = data
        app.revision += 1
        db.add(ApplicationAnswer(application_id=app_id, data=answer))
        db.commit()
