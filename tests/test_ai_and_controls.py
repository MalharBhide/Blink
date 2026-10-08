from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from backend.app.ai import AIService, Match, Command
from backend.app.memory import remember
from browser_agent.resolver import AnswerResolver
from browser_agent.parser import Field
from database.models import Application


def fake_ai():
    ai = AIService()
    ai.client = SimpleNamespace(responses=SimpleNamespace(parse=AsyncMock(), create=AsyncMock()))
    return ai


async def test_structured_openai_contract_and_no_tools():
    ai = fake_ai()
    ai.client.responses.parse.return_value = SimpleNamespace(
        output_parsed=Match(candidate_id="saved", confidence=0.99, explanation="Equivalent wording")
    )
    result = await ai.match(
        "Preferred programming language?",
        [{"id": "saved", "question": "Which programming language do you prefer?"}],
    )
    assert result.candidate_id == "saved"
    params = ai.client.responses.parse.call_args.kwargs
    assert params["store"] is False
    assert params["text_format"] is Match
    assert "tools" not in params
    ai.client.responses.parse.return_value = SimpleNamespace(
        output_parsed=Command(action="pause", value=None, reply="Paused.")
    )
    assert (await ai.chat("Pause the application.")).action == "pause"
    ai.client.responses.create.return_value = SimpleNamespace(
        output_text="A draft grounded in the supplied project."
    )
    assert "draft" in await ai.draft(
        "What would you like to learn?", {"projects": [{"description": "Built a class project."}]}
    )
    assert ai.client.responses.create.call_args.kwargs["store"] is False
    assert "tools" not in ai.client.responses.create.call_args.kwargs


async def test_semantic_match_is_review_only_and_contextual_questions_never_sent(client):
    saved = remember("Which programming language do you prefer?", "Python")
    ai = fake_ai()
    ai.client.responses.parse.return_value = SimpleNamespace(
        output_parsed=Match(candidate_id=saved["id"], confidence=0.99, explanation="Equivalent wording.")
    )
    resolver = AnswerResolver(ai)
    field = Field("custom", "Preferred programming language?", "text", True, [])
    app = Application(id=str(uuid4()), data={"answers": []})
    result = await resolver.resolve(field, app)
    assert result.source == "draft" and result.reviewed is False
    assert result.answer == "Python"
    payload = ai.client.responses.parse.call_args.kwargs["input"][1]["content"]
    assert "Python" not in payload  # actual remembered answer is never sent for matching
    ai.client.responses.parse.reset_mock()
    for label in ("Will you need sponsorship now?", "Gender", "Are you available in 2028?"):
        assert await resolver.resolve(Field("other", label, "text", True, []), app) is None
    ai.client.responses.parse.assert_not_awaited()
    remember("Reviewed response", "My accepted draft.", source="draft", reviewed=True)
    resolved = await resolver.resolve(Field("x", "Reviewed response", "text", True, []), app)
    assert resolved.source == "draft" and resolved.reviewed


async def test_replay_preserves_reviewed_draft_provenance(client):
    answer = {
        "key": "q",
        "group": "",
        "index": 0,
        "answer": "Approved draft",
        "source": "draft",
        "reviewed": True,
        "explanation": "Reviewed by you",
        "document_id": None,
    }
    app = Application(id="draft", data={"answers": [answer]})
    result = await AnswerResolver(AIService()).resolve(
        Field("q", "Written question", "textarea", True, []), app
    )
    assert result.source == "draft" and result.reviewed


async def test_negative_future_and_country_eligibility_never_inferred(client, profile_data):
    client.put("/api/profile", json=profile_data)
    resolver = AnswerResolver(AIService())
    app = Application(id="scope", data={"answers": []})
    for label in (
        "Are you NOT authorized to work in the United States?",
        "Will you be authorized to work in the United States in 2028?",
        "Are you authorized to work in the United States and Canada?",
        "Will you NOT require sponsorship now or in the future in the United States?",
    ):
        assert await resolver.resolve(Field("f", label, "text", True, []), app) is None


async def test_ambiguous_repeated_controls_request_user_instead_of_duplicating_first_record(
    client, profile_data
):
    client.put("/api/profile", json=profile_data)
    result = await AnswerResolver(AIService()).resolve(
        Field("school2", "College or university", "text", True, [], "unclassified_repeat"),
        Application(id="repeat", data={"answers": []}),
    )
    assert result is None


def test_unreviewed_draft_cannot_enter_reusable_memory(client):
    with pytest.raises(ValueError, match="Review"):
        remember("Question", "Invented draft", source="draft")


async def test_application_dependent_questions_do_not_become_universal_answers(client, profile_data):
    client.put("/api/profile", json=profile_data)
    for question in (
        "Have you previously worked for this company?",
        "Preferred compensation for this role?",
        "I agree to the terms of this application",
    ):
        assert client.post("/api/memory", json={"question": question, "answer": "Yes"}).status_code == 400
    resolver = AnswerResolver(AIService())
    app = Application(id="specific", data={"answers": []})
    # An internship availability date cannot be filled from a previous employer's start date.
    assert await resolver.resolve(Field("start", "Start date", "date", True, []), app) is None
    assert (
        await resolver.resolve(Field("start", "Start date", "month", True, [], "employment"), app)
    ).answer == "2025-06"
