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
    body = (await page.locator("body").inner_text())[:24000]
    company = await adapter.company(page)
    loc = page.locator('[data-job-location], [data-automation-id="locations"]')
    location = (await loc.first.inner_text()) if await loc.count() else "Not specified"
    ident = page.locator('[data-job-id], [data-automation-id="requisitionId"]')
    job_id = await ident.first.inner_text() if await ident.count() else ""
    return JobVerdict(classify_title(title), title, company, location, body, job_id)
