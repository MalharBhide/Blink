# ⚡ Blink

**Apply for internships in the _blink_ of an eye.** Answer once, apply repeatedly.

Blink is a local, single-user MVP with a React/TypeScript/Tailwind frontend, FastAPI backend, encrypted SQLite persistence through SQLAlchemy/Alembic, a restricted Playwright browser agent, WebSocket updates, and optional OpenAI integration.

**The complete onboarding → profile → document upload → automatic form filling → missing-answer chat → remembered answers → review → approved submission → confirmed history flow works against the included local multi-step mock portal.** Real Workday, Greenhouse, and Lever adapters are conservative and experimental. They parse known semantics and pause at unsupported employer-specific controls, redirects, authentication, or network endpoints. This is not a universal real-employer auto-apply service. No real employer submission is used in automated tests.

## Quick start

Requirements: Python **3.12+**, Node.js **22.12+** (24 LTS recommended), and **pnpm 11**. Chromium installation may need additional system packages on Linux. macOS, Windows, and Linux source paths/launchers are supported; development was verified on macOS. Use your own downloaded clone for your own data.

```bash
git clone https://github.com/MalharBhide/Blink.git
cd Blink
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.lock.txt
python -m playwright install chromium
cp .env.example .env
cd frontend
pnpm install --frozen-lockfile
cd ..
python -m alembic upgrade head
python scripts/dev.py
```

Open **http://127.0.0.1:5173** and unlock using the code in your local **`.data/access-code`** file. Open that file in a text editor (or run `cat .data/access-code`; PowerShell: `Get-Content .data/access-code`). It is created with owner-only permissions and never served over HTTP. Paste it into Blink; it is kept only in memory. The supervisor starts the backend on port 8000, mock portal on 8001, and frontend on 5173. Ctrl+C stops the services. Migrations also run idempotently at API startup. The launcher creates `.env` from the example if missing.

Windows PowerShell uses `py -3.12 -m venv .venv`, `.venv\Scripts\Activate.ps1`, and `Copy-Item .env.example .env`. Use `python` instead of `python3` after activating. If necessary allow script activation for the current terminal, or call `.venv\Scripts\python.exe` directly. Install pnpm using the official package manager setup or `npm install -g pnpm@11`. On Linux, `python -m playwright install --with-deps chromium` can install required system dependencies.

### Start services separately

Run these from the repository root with the Python environment activated:

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log
python -m uvicorn mock_portal.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

In a third terminal:

```bash
cd frontend
pnpm dev
```

Do not use `--host 0.0.0.0`, expose the ports on the network, or deploy this single-user MVP as a hosted service.

## Try the complete flow

1. Open **Applicant profile**, enter whatever personal/education/experience/skill data you want, and **Save profile**. Onboarding is optional and editable; you can start before every field is answered. Multiple education, employment, project, and skill records are supported.
2. Upload a PDF/DOCX under **Documents**. The first resume becomes the default. Choose another document per application or switch the selected resume while paused/reviewing.
3. Start with a fresh local URL such as `http://127.0.0.1:8001/mock/jobs/demo-1`. **Try the local test portal** pre-fills that URL. Use `demo-2` for a second role to demonstrate memory reuse. Never enter real applicant data in test fixtures.
4. Watch the dedicated visible Chromium window. The workspace displays synchronized screenshots after each operation, rather than an interactive embedded browser.
5. The agent fills profile facts and uploads the selected resume. Required unknown questions pause the worker. Answer through chat and check **Remember this exact answer** only if you explicitly want future reuse. Context-dependent availability is kept with the application unless you approve exact wording for reuse. Optional EEO fields remain empty; sensitive reusable answers need separate explicit consent.
6. At review, inspect every answer/document/provenance explanation. **Edit** reconstructs all steps so changes actually reach the portal, then requires a new review.
7. Click **Approve & submit** for that application. Approval is revision-bound. Only a recognized confirmation establishes success. View the result in **Application history**. Duplicate job IDs/URLs are blocked even when tracking query parameters change.
8. **Pause**, **Continue**, and **Stop** work through actual backend actions. Stop cancels the worker and closes the browser. Resume after a service restart reconstructs supported forms with saved answers; login, CAPTCHA, and file uploads may need to be repeated. Submitted and uncertain submissions cannot be auto-resubmitted.

Useful fixture URLs: `/mock/jobs/non-intern` is rejected; `/mock/jobs/ambiguous` requires confirmation; `/mock/jobs/malicious` contains prompt injection that cannot expand permissions.

## OpenAI configuration

Edit your own ignored `.env`:

```dotenv
OPENAI_API_KEY=your-own-key
OPENAI_MODEL=gpt-4.1-mini
BROWSER_HEADLESS=false
ENABLE_MOCK_PORTAL=true
```

The model is configurable. Without a key the deterministic workflow still works: profile filling, exact approved memory, missing questions, review, submission, and history. With a key, Blink uses the [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses) for conversational help, conservative semantic question suggestions, and written drafts requested with **Help draft an answer**. There are no AI browser/OS tools. Drafts and semantic suggestions require user acceptance. Live paid API calls are **not** part of automated testing and require your own configured key.

AI calls send minimal question/chat context; draft generation sends only selected verified project/experience descriptions. Contact data, resumes, grades, and eligibility are not automatically sent for drafting. Calls use `store=False`, a timeout, and bounded retries. Provider retention policies still apply. Leave the key blank to disable AI network calls entirely. More details are in [Security and privacy](docs/SECURITY.md).

## Privacy and public source code

**This repository contains no user applicant database or uploaded documents.** A user's profile and documents are created in their own local `.data/` directory when they run the application. They are encrypted at rest, Git-ignored, and excluded from publication. `.env`, the private access code, and the encryption key are also excluded. Frontend state and screenshots are not stored in browser localStorage. The local API uses origin/host/client checks and private access-code pairing and ephemeral bearer tokens; FastAPI telemetry is explicitly disabled.

This is a local trust boundary: someone with your OS account/admin privileges or your encryption key can access local data. Employer portals receive information entered into their forms and may save it before final submission; OpenAI receives selected context when enabled. There is no claim of certified legal compliance or protection against compromised devices. Read [docs/SECURITY.md](docs/SECURITY.md) before using real applicant data.

Keep secure backups of both `.data/` and its original key (or `ENCRYPTION_KEY` supplied separately). Losing the key makes data unreadable. A missing key for an existing database causes a startup error instead of silently creating a new key. This MVP has no automated key rotation. The optional mock portal keeps submitted fixture data in process memory only and is disabled in the backend unless explicitly enabled.

## Tests and checks

```bash
python -m pytest -q
python -m ruff check backend browser_agent database mock_portal tests scripts
python scripts/check_public_tree.py
cd frontend
pnpm build
pnpm exec playwright install chromium
pnpm test:e2e
```

Python tests launch the local mock portal on **8001** and use a fresh temporary encrypted database and synthetic applicant data. Stop your development mock server first. E2E tests start all three localhost services, use headless contexts, and store ignored synthetic test data in `.data/e2e`. Stop development services first for isolated E2E runs; E2E refuses to reuse existing servers and uses the built production frontend. CI runs in fresh environments. No employer forms are submitted.

Test coverage includes onboarding persistence, profile-derived filling, missing answers, explicit memory approval/reuse, repeated records, selected resume upload, pause/resume, non-internship rejection, URL/file/API access restrictions, malicious page content, no premature submit, revision approval, confirmed submission, review edits, duplicates, optional EEO consent, and authorization/sponsorship jurisdiction/time distinctions. Frontend tests cover the complete UI flow and mobile overflow. CI runs backend tests, lint, source hygiene, frontend build, and E2E tests.

## Current capability boundary

| Capability | Status |
| --- | --- |
| React UI: overview, profile tabs, documents, saved answers, workspace, history | Working |
| Encrypted normalized persistence and Alembic migration | Working |
| Local visible browser / synchronized screenshots | Working |
| Multi-step/repeated records and label-based form filling | Working on mock; control support available to adapters |
| Missing-answer chat, explicit memory reuse, revision-bound review, mock submission | End-to-end tested |
| Text, email, month/date, radios, native selects, file controls | Working |
| Checkboxes, searchable comboboxes, conditional DOM reinspection | Implemented; adapter-specific verification required |
| Workday/Greenhouse/Lever role selectors and scoped navigation | Experimental, conservative |
| Employer-specific Workday repeaters/custom dropdowns/draft APIs/login transitions | Partial; pauses instead of granting general access |
| Real ATS final submission network endpoints | Strictly limited; unrecognized endpoints blocked |
| OpenAI structured responses, question comparison, user-requested drafts | Implemented; SDK contract tested; paid live calls not exercised |
| CAPTCHA/authentication | Manual; unsupported redirects remain blocked |
| Resume after restart | Reconstructs supported forms; no saved passwords or browser cookies |
| PostgreSQL | ORM/migration structure ready; SQLite only tested; install/configure a PostgreSQL driver separately |
| Multi-user hosting, discovery, bulk applying, auto-submit | Outside this MVP; auto-submit is disabled |

An unsupported ATS workflow can pause before completion. Add and test a scoped adapter for that employer before expecting automatic applications there. The project prioritizes reliable local end-to-end behavior and restricted browsing, as specified.

## Architecture

```text
frontend/                  React + TypeScript + Tailwind + Vite
backend/app/               Local API, chat actions, AI, memory, encrypted documents, tracker
browser_agent/             Orchestrator state machine, URL policy, controller, parser, validator, adapters, resolver
database/                  Normalized SQLAlchemy entities and Alembic migration
mock_portal/           Synthetic multi-step internship application portal
tests/                     Pytest integration/security/browser tests
frontend/e2e/              Playwright UI workflow and responsive tests
scripts/                   Cross-platform launcher and publication hygiene check
.github/workflows/         CI
```

The orchestrator chooses permitted steps. The controller performs fixed browser actions validated by policy. The resolver uses deterministic profile mappings, exact approved memory, and review-only semantic suggestions. Browser route guards enforce requests independently of AI/page text; service workers are blocked following [Playwright's routing guidance](https://playwright.dev/python/docs/api/class-browsercontext). Applicant content lives in normalized encrypted entities with per-answer provenance (`user`, `profile`, or `draft`). No webpage content can invoke backend commands or alter permissions.

## Troubleshooting

- **Backend offline:** activate the environment, start the API on 8000, and check that `.env` frontend origins match `http://127.0.0.1:5173` or `http://localhost:5173`.
- **Browser missing:** `python -m playwright install chromium`; Linux may also need `--with-deps`.
- **Unknown/malformed control:** choose an available option; resolve validation manually in the dedicated browser. Account/CAPTCHA challenges are never bypassed. Unsupported portal URLs/endpoints need an adapter change rather than an allow-all switch.
- **Paused after restart:** open the application in History and Continue. It replays recorded values and asks for missing ones.
- **Submission unknown:** check the employer portal manually. Do not force another automated submission. Blink retains its duplicate lock.
- **Slow macOS Documents dependency reads:** some synced Documents directories make large `node_modules`/virtual environments slow. Use an ordinary local clone outside a synced folder, or install the Python environment outside the source tree. User data still remains local and ignored.
