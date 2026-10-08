from dataclasses import dataclass
from sqlalchemy import select
from backend.app.memory import get_profile, fingerprint, normalize, SENSITIVE, CONTEXTUAL, APPLICATION_ONLY
from database.models import SavedAnswer
from database.session import session

ALIASES = {
    "first_name": ["first name", "legal first name", "given name"],
    "last_name": ["last name", "legal last name", "family name", "surname"],
    "preferred_name": ["preferred name"],
    "email": ["email", "email address"],
    "phone": ["phone", "phone number", "mobile phone number"],
    "country": ["country"],
    "state": ["state", "state province"],
    "city": ["city"],
    "address": ["address", "address line 1", "mailing address", "street address"],
    "zip": ["zip", "zip code", "postal code"],
    "linkedin": ["linkedin", "linkedin url"],
    "github": ["github", "github url"],
    "portfolio": ["portfolio", "website", "personal website"],
    "school": ["school", "university", "college or university", "school or university"],
    "degree": ["degree", "degree type"],
    "major": ["major", "field of study"],
    "minor": ["minor"],
    "additional_majors": ["additional majors"],
    "graduation": ["expected graduation", "expected graduation date", "graduation date"],
    "academic_year": ["current academic year", "academic year"],
    "gpa": ["gpa", "grade point average"],
    "gpa_scale": ["gpa scale"],
    "coursework": ["relevant coursework"],
    "honors": ["academic honors"],
    "employer": ["employer", "company", "company name"],
    "title": ["job title", "position title"],
    "start": ["start date", "employment start date"],
    "end": ["end date", "employment end date"],
    "description": ["responsibilities", "responsibilities and accomplishments", "job description"],
}


@dataclass
class Resolution:
    answer: str
    source: str
    explanation: str
    document_id: str | None = None
    reviewed: bool = False


def profile_value(field, profile):
    label = normalize(field.label)
    key = next((k for k, aliases in ALIASES.items() if label in aliases), None)
    if not key:
        return None
    if key in ("start", "end") and field.group != "employment" and not label.startswith("employment "):
        return None
    if field.group in ("education", "employment"):
        records = profile[field.group]
        record = records[field.index] if field.index < len(records) else {}
    elif key in (
        "school",
        "degree",
        "major",
        "minor",
        "graduation",
        "academic_year",
        "gpa",
        "gpa_scale",
        "coursework",
        "honors",
        "additional_majors",
    ):
        record = profile["education"][0] if profile["education"] else {}
    elif key in ("employer", "title", "start", "end", "description"):
        record = profile["employment"][0] if profile["employment"] else {}
    else:
        record = profile["personal"]
    value = record.get(key)
    return str(value) if value is not None and str(value).strip() else None


class AnswerResolver:
    def __init__(self, ai):
        self.ai = ai

    async def resolve(self, field, application):
        data = application.data
        # Saved application answers include record identity; they take priority after edits.
        for item in reversed(data.get("answers", [])):
            if (
                item["key"] == field.key
                and item.get("group", "") == field.group
                and item.get("index", 0) == field.index
            ):
                return Resolution(
                    item["answer"],
                    item["source"],
                    item["explanation"],
                    item.get("document_id"),
                    item.get("reviewed", False),
                )
        if field.group == "unclassified_repeat":
            return None
        if field.kind == "file":
            kind = "resume" if "resume" in field.label.casefold() or "cv" in field.label.casefold() else None
            document = data.get("resume_id") if kind == "resume" else data.get("documents", {}).get(field.key)
            if document:
                return Resolution(
                    "Selected uploaded document",
                    "user",
                    "Document explicitly chosen for this application.",
                    document,
                )
            return None
        if SENSITIVE.search(field.label):
            # No profile inference for EEO. Exact, explicitly consented saved answers only.
            value = None
        else:
            value = profile_value(field, get_profile())
        if value is not None:
            return Resolution(value, "profile", "Copied from your explicitly entered profile.")
        label = normalize(field.label)
        prefs = get_profile()["preferences"]
        # Exact positive eligibility templates only. Negation/time/jurisdiction qualifiers cannot be lost.
        eligibility = {
            normalize("Are you legally authorized to work in the United States?"): "authorized_us",
            normalize("Are you authorized to work in the United States?"): "authorized_us",
            normalize("Are you currently authorized to work in the United States?"): "authorized_us",
            normalize(
                "Will you now or in the future require visa sponsorship in the United States?"
            ): "sponsorship_us",
            normalize(
                "Do you need employment visa sponsorship in the United States now or in the future?"
            ): "sponsorship_us",
        }
        key = eligibility.get(label)
        if key and prefs.get(key) in ("Yes", "No"):
            return Resolution(
                prefs[key],
                "profile",
                "Your explicitly saved United States eligibility answer, with the same jurisdiction, positive wording, and time scope.",
            )
        if APPLICATION_ONLY.search(field.label):
            return None
        with session() as db:
            exact = db.scalar(select(SavedAnswer).where(SavedAnswer.fingerprint == fingerprint(field.label)))
            if exact and (not SENSITIVE.search(field.label) or exact.data.get("sensitive_permission")):
                return Resolution(
                    str(exact.data["answer"]),
                    exact.data.get("source", "user"),
                    "Exact question matches an answer you approved for reuse.",
                    reviewed=exact.data.get("reviewed", False),
                )
            # Semantic matching excludes sensitive/context-dependent questions.
            if CONTEXTUAL.search(field.label) or SENSITIVE.search(field.label):
                return None
            candidates = [
                {"id": x.id, "question": x.data["question"]}
                for x in db.scalars(select(SavedAnswer))
                if x.data.get("scope") == "global"
                and not CONTEXTUAL.search(x.data["question"])
                and not SENSITIVE.search(x.data["question"])
            ]
        if candidates:
            try:
                match = await self.ai.match(field.label, candidates[:30])
            except Exception:
                match = None
            # A semantic suggestion always goes through review before it is filled.
            if match and match.confidence >= 0.98 and match.candidate_id in {c["id"] for c in candidates}:
                with session() as db:
                    saved = db.get(SavedAnswer, match.candidate_id)
                    return Resolution(
                        str(saved.data["answer"]),
                        "draft",
                        "Suggested equivalent saved question; please confirm: " + match.explanation,
                    )
        return None
