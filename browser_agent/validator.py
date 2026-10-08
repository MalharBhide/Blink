import re
from dataclasses import dataclass


@dataclass
class JobVerdict:
    status: str
    title: str
    company: str
    location: str
    description: str
    job_id: str = ""


def classify_title(title):
    # Title only: malicious text or unrelated internship mentions cannot validate a role.
    if re.search(r"\binternship (?:program )?(?:manager|coordinator|recruiter)\b", title, re.I):
        return "rejected"
    if re.search(r"\b(intern|internship|internships)\b", title, re.I):
        return "internship"
    if re.search(r"\b(summer analyst|co[- ]?op|undergraduate research)\b", title, re.I):
        return "ambiguous"
    return "rejected"


async def inspect_job(page, adapter):
    title = await adapter.title(page)
    status = classify_title(title)
    # Structured metadata cannot override an explicitly conflicting visible role.
    headers = page.locator(
        f'h1, [data-job-title], [data-automation-id="jobPostingHeader"], {adapter.title_selector}'
    )
    for i in range(min(await headers.count(), 12)):
        if await headers.nth(i).is_visible():
            visible = (await headers.nth(i).inner_text()).strip()
            if (
                re.search(
                    r"\b(engineer|developer|scientist|analyst|manager|director|recruiter|coordinator)\b",
                    visible,
                    re.I,
                )
                and classify_title(visible) == "rejected"
            ):
                status = "rejected"
    body = (await page.locator("body").inner_text())[:24000]
    company = await adapter.company(page)
    loc = page.locator('[data-job-location], [data-automation-id="locations"]')
    location = (await loc.first.inner_text()) if await loc.count() else "Not specified"
    ident = page.locator('[data-job-id], [data-automation-id="requisitionId"]')
    job_id = await ident.first.inner_text() if await ident.count() else ""
    return JobVerdict(status, title, company, location, body, job_id)


async def application_matches_job(page, adapter, verdict):
    def words(text):
        values = set(re.findall(r"[a-z0-9]+", text.casefold())) - {"apply", "application", "for", "to", "the"}
        return {"intern" if x in ("internship", "internships") else x for x in values}

    expected = words(verdict.title)
    visible_headers = page.locator(
        f'h1, [data-job-title], [data-automation-id="jobPostingHeader"], {adapter.title_selector}'
    )
    for i in range(min(await visible_headers.count(), 12)):
        if not await visible_headers.nth(i).is_visible():
            continue
        visible = (await visible_headers.nth(i).inner_text()).strip()
        status = classify_title(visible)
        if status != "rejected":
            actual = words(visible)
            if not (actual <= expected or expected <= actual):
                return False
        elif re.search(
            r"\b(engineer|developer|scientist|analyst|manager|director|recruiter|coordinator)\b",
            visible,
            re.I,
        ):
            return False
    heading = await adapter.title(page)
    if not heading or heading.casefold() in (
        verdict.company.casefold(),
        "join " + verdict.company.casefold(),
    ):
        return True
    if re.fullmatch(
        r"(?:(?:job|your|my) )?application(?: form)?|apply(?: now)?|personal information|my information|my experience|application questions|review(?: application)?|sign in",
        heading,
        re.I,
    ):
        return True
    if classify_title(heading) == "rejected":
        return False

    a, b = words(heading), words(verdict.title)
    return a <= b or b <= a
