# ruff: noqa: E402
# Environment isolation must precede importing the application.
import os
import tempfile
from pathlib import Path

# All tests use fresh encrypted synthetic data and headless isolated browser contexts.
TEST_DIR = Path(tempfile.mkdtemp(prefix="blink-tests-"))
os.environ["DATA_DIR"] = str(TEST_DIR)
os.environ["DATABASE_URL"] = "sqlite:///" + str(TEST_DIR / "app.sqlite3")
os.environ["ENCRYPTION_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["BROWSER_HEADLESS"] = "true"
os.environ["ENABLE_MOCK_PORTAL"] = "true"

import pytest
import subprocess
import sys
import time
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import delete
from backend.app.main import app, AGENTS
from backend.app.config import access_code
from database.models import Base, Profile
from database.session import session


@pytest.fixture(scope="session")
def portal():
    # Fixed port is a deliberate part of the mock-only allowlist.
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "mock_portal.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
            "--no-access-log",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError("Mock portal could not start; port 8001 may already be in use.")
        try:
            if httpx.get("http://127.0.0.1:8001/mock/jobs/test", timeout=1).status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("Mock portal startup timed out.")
    yield
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture
def client():
    with TestClient(app) as client:
        with session() as db:
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(delete(table))
            db.add(Profile(id=1, data={}))
            db.commit()
        AGENTS.clear()
        token = client.get(
            "/api/session", headers={"X-Local-Client": "internship-ui", "X-Blink-Access": access_code()}
        ).json()["token"]
        client.headers.update({"Authorization": "Bearer " + token})
        yield client


@pytest.fixture
def profile_data():
    return {
        "personal": {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": "synthetic@example.test",
            "phone": "5550101234",
            "city": "Bloomington",
        },
        "preferences": {"authorized_us": "Yes", "sponsorship_us": "No"},
        "education": [
            {
                "school": "Synthetic University",
                "degree": "Bachelor of Science",
                "major": "Computer Science",
                "graduation": "2027-05",
            },
            {
                "school": "Example College",
                "degree": "Associate",
                "major": "Mathematics",
                "graduation": "2025-05",
            },
        ],
        "employment": [
            {
                "employer": "Synthetic Labs",
                "title": "Research Assistant",
                "start": "2025-06",
                "description": "Built a class project.",
            }
        ],
        "projects": [],
        "skills": [{"name": "Python"}],
    }


def await_status(client, app_id, desired, timeout=35):
    desired = {desired} if isinstance(desired, str) else set(desired)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get("/api/applications/" + app_id).json()
        if result["status"] in desired:
            return result
        if (
            result["status"] in {"rejected", "submission_unknown", "paused", "cancelled"}
            and result["status"] not in desired
        ):
            pytest.fail(f"Unexpected agent state: {result}")
        time.sleep(0.15)
    pytest.fail(f"Timed out awaiting {desired}: {result}")
