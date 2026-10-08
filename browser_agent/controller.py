from playwright.async_api import async_playwright
from browser_agent.policy import PolicyError
from browser_agent.parser import parse_form
import json


class BrowserController:
    """No arbitrary evaluate/click/URL/file APIs are exposed to AI or HTTP callers."""

    def __init__(self, policy, headless=False):
        self.policy = policy
        self.headless = headless
        self.browser = self.context = self.page = self.pw = None
        self.screenshot = None

    async def start(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            accept_downloads=False, service_workers="block", viewport={"width": 1280, "height": 900}
        )
        await self.context.clear_permissions()
        await self.context.route("**/*", self._route)
        await self.context.route_web_socket("**/*", lambda ws: ws.close())
        self.page = await self.context.new_page()
        self.page.set_default_timeout(8000)
        self.page.set_default_navigation_timeout(20000)
        self.context.on("page", self._block_popup)
        self.page.on("download", lambda download: download.cancel())
        self.page.on("dialog", lambda dialog: dialog.dismiss())
        # File chooser handling only accepts memory-backed registered documents.
        self.page.on("filechooser", lambda chooser: chooser.set_files([]))

    async def _block_popup(self, page):
        if page != self.page:
            await page.close()

    async def _route(self, route):
        req = route.request
        if not self.policy.request_allowed(req.url, req.resource_type, req.method):
            self.policy.blocked.append(
                {"kind": req.resource_type, "reason": "Blocked out-of-workflow request"}
            )
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def navigate(self, url):
        self.policy.navigation(url)
        await self.page.goto(url, wait_until="domcontentloaded")
        self.policy.navigation(self.page.url)

    async def inspect(self):
        self.policy.interaction(self.page.url)
        return await parse_form(self.page)

    async def snapshot(self):
        if self.page and not self.page.is_closed():
            self.screenshot = await self.page.screenshot(type="jpeg", quality=65)
        return self.screenshot

    def locator(self, field):
        # CSS attribute escaping uses JSON string literals, never page-provided selectors.
        return self.page.locator(f"[data-agent-field={json.dumps(field.key)}]")

    async def fill(self, field, answer):
        self.policy.interaction(self.page.url)
        el = self.locator(field)
        value = str(answer)
        if field.kind == "radio":
            match = self.page.get_by_label(value, exact=True)
            if await match.count() == 1:
                await match.check()
            else:
                for i in range(await el.count()):
                    if (await el.nth(i).get_attribute("value") or "").casefold() == value.casefold():
                        await el.nth(i).check()
                        return
                raise ValueError("Radio option not found; choose an available option.")
        elif field.kind == "checkbox":
            if value.casefold() not in ("yes", "no", "true", "false"):
                raise ValueError("Checkbox answer must be Yes or No.")
            await el.set_checked(value.casefold() in ("yes", "true"))
        elif field.kind.startswith("select"):
            labels = [x.strip() for x in value.split(";")] if field.kind == "select-multiple" else value
            await el.select_option(label=labels)
        elif field.kind == "combobox":
            await el.fill(value)
            option = self.page.get_by_role("option", name=value, exact=True)
            await option.click()
        elif field.kind == "file":
            raise PolicyError("File fields require a registered document ID.")
        elif field.kind == "password":
            raise PolicyError("Login is manual.")
        else:
            await el.fill(value)

    async def upload(self, field, document_id):
        from backend.app.documents import document_payload

        self.policy.interaction(self.page.url)
        payload = document_payload(document_id)  # no filesystem paths accepted
        await self.locator(field).set_input_files(payload)

    async def click_next(self, button):
        self.policy.interaction(self.page.url)
        text = (await button.inner_text()).casefold().strip()
        if text not in ("next", "continue", "save and continue", "review", "review application"):
            raise PolicyError("Only navigation controls are allowed before review.")
        await button.click()
        self.policy.navigation(self.page.url)

    async def submit(self, button):
        self.policy.interaction(self.page.url)
        self.policy.require_submit()
        await button.click(no_wait_after=True)

    async def stop(self):
        self.policy.stopped = True
        await self.close()

    async def close(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.pw:
            await self.pw.stop()
            self.pw = None
        self.screenshot = None
