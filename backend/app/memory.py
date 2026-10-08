import hashlib
import re
from uuid import uuid4
from sqlalchemy import select, delete
from database.session import session
from database.models import Profile, Preference, Education, Employment, Project, Skill, SavedAnswer

COLLECTIONS = {"education": Education, "employment": Employment, "projects": Project, "skills": Skill}
SENSITIVE = re.compile(
    r"\b(gender|race|ethnic|disabilit\w*|veteran|pronoun\w*|sex|sexual\s+orientation|racial|religio\w*)\b",
    re.I,
)
CONTEXTUAL = re.compile(
    r"\b(company|previously|relocat\w*|available|availability|compensation|salary|start date|end date|country|authorized|authorised|sponsor\w*)\b",
    re.I,
)


APPLICATION_ONLY = re.compile(
    r"\b(this company|our company|the company|this position|this role|previously worked|ever worked|salary|compensation|certif\w*|terms|agree|consent)\b",
    re.I,
)


def normalize(question: str):
    # Do not remove qualifiers, negation, dates, countries, or employer names.
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", question.casefold())).strip()


def fingerprint(question, scope="global"):
    return hashlib.sha256(f"{scope}:{normalize(question)}".encode()).hexdigest()


def get_profile():
    with session() as db:
        p = db.get(Profile, 1)
        pref = db.get(Preference, 1)
        return {
            "personal": p.data if p else {},
            "preferences": pref.data if pref else {},
            **{
                k: [v.data for v in db.scalars(select(cls).order_by(cls.id))]
                for k, cls in COLLECTIONS.items()
            },
        }


def save_profile(data):
    with session() as db:
        p = db.get(Profile, 1) or Profile(id=1)
        p.data = data.get("personal", {})
        db.add(p)
        db.flush()
        pref = db.get(Preference, 1) or Preference(id=1)
        pref.data = data.get("preferences", {})
        db.add(pref)
        for key, cls in COLLECTIONS.items():
            db.execute(delete(cls))
            for value in data.get(key, []):
                db.add(cls(profile_id=1, data=value))
        db.commit()
    return get_profile()


def remember(question, answer, scope="global", explicit_sensitive=False, source="user", reviewed=False):
    if scope == "global" and APPLICATION_ONLY.search(question):
        raise ValueError(
            "This question depends on the employer, position, or its terms. Answer it within that application; it cannot become universal memory."
        )
    if source == "draft" and not reviewed:
        raise ValueError("Review a generated draft before approving its memory.")
    if SENSITIVE.search(question) and not explicit_sensitive:
        raise ValueError("Self-identification requires explicit permission to reuse this answer.")
    with session() as db:
        key = fingerprint(question, scope)
        item = db.scalar(select(SavedAnswer).where(SavedAnswer.fingerprint == key)) or SavedAnswer(
            id=str(uuid4()), fingerprint=key
        )
        item.data = {
            "question": question,
            "answer": answer,
            "scope": scope,
            "source": source,
            "reviewed": reviewed,
            "sensitive_permission": explicit_sensitive,
        }
        db.add(item)
        db.commit()
        return {"id": item.id, **item.data}
