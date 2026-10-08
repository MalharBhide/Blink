from pydantic import BaseModel, Field, ConfigDict
from typing import Literal


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    personal: dict[str, str] = Field(default_factory=dict)
    preferences: dict[str, str] = Field(default_factory=dict)
    education: list[dict[str, str]] = Field(default_factory=list, max_length=30)
    employment: list[dict[str, str]] = Field(default_factory=list, max_length=30)
    projects: list[dict[str, str]] = Field(default_factory=list, max_length=50)
    skills: list[dict[str, str]] = Field(default_factory=list, max_length=100)


class StartInput(BaseModel):
    url: str = Field(max_length=2048)
    resume_id: str | None = None


class AnswerInput(BaseModel):
    text: str = Field(default="", max_length=10000)
    remember: bool = False
    sensitive_permission: bool = False
    document_id: str | None = None
    origin: Literal["user", "draft"] = "user"


class ActionInput(BaseModel):
    action: Literal["pause", "continue", "cancel", "stop", "retry"]


class ApproveInput(BaseModel):
    revision: int
    approved: Literal[True]


class EditInput(BaseModel):
    key: str
    answer: str = Field(max_length=10000)
    group: str = ""
    index: int = 0
    document_id: str | None = None


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class MemoryInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(max_length=10000)
    sensitive_permission: bool = False
