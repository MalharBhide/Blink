import re


class BaseAdapter:
    name = "generic"
    title_selector = "h1"
    company_selector = "[data-job-company]"

    async def title(self, page):
        el = page.locator(self.title_selector)
        return (await el.first.inner_text()).strip() if await el.count() else ""

    async def company(self, page):
        el = page.locator(self.company_selector)
        return (
            (await el.first.inner_text()).strip()
            if await el.count()
            else page.url.split("/")[2].split(".")[0]
        )

    async def apply_link(self, page):
        el = page.get_by_role("link", name=re.compile(r"^apply(?: now| for.*)?$", re.I))
        return await el.first.get_attribute("href") if await el.count() else None

    async def next_button(self, page):
        el = page.get_by_role(
            "button", name=re.compile(r"^(next|continue|save and continue|review|review application)$", re.I)
        )
        return el.first if await el.count() else None

    async def submit_button(self, page):
        el = page.get_by_role(
            "button", name=re.compile(r"^(submit|submit application|send application|apply)$", re.I)
        )
        return el.first if await el.count() else None

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
        if not await el.count():
            return None
        text = await el.first.inner_text()
        if re.search(
            r"(application (submitted|received)|thank you for applying|successfully submitted)", text, re.I
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
                await button.first.click()


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


ADAPTERS = {
    "workday": WorkdayAdapter,
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "mock": BaseAdapter,
}
