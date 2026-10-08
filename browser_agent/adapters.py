import re
import json


class BaseAdapter:
    name = "generic"
    title_selector = "h1"
    company_selector = "[data-job-company]"

    async def title(self, page):
        # Structured job data is data only: no instructions or executable code.
        nodes = page.locator('script[type="application/ld+json"]')
        titles = []
        for i in range(min(await nodes.count(), 12)):
            raw = await nodes.nth(i).text_content()
            if not raw or len(raw) > 100000:
                continue
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            records = data if isinstance(data, list) else [data]
            for record in records:
                if isinstance(record, dict):
                    records.extend(record.get("@graph", []) if isinstance(record.get("@graph"), list) else [])
                    if record.get("@type") == "JobPosting" and isinstance(record.get("title"), str):
                        titles.append(record["title"][:500])
        if len(titles) == 1:
            return titles[0].strip()
        if len(titles) > 1:
            return ""  # A results page cannot verify one particular role.
        el = page.locator(self.title_selector)
        for i in range(min(await el.count(), 8)):
            if await el.nth(i).is_visible():
                return (await el.nth(i).inner_text()).strip()[:500]
        return ""

    async def company(self, page):
        el = page.locator(self.company_selector)
        return (
            (await el.first.inner_text()).strip()
            if await el.count()
            else page.url.split("/")[2].split(".")[0]
        )

    async def apply_link(self, page):
        el = page.get_by_role("link", name=re.compile(r"^apply(?: now| for.*| to.*)?$", re.I))
        visible = [el.nth(i) for i in range(min(await el.count(), 12)) if await el.nth(i).is_visible()]
        # Multiple distinct Apply destinations are ambiguous; never pick another role.
        targets = {await item.get_attribute("href") for item in visible}
        return targets.pop() if len(targets) == 1 else None

    async def next_button(self, page):
        el = page.get_by_role(
            "button", name=re.compile(r"^(next|continue|save and continue|review|review application)$", re.I)
        )
        for i in range(await el.count()):
            if await el.nth(i).is_visible() and await el.nth(i).is_enabled():
                return el.nth(i)
        return None

    async def apply_button(self, page):
        # Entry buttons are distinguished from a form's final Apply control.
        controls = page.locator(
            'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select, [role="combobox"]'
        )
        if await controls.filter(visible=True).count():
            return None
        buttons = page.get_by_role("button", name=re.compile(r"^apply(?: now| for.*| to.*)?$", re.I))
        for i in range(await buttons.count()):
            if await buttons.nth(i).is_visible() and await buttons.nth(i).is_enabled():
                return buttons.nth(i)
        return None

    async def submit_button(self, page):
        el = page.get_by_role(
            "button", name=re.compile(r"^(submit|submit application|send application|apply)$", re.I)
        )
        inputs = page.locator('input[type="submit"]').filter(visible=True)
        for i in range(await el.count()):
            if await el.nth(i).is_visible() and await el.nth(i).is_enabled():
                return el.nth(i)
        for i in range(await inputs.count()):
            value = await inputs.nth(i).get_attribute("value") or ""
            if re.fullmatch(r"submit(?: application)?|send application|apply(?: now)?", value, re.I):
                return inputs.nth(i)
        return None

    async def manual_challenge(self, page):
        return (
            await page.locator(
                'input[type=password], input[autocomplete="one-time-code"], input[name*="password" i], input[name*="passcode" i], iframe[src*="captcha"], [data-captcha], [data-login]'
            ).count()
            > 0
        )

    async def confirmation(self, page):
        # Use known confirmation containers, never arbitrary job-description text.
        el = page.locator(
            '[data-confirmation], [data-automation-id="congratulationsMessage"], .application-confirmation, .post-application, #application_confirmation'
        )
        for i in range(await el.count()):
            if await el.nth(i).is_visible():
                text = await el.nth(i).inner_text()
                if re.search(
                    r"(application (submitted|received)|thank you for applying|successfully submitted)",
                    text,
                    re.I,
                ):
                    return text[:1500]
        return None

    async def expand_records(self, page, profile):
        for group, collection in (("education", "education"), ("employment", "employment")):
            # Mock / semantic data attributes; custom production repeaters fall back to user.
            records = page.locator(f'[data-record-group="{group}"]')
            if not await records.count():
                continue
            needed = len(profile.get(collection, []))
            while await records.count() < needed:
                button = page.get_by_role("button", name=re.compile(f"^Add (?:another )?{group}$", re.I))
                if not await button.count():
                    break
                before = await records.count()
                await button.first.click()
                if await records.count() <= before:
                    break


class WorkdayAdapter(BaseAdapter):
    name = "workday"
    title_selector = '[data-automation-id="jobPostingHeader"], h1, h2[data-automation-id="jobPostingHeader"]'
    company_selector = '[data-automation-id="companyName"], [data-job-company]'

    async def apply_link(self, page):
        el = page.locator('[data-automation-id="adventureButton"]')
        if await el.count():
            return await el.first.get_attribute("href")
        return await super().apply_link(page)


class GreenhouseAdapter(BaseAdapter):
    name = "greenhouse"
    title_selector = "h1.app-title, h1"
    company_selector = ".company-name, [data-job-company]"


class LeverAdapter(BaseAdapter):
    name = "lever"
    title_selector = ".posting-headline h2, h1"
    company_selector = ".main-header-logo img[alt], [data-job-company]"

    async def company(self, page):
        return page.url.split("/")[3]


class GenericAdapter(BaseAdapter):
    """Semantic HTML controls; never grants URLs, tools, or network permissions."""

    title_selector = '[data-job-title], main h1, article h1, h1, [itemprop="title"]'


class AshbyAdapter(GenericAdapter):
    name = "ashby"


class SmartRecruitersAdapter(GenericAdapter):
    name = "smartrecruiters"
    title_selector = 'h1.job-title, [itemprop="title"], h1'


class ICIMSAdapter(GenericAdapter):
    name = "icims"
    title_selector = ".iCIMS_Header h1, h1, [data-job-title]"


ADAPTERS = {
    "workday": WorkdayAdapter,
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "mock": BaseAdapter,
    "generic": GenericAdapter,
    "ashby": AshbyAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
    "icims": ICIMSAdapter,
}
