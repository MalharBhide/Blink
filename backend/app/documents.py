import io
import zipfile
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from backend.app.config import settings, cipher
from database.session import session
from database.models import Document

MAX_SIZE = 15 * 1024 * 1024
KINDS = {"resume", "cover_letter", "transcript", "supporting"}


def list_documents():
    with session() as db:
        return [{"id": d.id, **d.data} for d in db.scalars(select(Document).order_by(Document.created_at))]


def create_document(name, content, kind, default=False):
    name = Path(name.replace("\\", "/")).name
    extension = Path(name).suffix.lower()
    if kind not in KINDS or extension not in (".pdf", ".docx") or len(content) > MAX_SIZE or not content:
        raise ValueError("Use a PDF or DOCX up to 15 MB and a supported document type.")
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF header.")
    if extension == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if (
                    "word/document.xml" not in z.namelist()
                    or sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024
                ):
                    raise ValueError("Invalid DOCX.")
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid DOCX.") from exc
    doc_id = str(uuid4())
    directory = settings().data_dir / "documents"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / doc_id
    path.write_bytes(cipher().encrypt(content))
    path.chmod(0o600)
    metadata = {
        "name": name,
        "kind": kind,
        "default": default and kind == "resume",
        "size": len(content),
        "mime": "application/pdf"
        if extension == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    with session() as db:
        if metadata["default"]:
            for old in db.scalars(select(Document)):
                old.data = {**old.data, "default": False}
        doc = Document(id=doc_id, data=metadata)
        db.add(doc)
        db.commit()
    return {"id": doc_id, **metadata}


def document_payload(doc_id):
    # Only opaque IDs selected by the user / their default are accepted, never raw paths.
    with session() as db:
        doc = db.get(Document, doc_id)
        if not doc:
            raise ValueError("Selected document no longer exists.")
        content = cipher().decrypt((settings().data_dir / "documents" / doc.id).read_bytes())
        return {"name": doc.data["name"], "mimeType": doc.data["mime"], "buffer": content}


def default_resume():
    docs = list_documents()
    return next((d["id"] for d in docs if d["kind"] == "resume" and d["default"]), None)
