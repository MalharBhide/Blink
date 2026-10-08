import asyncio
import time
import re
import json
from html import unescape


class BaseAdapter:
    name = "generic"
    manual_message = (
        "Login or CAPTCHA needs your attention in the dedicated browser. No password is collected by Blink. "
        "If the portal's login request is blocked, that authentication flow is unsupported; cancel and complete it yourself. "
        "Press Continue only after the challenge is complete."
    )
    title_selector = "h1"
    unsupported_message = (
        "This employer's next control or network endpoint is unsupported. Blink paused safely. "
        "Cancel and complete this application yourself if the portal cannot advance within these restrictions."
    )
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
            return unescape(titles[0]).strip()
        if len(titles) > 1:
            return ""  # A results page cannot verify one particular role.
        # CSS comma groups return document order, not selector priority. Prefer
        # a portal's job heading over its earlier global career-site header.
        for selector in self.title_selector.split(","):
            el = page.locator(selector.strip())
            for i in range(min(await el.count(), 8)):
                if await el.nth(i).is_visible():
                    return (await el.nth(i).inner_text()).strip()[:500]
        return ""

    async def wait_ready(self, page, timeout=15):
        """Wait for rendered content, rather than only server-side JSON metadata."""
        deadline = time.monotonic() + timeout
        controls = page.locator('h1, h2, input:not([type="hidden"]), button, select, a').filter(visible=True)
        while time.monotonic() < deadline:
            if await controls.count() and await self.title(page):
                return True
            if await self.manual_challenge(page):
                return True
            await asyncio.sleep(0.2)
        return False

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

    async def application_choice(self, page):
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
            )
            .filter(visible=True)
            .count()
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

    unsupported_message = (
        "Workday's application step needs an account/profile or form API this adapter does not yet support. "
        "Blink opened the application entry but has not completed it. Cancel and finish it yourself."
    )

    async def title(self, page):
        title = await super().title(page)
        if "/apply" in page.url and re.fullmatch(r".*career(?:s)? site", title, re.I):
            return ""  # Global branding does not identify a different job.
        return title

    async def wait_ready(self, page, timeout=15):
        deadline = time.monotonic() + timeout
        header = page.locator('[data-automation-id="jobPostingHeader"]').filter(visible=True)
        while time.monotonic() < deadline:
            if await header.count() or await self.manual_challenge(page):
                return True
            await asyncio.sleep(0.2)
        return False

    async def application_choice(self, page):
        choice = page.get_by_role("dialog").get_by_role("button", name="Apply Manually", exact=True)
        return choice.first if await choice.filter(visible=True).count() else None

    async def apply_link(self, page):
        # Workday's Apply handler opens a modal in its SPA. A fresh navigation
        # to the anchor href can load the listing instead of the application.
        if await self.apply_button(page):
            return None
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


class AvatureAdapter(GenericAdapter):
    name = "avature"
    title_selector = ".article__header__text__title, .article__header h2, main h1, main h2"


class OracleAdapter(GenericAdapter):
    name = "oracle"
    manual_message = (
        "This application needs employer email verification. This adapter can open the email screen, "
        "but does not yet support its verification API. Cancel and complete the application yourself. "
        "Blink has not sent your email or submitted this application."
    )

    async def manual_challenge(self, page):
        if page.url.rstrip("/").endswith("/apply/email"):
            return (
                await page.get_by_role("textbox", name="Email Address", exact=True)
                .filter(visible=True)
                .count()
                > 0
            )
        return await super().manual_challenge(page)

    title_selector = '[data-bind*="jobTitle"], .job-details__title, h1, h2.job-details__title'


ADAPTERS = {
    "workday": WorkdayAdapter,
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "mock": BaseAdapter,
    "generic": GenericAdapter,
    "ashby": AshbyAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
    "icims": ICIMSAdapter,
    "avature": AvatureAdapter,
    "oracle": OracleAdapter,
}
