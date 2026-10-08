# ⚡ Blink

**Apply for internships in the _blink_ of an eye.**

Fill out your profile once, upload your resume, and let Blink help with repetitive internship application forms. It asks you about missing answers and **waits for your approval before submitting**.

Blink runs **on your own computer**. There is no account to create and no shared applicant database. GitHub hosts the source code, not the running website or your information.

> **What works today:** the complete application process is tested with the included practice portal. Workday, Greenhouse, and Lever support is experimental: some employer forms will pause and need your help. Blink cannot complete every employer's application yet.

## Open Blink

### First time

1. **Download Blink.** On [the repository page](https://github.com/MalharBhide/Blink), click **Code → Download ZIP**, then unzip it. Keep the folder somewhere private on your computer. If you already have the project folder, use that.
2. **Install its two prerequisites** if you don't already have them: [Python](https://www.python.org/downloads/) **3.12 or newer**, and [Node.js](https://nodejs.org/en/download) **22.12 or newer**. Choose the Node.js LTS installer. On Windows, check **Add Python to PATH** in the Python installer. Close and reopen any old terminal windows afterward.
3. **Open the Blink folder** and start the launcher for your computer:

   | Computer | Open this file |
   | --- | --- |
   | macOS | Double-click **Launch Blink.command** |
   | Windows | Double-click **Launch Blink.bat** |
   | Linux | Run **Launch Blink.sh** from a terminal |

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

1. Choose **Add your details**. Start with your name, contact information, and education. Everything is optional; click **Save profile** when you're done.
2. Choose **Upload your resume** and select a PDF or Word (`.docx`) file. You can keep several resumes and choose one for each application.
3. On **Overview**, paste a direct internship job link. To learn how Blink works first, choose **Try the local test portal**. Use synthetic information for practice; do not submit real employer forms just to test the app.
4. Watch **Agent workspace**. Blink fills information it knows and asks you for unfamiliar answers in chat. Only choose **Remember this answer** when you want it reused.
5. **Review everything**, edit any answers you want to change, then choose **Approve & submit**. Blink records a successful application only after it finds confirmation.
6. Check **Application history** to see progress or resume an interrupted application.

**Pause** puts an application on hold. **Stop** halts the agent and closes its application browser. **Lock workspace** hides your profile and locks this browser; it does not cancel an application already running.

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

| What you see | What to do |
| --- | --- |
| “This site can't be reached” | Open **Launch Blink** and wait for it to say it's ready. A bookmarked link cannot start the app by itself. |
| “Your workspace is locked” or an expired opening link | Open **Launch Blink** again. It creates a fresh private opening link. |
| Python or Node.js is missing | Install the two prerequisites above, then reopen the launcher. |
| Setup cannot download a component | Check your internet connection, then launch again. Your saved data is not erased. |
| A local port is already in use | Close an earlier Blink development server. The launcher will not take over another program's port. |
| Employer form pauses | Read the explanation in chat. Login and CAPTCHA need your help; some workflows aren't supported yet. |
| Submission cannot be confirmed | Check the employer's portal yourself. Blink blocks automatic resubmission to avoid duplicates. |

If you report a problem on GitHub, describe the steps using fake information. **Never attach a resume, applicant database, access code, key, or private screenshot.**

## For developers

The [developer guide](docs/DEVELOPMENT.md) covers separate frontend/backend development, API configuration, migrations, tests, and the architecture. Normal use needs only **Launch Blink**.
