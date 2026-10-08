from playwright.async_api import async_playwright, Error as PlaywrightError
from browser_agent.policy import PolicyError
from browser_agent.policy import canonical, public_host
from browser_agent.parser import parse_form
import json
import asyncio
from urllib.parse import urlsplit, urljoin
from html.parser import HTMLParser


class OracleBootstrap(HTMLParser):
    def __init__(self):
        super().__init__()
        self.site = None

    def handle_starttag(self, tag, attrs):
        if tag == "base":
            self.site = dict(attrs).get("data-sitenumber")


class BrowserController:
    """No arbitrary evaluate/click/URL/file APIs are exposed to AI or HTTP callers."""

    def __init__(self, policy, headless=False):
        self.policy = policy
        self.headless = headless
        self.browser = self.context = self.page = self.pw = None
        self.screenshot = None
        self.pending_navigation = None
        self.pending_confirmation = None
        self.submission_response_status = None

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
        try:
            await self._guard_request(route)
        except Exception:
            # Playwright fetch diagnostics may contain cookies or headers.
            # Never let those escape into application/server logs.
            self.policy.blocked.append({"kind": "request", "reason": "Portal request failed or timed out"})
            try:
                await route.abort("failed")
            except Exception:
                pass

    async def _guard_request(self, route):
        req = route.request
        permitted = self.policy.request_allowed(req.url, req.resource_type, req.method)
        if permitted and req.method not in ("GET", "HEAD"):
            # Consume the single approved submission attempt before any await.
            # Concurrent website requests cannot reuse the permission.
            self.policy.submission_permit = False
        if req.resource_type == "document":
            # Embedded documents cannot borrow main-page permissions.
            if req.frame != self.page.main_frame:
                permitted = False
            elif not permitted and req.method == "GET":
                # Candidate only; the route is aborted until a human confirms it.
                self.pending_navigation = req.url
        if permitted and urlsplit(req.url).scheme == "https":
            try:
                await asyncio.wait_for(asyncio.to_thread(public_host, urlsplit(req.url).hostname), 8)
            except (PolicyError, TimeoutError):
                permitted = False
        permitted = permitted and not self.policy.stopped
        if not permitted:
            self.policy.blocked.append(
                {"kind": req.resource_type, "reason": "Blocked out-of-workflow request"}
            )
            await route.abort("blockedbyclient")
            return
        # Chromium can follow a redirect without invoking the same route handler
        # again. Fetch one hop, then fulfill; never forward an unchecked Location.
        response = await route.fetch(max_redirects=0, timeout=20000)
        # Versioned static bundles commonly redirect within their approved CDN
        # paths. Follow only read-only asset hops that independently pass policy.
        asset_url = req.url
        for _ in range(4):
            if not (
                req.method == "GET"
                and self.policy.static_redirect(asset_url, req.resource_type)
                and 300 <= response.status < 400
                and response.headers.get("location")
            ):
                break
            target = urljoin(asset_url, response.headers["location"])
            if not (
                self.policy.static_redirect(target, req.resource_type)
                and self.policy.request_allowed(target, req.resource_type, "GET")
            ):
                break
            await asyncio.wait_for(asyncio.to_thread(public_host, urlsplit(target).hostname), 8)
            if self.policy.stopped:
                await route.abort("blockedbyclient")
                return
            response = await route.fetch(
                url=target,
                max_redirects=0,
                timeout=20000,
                headers={
                    "accept": req.headers.get("accept", "*/*"),
                    "user-agent": req.headers.get("user-agent", ""),
                },
            )
            asset_url = target
        if req.method == "POST":
            self.submission_response_status = response.status
        if 300 <= response.status < 400 and response.headers.get("location"):
            if req.resource_type == "document" and req.method == "GET":
                self.pending_navigation = urljoin(req.url, response.headers["location"])
            elif req.method == "POST" and response.status in (301, 302, 303):
                self.pending_confirmation = urljoin(req.url, response.headers["location"])
            self.policy.blocked.append(
                {"kind": req.resource_type, "reason": "Redirect awaits exact workflow approval"}
            )
            await route.abort("blockedbyclient")
            return
        if (
            req.resource_type == "document"
            and self.policy.platform == "oracle"
            and "text/html" in response.headers.get("content-type", "")
        ):
            bootstrap = OracleBootstrap()
            bootstrap.feed((await response.text())[:2000000])
            self.policy.configure_oracle_site(bootstrap.site)
        await route.fulfill(response=response)

    async def navigate(self, url):
        self.policy.navigation(url)
        await asyncio.to_thread(self.policy.activate_portal, url)
        self.pending_navigation = None
        for attempt in range(2):
            self.policy.navigation(url)
            try:
                await self.page.goto(url, wait_until="domcontentloaded")
                break
            except PlaywrightError as exc:
                # Chromium can finish committing a previously aborted document's
                # internal error page during the next approved GET navigation.
                # Retry only this specific race, never a new destination or POST.
                if (
                    attempt
                    or self.pending_navigation
                    or self.policy.stopped
                    or "chrome-error://chromewebdata/" not in str(exc)
                ):
                    raise
                await asyncio.sleep(0.15)
        self.check_current_navigation()

    def check_current_navigation(self):
        try:
            self.policy.navigation(self.page.url)
        except PolicyError:
            # SPA history transitions can change the URL without a request.
            if not self.pending_navigation:
                self.pending_navigation = self.page.url
            raise

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
        self.check_current_navigation()

    async def click_apply(self, button):
        self.policy.interaction(self.page.url)
        controls = self.page.locator(
            'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select, [role="combobox"]'
        )
        if await controls.filter(visible=True).count():
            raise PolicyError("An Apply control beside applicant fields requires final review.")
        self.pending_navigation = None
        await button.click()
        self.check_current_navigation()

    async def choose_application(self, button):
        self.policy.interaction(self.page.url)
        if self.policy.platform != "workday":
            raise PolicyError("Application choices require a scoped platform adapter.")
        choice = self.page.get_by_role("dialog").get_by_role("button", name="Apply Manually", exact=True)
        if await choice.filter(visible=True).count() != 1:
            raise PolicyError("Application entry choice is ambiguous.")
        if await button.inner_text() != "Apply Manually":
            raise PolicyError("Only the manual application entry is supported.")
        self.pending_navigation = None
        await choice.first.click()
        self.check_current_navigation()

    async def submission_form(self, button):
        self.policy.interaction(self.page.url)
        return await button.evaluate("""el => {
            const form = el.form || el.closest('form');
            if (!form || (el.type === 'button' && !form.hasAttribute('action'))) return null;
            return {url: el.hasAttribute('formaction') ? el.formAction : form.action,
                    method: (el.getAttribute('formmethod') || form.method || 'get').toUpperCase()};
        }""")

    async def validate_submission_form(self, button, expected):
        actual = await self.submission_form(button)
        if actual != expected:
            raise PolicyError("The submission destination changed. Review it again before submitting.")
        if actual:
            self.policy.prepare_submission(self.page.url, canonical(actual["url"]), actual["method"])

    async def submit(self, button):
        self.policy.interaction(self.page.url)
        self.policy.require_submit()
        try:
            await button.click(no_wait_after=True)
        except Exception:
            # A blocked receipt redirect can abort click's navigation wait.
            # Its destination still requires separate read-only approval.
            if not self.pending_confirmation:
                raise

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
