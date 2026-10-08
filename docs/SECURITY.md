# Blink data and browser security

Blink is a **local, single-user development MVP**, with no hosted applicant service and no telemetry/analytics integration. Publishing the source code does not publish local profiles. Never deploy this MVP to a public server or bind the API/frontend to `0.0.0.0`.

## Local storage vs public repository

- Applicant content is created only after a user runs their own downloaded copy. No applicant records, uploaded documents, passwords, OpenAI keys, session tokens, or encryption keys are included in the repository.
- `.data/`, `.env`, database files, resumes, documents, test output, and generated files are Git-ignored. CI checks tracked files for private artifact paths and credential-like tokens. Synthetic test fixtures are deliberately fictitious.
- SQLAlchemy encrypts the content of profiles, education, employment, projects, skills, preferences, saved answers, application answers, application details, document metadata, and execution/chat logs using authenticated Fernet encryption. IDs, state, timestamps, and hashed duplicate/question indexes are plaintext metadata.
- Uploaded PDF/DOCX bytes are encrypted before storage. Playwright receives decrypted in-memory buffers **only for registered IDs chosen by the user**, rather than paths on the user's filesystem. Uploaded originals are not copied into the source tree. Screenshots are kept in process memory and served only through authenticated API routes.
- The default key is `.data/key`, created with mode `0600`; its directory uses `0700`. Alternatively provide `ENCRYPTION_KEY` in the user's own `.env`. Keep secure backups of the key **and** encrypted data. Losing the key loses access. The app refuses to silently generate a replacement key for an existing database.
- Files and keys on the same device cannot prevent malware, an administrator, or software running as the same OS user from accessing them. Use separate OS accounts, disk encryption, and device security. This app is not a hardened multi-user service or a guarantee of legal compliance.

## Local API boundary

The documented launcher binds API and frontend to `127.0.0.1`. Backend middleware rejects remote client IPs and unapproved Host/Origin headers. Data endpoints require a fresh random bearer token, retained only in frontend memory. Bootstrap requires a private access code stored in owner-only `.data/access-code`, in addition to a non-simple custom header; browser CORS allows only configured local frontend origins. WebSockets additionally validate client IP, Origin, and token subprotocol (not a URL query string). The code is not served by the frontend or any API endpoint, and is never placed in a URL or browser storage. Anyone who obtains it can unlock the local service; keep it private. On Windows, use an OS-user-private checkout/data directory and verify its NTFS permissions: POSIX file modes are not a Windows ACL guarantee. No authentication cookies are sent to the mock or employer portal. This mitigates remote website access/CSRF/DNS rebinding; **other software on the same OS account is within the local trust boundary**. Do not broaden CORS to `*`.

## Browser boundary

The browser agent uses a fresh Playwright Chromium process/context, with no access to a user's normal browser profile, extensions, tabs, cookies, or login sessions. No desktop control API is part of the application. Download acceptance, service workers, permissions, popups, and WebSockets are disabled. The browser retains Chromium's normal sandbox settings. There is no arbitrary evaluate, command, file path, or desktop endpoint available to the chatbot/AI.

The backend validates direct job URLs, supported ATS host/path patterns, public hostname resolution, exact requisition navigation paths, request types and methods, role titles, and execution states. An ATS hostname alone does not validate a role. Internship titles permit interaction; ambiguous summer analyst/co-op titles require user confirmation; titles with no internship signal are rejected. The page cannot extend allowlists. Navigation to another job, account sections, local file URLs, the Blink API, arbitrary websites, private network services, and cross-origin requests is blocked. Static ATS assets have narrow read-only exceptions. Unsupported redirects/endpoints cause a pause instead of broadening access.

This is an application-layer request policy, **not an operating-system/network sandbox against browser vulnerabilities**. Real ATS compatibility is intentionally limited. Test any new adapter with synthetic data and add explicit scoped request rules; do not grant entire ATS domains, arbitrary upload paths, or AI-selected URLs. Associated login/CAPTCHA flows that exceed existing permissions remain unsupported; no bypass is attempted. Do not log passwords or authentication page DOM.

## Submission and review

The agent only executes a final submit operation after an explicit approval endpoint call matching the current review revision. Editing answers reconstructs the form and invalidates approval. The local portal's submission POST is blocked until approval. Real portal submission endpoints have **no permissive global grant** and require a tested, scoped adapter extension. Page content, job descriptions, AI suggestions, and chat commands cannot approve submission. A click does not establish success: only a recognized portal confirmation does. Uncertain/interrupted submissions stay locked against duplicates. Stop cancels the worker, blocks further requests, and closes its isolated browser. It cannot undo a request that a portal already received.

## AI and external disclosure

OpenAI is optional. Leaving `OPENAI_API_KEY` empty keeps profile filling, exact memory matching, missing questions, review, and mock submission local and functional. When enabled:

- Semantic matching sends only question text and candidate question text/IDs. Context-sensitive eligibility, dates, employer details, and self-identification are excluded from semantic auto-matching. Semantic suggestions require user confirmation.
- Conversational help sends the user's chat message. Do not paste secrets into chat. Password fields are manual; credentials are never collected for browser login.
- Draft generation occurs only after clicking **Help draft an answer** and sends the current question plus selected project/experience descriptions. It does not send resumes, contact info, grades, or eligibility. Review and edit the draft before accepting it.
- Responses API calls set `store=False`, have timeouts and bounded retries, and provide no browser or OS tools. `store=False` does not itself guarantee zero provider-side retention; consult your provider's policy/account configuration.
- Employer portals receive the fields/documents you choose for that application; filling a form may send information to the employer before final submission, depending on its implementation. The app does not promise employer-side confidentiality.

Optional EEO answers are neither inferred nor selected from profile fields. Reusable self-identification memory requires an additional explicit consent flag. Country/current/future authorization and sponsorship remain distinct.

## Reporting issues

Open a repository issue containing only a minimal synthetic reproduction. Do not attach resumes, applicant databases, encryption keys, private screenshots, credentials, or application logs containing personal data. No legal compliance certification is claimed; jurisdiction-specific requirements need qualified review before a hosted or commercial launch.
