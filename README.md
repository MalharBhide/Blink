# ⚡ Blink

**Apply for internships in the _blink_ of an eye.**

Fill out your profile once, upload your resume, and let Blink help with repetitive internship application forms. It asks you about missing answers and **waits for your approval before submitting**.

Blink runs **on your own computer**. There is no account to create and no shared applicant database. GitHub hosts the source code, not the running website or your information.

> **Link support:** paste a direct public HTTPS internship link from an employer or application portal. Blink uses a general form reader, plus platform adapters for Workday, Greenhouse, Lever, Ashby, SmartRecruiters, iCIMS, Avature, and Oracle Recruiting. The practice portal and unfamiliar-site HTML forms are tested end to end. Employer-specific forms remain experimental: accepting a link does not guarantee Blink can finish every application.

## Open Blink

### First time

1. **Download Blink.** On [the repository page](https://github.com/MalharBhide/Blink), click **Code → Download ZIP**, then unzip it. Keep the folder somewhere private on your computer, preferably outside iCloud Drive or other synced folders. If you already have the project folder, use that. On macOS, choose **Keep Downloaded** in Finder if the folder is in iCloud Drive.
2. **Install its two prerequisites** if you don't already have them: [Python](https://www.python.org/downloads/) **3.12 or newer**, and [Node.js](https://nodejs.org/en/download) **22.12 or newer**. Choose the Node.js LTS installer. On Windows, check **Add Python to PATH** in the Python installer. Close and reopen any old terminal windows afterward.
3. **Open the Blink folder** and start the launcher for your computer:

   | Computer | Open this file                          |
   | -------- | --------------------------------------- |
   | macOS    | Double-click **Launch Blink.command**   |
   | Windows  | Double-click **Launch Blink.bat**       |
   | Linux    | Run **Launch Blink.sh** from a terminal |

4. **Wait for setup.** The first launch downloads the required components and application browser, then prepares the website. It needs an internet connection and may take a few minutes. Later launches reuse what's installed.
5. **Your browser opens automatically**, with your private workspace unlocked. You do **not** need to find an access-code file or start several servers.

You can close the launcher window after the website opens. Blink keeps running in the background.

### Every time after that

Open **Launch Blink** again. It reconnects to your running workspace, or starts it if needed. Your saved profile and documents are still there.

The website normally runs at **http://127.0.0.1:8000**. This address works only on the computer running Blink. If the page is locked, reopen the launcher. Refreshing a signed-in tab keeps your session; restarting Blink locks it again.

To shut it down, open **Stop Blink.command** on macOS or **Stop Blink.bat** on Windows. On Linux, run `./Launch\ Blink.sh --stop`. Stopping Blink keeps your saved information.

### If double-clicking doesn't work

Open a terminal **in the Blink folder** and run:

```bash
python3 scripts/launch.py
```

On Windows, use `py -3 scripts\launch.py` instead. The launcher explains missing prerequisites and startup problems. You never need to disable browser security settings or use an administrator account to access the website.

## Your first application

1. Choose **Add your details**. Start with your name, contact information, and education. Everything is optional. Your changes save automatically; look for **All changes saved securely on this device**. You can also click **Save profile**.
2. Choose **Upload your resume** and select a PDF or Word (`.docx`) file. The first resume becomes your default. You can keep several resumes, choose one for each application, and download your saved documents.
3. On **Overview**, paste a direct internship job link. To learn how Blink works first, choose **Try the local test portal**. Use synthetic information for practice; do not submit real employer forms just to test the app.
4. Watch **Agent workspace**. Blink fills information it knows and asks you for unfamiliar answers in chat. Only choose **Remember this answer** when you want it reused.
5. If the employer opens a different application page, Blink asks you to **confirm that exact destination** before continuing. Confirm only links belonging to this internship. This permission stays with that application.
6. **Review everything**, including where the form will send your information, edit any answers you want to change, wait for the updated review, then choose **Approve & submit**. Blink records a successful application only after it finds confirmation.
7. Check **Application history** to see progress or resume an interrupted application.

If the connection drops, Blink keeps your unsaved profile draft in the current tab and tries to reconnect. Keep that tab open until your changes are saved.

**Pause** puts an application on hold. **Stop** halts the agent and closes its application browser. **Lock workspace** hides your profile and locks this browser; it does not cancel an application already running.

## Which internship links can I use?

Use the direct posting or application link, rather than a company's homepage, a search results page, or your account dashboard. Job IDs in links such as `...?jobId=123` are preserved. The agent verifies an internship title before filling anything; ambiguous roles such as Summer Analyst need your confirmation.

On unfamiliar sites, Blink can read labeled text fields, dropdowns, radio buttons, checkboxes, and upload controls. It supports ordinary HTML forms that submit to an explicitly approved endpoint, as well as the tested practice workflow. Apply buttons and new application steps can lead to another exact page after your confirmation.

Workday links using either `/job/` or `/details/` are recognized. Its Apply button is used inside the page, then **Apply Manually** is selected. For Oracle links ending in `/apply/email`, Blink first opens the associated listing to verify the role. Avature links can reach only the selected job's login screen. Necessary public scripts, translations, and job metadata have narrowly scoped read permissions.

These adapters **do not yet complete account sign-in, Oracle email verification, or employer-specific draft/save APIs**. Opening an application screen is not a completed application. Those flows may still be blocked even if you interact manually. Blink explains the unsupported step and does not collect passwords or bypass CAPTCHA.

If an older attempt was incorrectly rejected, open it in **Application history → Agent workspace → Check link again**. This rechecks the original job with fresh permissions and preserves the prior attempt's answers in encrypted history. Paused attempts use **Continue**. Submitted or uncertain submissions cannot be retried.

When a portal needs manual completion, the workspace offers its link, your saved documents, and copy buttons for reviewed answers. Opening that link uses your own browser and leaves the restricted agent paused.

Some portals require custom APIs, third-party scripts, embedded forms, accounts, or CAPTCHA. Those can still pause. Blink keeps its browser restrictions active and tells you when it cannot continue safely. It cannot guarantee automatic completion on every employer's website.

## AI help is optional

You can use saved-profile filling, remembered answers, and the practice application without an OpenAI key.

For AI-assisted chat and written drafts, open the `.env` file in your local Blink folder using a text editor. Set `OPENAI_API_KEY` to your own key, save it, then **Stop Blink** and **Launch Blink** again. OpenAI usage may cost money. Never share that file or upload it to GitHub.

Written drafts need your review. Blink does not invent experience, grades, work authorization, or other personal facts.

## Your information stays private

- Your profile, saved answers, and uploaded documents are stored **encrypted on your computer**. They are excluded from GitHub.
- The website accepts local connections only. Opening it requires a private access code or an owner-created, one-use launch link that expires after two minutes. The launcher handles this automatically; your permanent code is never placed in the link.
- Blink's agent gets its own isolated application browser. It cannot control your desktop, your normal browser tabs, email, or unrelated websites.
- Employer forms receive the information you enter and may save it before final submission. When optional AI is enabled, OpenAI receives the limited context used for that feature.
- Someone with administrator access, your OS account, or your private keys can still access your local information. Keep your device secure. On a shared computer, use your own OS account and a private folder.

**Do not delete `.data` to fix a startup issue.** It contains your saved information and encryption key. Losing that key can make your data unreadable. Back up that folder securely.

[Read the security and privacy details](docs/SECURITY.md).

## Need help?

| What you see                                          | What to do                                                                                                 |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| “This site can't be reached”                          | Open **Launch Blink** and wait for it to say it's ready. A bookmarked link cannot start the app by itself. |
| “Your workspace is locked” or an expired opening link | Open **Launch Blink** again. It creates a fresh private opening link.                                      |
| Python or Node.js is missing                          | Install the two prerequisites above, then reopen the launcher.                                             |
| Setup stalls or files time out                       | Check free disk space. For an iCloud folder, choose **Keep Downloaded**, wait for downloads, then relaunch. Blink checks and repairs missing components. |
| Setup cannot download a component                     | Check your internet connection, then launch again. Your saved data is not erased.                          |
| A local port is already in use                        | Close an earlier Blink development server. The launcher will not take over another program's port.         |
| Employer form pauses                                  | Read the explanation in chat. Login and CAPTCHA need your help; some workflows aren't supported yet.       |
| Submission cannot be confirmed                        | Check the employer's portal yourself. Blink blocks automatic resubmission to avoid duplicates.             |

If you report a problem on GitHub, describe the steps using fake information. **Never attach a resume, applicant database, access code, key, or private screenshot.**

## For developers

The [developer guide](docs/DEVELOPMENT.md) covers separate frontend/backend development, API configuration, migrations, tests, and the architecture. Normal use needs only **Launch Blink**.
