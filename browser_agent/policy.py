"""Exact application scopes, independent of platform names and AI/page instructions."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit, unquote, quote, parse_qsl, urlencode
import ipaddress
import re
import socket
import hashlib


class PolicyError(ValueError):
    pass


TRACKING = {"source", "ref", "referrer", "gh_src", "lever-source", "utm", "trk"}
UNRELATED = re.compile(
    r"(?:^|/)(?:account|accounts|login|signin|sign-in|signup|sign-up|register|profile|"
    r"dashboard|settings|inbox|mail|banking|payments|billing|logout|oauth|admin)(?:/|$)",
    re.I,
)


def canonical(url):
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError as exc:
        raise PolicyError("Invalid URL.") from exc
    if p.username or p.password or any(ord(c) < 32 for c in url):
        raise PolicyError("Credentials and control characters are not accepted in URLs.")
    path = unquote(p.path).rstrip("/")
    if any(c in path for c in ("\\", "\x00", "%")) or "/../" in f"{path}/" or "/./" in f"{path}/":
        raise PolicyError("Invalid URL path.")
    host = (p.hostname or "").encode("idna").decode().lower()
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and not (p.scheme.lower() == "https" and port == 443):
        netloc += f":{port}"
    # Preserve exact functional queries, including signed URLs. Identity matching
    # separately ignores tracking; navigation never discards or reorders job IDs.
    parse_qsl(p.query, keep_blank_values=True, max_num_fields=60)
    query = p.query
    return urlunsplit((p.scheme.lower(), netloc, quote(path, safe="/-._~!$&'()*+,;=:@"), query, ""))


def job_login_for(url):
    p = urlsplit(canonical(url))
    return (
        p.scheme == "https"
        and p.port in (None, 443)
        and (p.hostname or "").endswith(".avature.net")
        and re.fullmatch(r"/[a-z]{2}_[A-Z]{2}/careers/Login", p.path) is not None
        and re.fullmatch(r"jobId=\d{1,12}", p.query) is not None
    )


def platform_for(url, mock=False):
    p = urlsplit(canonical(url))
    if (
        mock
        and p.scheme == "http"
        and p.netloc in ("127.0.0.1:8001", "localhost:8001")
        and re.fullmatch(r"/mock/jobs/[\w-]+", p.path)
    ):
        return "mock"
    if p.scheme != "https" or p.port not in (None, 443) or not p.hostname:
        raise PolicyError("Use a direct public HTTPS internship link.")
    if UNRELATED.search(unquote(p.path)) and not job_login_for(url):
        raise PolicyError("Account and unrelated personal sections are blocked.")
    if not p.path and not p.query:
        raise PolicyError("Paste the direct internship listing, rather than a website homepage.")
    host = p.hostname
    if host.endswith(".myworkdayjobs.com") and re.search(r"/(?:job|details)/", p.path):
        return "workday"
    if "/hcmUI/CandidateExperience/" in p.path and re.search(r"/job/\d+", p.path):
        return "oracle"
    if host.endswith(".avature.net") and (re.search(r"/JobDetail/\d+", p.path, re.I) or job_login_for(url)):
        return "avature"
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io") and re.fullmatch(
        r"/[^/]+/jobs/\d+(?:/apply)?", p.path
    ):
        return "greenhouse"
    if host == "jobs.lever.co" and re.fullmatch(r"/[^/]+/[a-f\d-]{36}(?:/apply)?", p.path):
        return "lever"
    if host == "jobs.ashbyhq.com":
        return "ashby"
    if host == "jobs.smartrecruiters.com":
        return "smartrecruiters"
    if host.endswith(".icims.com"):
        return "icims"
    return "generic"


def public_host(host):
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise PolicyError("The job hostname cannot be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise PolicyError("Private, loopback, link-local, and reserved network destinations are blocked.")


def job_key(url, mock=False):
    url = canonical(url)
    platform = platform_for(url, mock)
    p = urlsplit(url)
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(p.query, keep_blank_values=True)
            if k.casefold() not in TRACKING and not k.casefold().startswith("utm_")
        )
    )
    identity = p.path + ("?" + query if query else "")
    if platform == "workday":
        match = re.search(r"_([\w-]+)(?:/apply(?:/applyManually)?)?$", p.path)
        identity = match.group(1) if match else identity
    elif platform == "oracle":
        identity = re.split(r"(/job/\d+)", p.path, maxsplit=1)[0] + re.search(r"/job/\d+", p.path)[0]
    elif platform == "avature":
        ident = (
            dict(parse_qsl(p.query))["jobId"]
            if job_login_for(url)
            else re.search(r"/JobDetail/(\d+)", p.path, re.I)[1]
        )
        base = p.path.rsplit("/", 1)[0] if job_login_for(url) else p.path.rsplit("/", 2)[0]
        identity = base + "/JobDetail/" + ident
    elif platform in ("lever", "greenhouse"):
        identity = p.path.removesuffix("/apply") + ("?" + query if query else "")
    identity_host = (
        "greenhouse" if platform == "greenhouse" else "mock.local" if platform == "mock" else p.hostname
    )
    return hashlib.sha256(f"{identity_host}:{identity}".encode()).hexdigest()


@dataclass
class WorkflowPolicy:
    initial_url: str
    mock: bool = False
    verified: bool = False
    submission_permit: bool = False
    stopped: bool = False
    allowed_pages: set = field(default_factory=set)
    blocked: list = field(default_factory=list)
    submission_targets: set = field(default_factory=set)
    oracle_site: str | None = None

    def __post_init__(self):
        self.initial_url = canonical(self.initial_url)
        self.platform = platform_for(self.initial_url, self.mock)
        self.origin = urlsplit(self.initial_url)
        self.root = self.origin.path
        self.verification_url = self.initial_url
        self.allowed_pages.add(self.initial_url)
        if self.platform != "mock":
            public_host(self.origin.hostname)
        # Computed transitions are restricted to this exact job, not its ATS domain.
        p = self.origin
        if not p.path.endswith("/apply") and not job_login_for(self.initial_url):
            self.allowed_pages.add(urlunsplit((p.scheme, p.netloc, p.path + "/apply", p.query, "")))
        if all(k.casefold() in TRACKING or k.casefold().startswith("utm_") for k, _ in parse_qsl(p.query)):
            self.allowed_pages.add(urlunsplit((p.scheme, p.netloc, p.path, "", "")))
            self.allowed_pages.add(urlunsplit((p.scheme, p.netloc, p.path + "/apply", "", "")))
        if self.platform == "mock":
            self.allowed_pages.add(urlunsplit((p.scheme, p.netloc, p.path + "/confirmation", "", "")))
            self.submission_targets.add(
                (urlunsplit((p.scheme, p.netloc, p.path + "/submit", "", "")), "POST")
            )
        if self.platform == "workday":
            listing = re.sub(r"/apply(?:/applyManually)?$", "", p.path)
            self.verification_url = urlunsplit((p.scheme, p.netloc, listing, p.query, ""))
            self.allowed_pages.add(self.verification_url)
        if self.platform == "avature":
            ident = (
                dict(parse_qsl(p.query))["jobId"]
                if job_login_for(self.initial_url)
                else re.search(r"/JobDetail/(\d+)", p.path, re.I)[1]
            )
            base = p.path.rsplit("/", 1)[0] if job_login_for(self.initial_url) else p.path.rsplit("/", 2)[0]
            self.job_login_url = urlunsplit((p.scheme, p.netloc, base + "/Login", "jobId=" + ident, ""))
            self.verification_url = urlunsplit((p.scheme, p.netloc, base + "/JobDetail/" + ident, "", ""))
            self.allowed_pages.update((self.job_login_url, self.verification_url))
        if self.platform == "oracle":
            path = re.split(r"(/job/\d+)", p.path, maxsplit=1)
            job_path = path[0] + path[1]
            self.verification_url = urlunsplit((p.scheme, p.netloc, job_path, "", ""))
            self.allowed_pages.add(self.verification_url)
            self.allowed_pages.add(self.verification_url + "/apply/email")

    def activate_portal(self, url):
        """An approved employer-to-ATS transition selects that portal's rules."""
        self.navigation(url)
        if self.platform == "mock":
            return
        detected = platform_for(url)
        p = urlsplit(canonical(url))
        if detected == "generic" or (detected == self.platform and p.netloc == self.origin.netloc):
            return
        scope = WorkflowPolicy(url)
        self.platform, self.origin, self.root = scope.platform, scope.origin, scope.root
        self.oracle_site = None
        self.job_login_url = getattr(scope, "job_login_url", None)
        self.allowed_pages.update(scope.allowed_pages)
        # This switches only public resource rules, never write permissions.
        self.submission_permit = False

    def configure_oracle_site(self, site_number):
        # Untrusted bootstrap data may only select this bounded public settings
        # endpoint. It cannot supply a URL or enable application/account APIs.
        if self.platform == "oracle" and re.fullmatch(r"CX_\d{1,10}", site_number or ""):
            self.oracle_site = site_number

    def validate_destination(self, url):
        url = canonical(url)
        p = urlsplit(url)
        # The local test exception never extends to other localhost paths/ports.
        if self.platform == "mock":
            if url not in self.allowed_pages and url not in {u for u, _ in self.submission_targets}:
                raise PolicyError("The practice portal is confined to its exact mock requisition.")
        else:
            platform_for(url)  # scheme, port, unrelated sections
            if p.netloc == self.origin.netloc:
                if self.platform == "avature":
                    target = (
                        dict(parse_qsl(p.query)).get("jobId")
                        if job_login_for(url)
                        else (
                            re.search(r"/JobDetail/(\d+)", p.path, re.I)[1]
                            if re.search(r"/JobDetail/(\d+)", p.path, re.I)
                            else None
                        )
                    )
                    original = dict(parse_qsl(urlsplit(self.job_login_url).query))["jobId"]
                elif self.platform == "oracle":
                    found = re.search(r"/job/(\d+)", p.path)
                    target = found[1] if found else None
                    original = re.search(r"/job/(\d+)", self.root)[1]
                elif self.platform == "workday":
                    found = re.search(r"_([\w-]+)(?:/apply(?:/applyManually)?)?$", p.path)
                    current = re.search(r"_([\w-]+)(?:/apply(?:/applyManually)?)?$", self.root)
                    target = found[1] if found else None
                    original = current[1] if current else None
                else:
                    target = original = None
                if target and original and target != original:
                    raise PolicyError(
                        "This destination identifies a different job, not the selected internship."
                    )
            public_host(p.hostname)
        return url

    def approve_destination(self, url, *, user_confirmed=False, submission=False):
        """Only orchestrator human-confirmation paths may extend the exact URL set."""
        if self.stopped or not user_confirmed:
            raise PolicyError("A new workflow destination requires explicit user confirmation.")
        url = self.validate_destination(url)
        if submission:
            if not self.verified:
                raise PolicyError("Submission destinations require a verified internship.")
            self.submission_targets.add((url, "POST"))
        else:
            self.allowed_pages.add(url)
        return url

    def permit_apply_link(self, url):
        url = canonical(url)
        if url not in self.allowed_pages or not self.verified:
            raise PolicyError("Confirm this application's new destination before proceeding.")
        return url

    def navigation(self, url):
        if self.stopped:
            raise PolicyError("Agent stopped.")
        if job_login_for(url) and not self.verified:
            raise PolicyError("Job-specific login requires a verified internship first.")
        if canonical(url) not in self.allowed_pages:
            raise PolicyError("Navigation outside this application's approved URLs was blocked.")

    def interaction(self, url):
        self.navigation(url)
        if not self.verified:
            raise PolicyError("Form actions require a verified internship.")

    def prepare_submission(self, page_url, action_url, method):
        self.interaction(page_url)
        action_url = canonical(action_url)
        if method.upper() != "POST":
            raise PolicyError("Automatic submission only supports explicit POST forms.")
        # Current approved pages are safe exact form targets; unfamiliar endpoints ask first.
        if action_url not in self.allowed_pages and (action_url, "POST") not in self.submission_targets:
            raise PolicyError("Confirm the exact form submission destination first.")
        self.submission_targets.add((action_url, "POST"))
        return action_url

    def static_redirect(self, url, resource_type):
        p = urlsplit(canonical(url))
        return resource_type in ("script", "stylesheet", "font", "image") or (
            self.platform == "workday"
            and resource_type in ("xhr", "fetch")
            and re.fullmatch(
                r"/wday/asset/(?:candidate-experience-jobs|candidate-experience-apply-flow)/(?:[\w.-]+/)?compiled-lang/[\w-]+/[\w-]+\.json",
                p.path,
            )
            is not None
        )

    def request_allowed(self, url, resource_type, method="GET"):
        if self.stopped:
            return False
        try:
            clean = canonical(url)
            p = urlsplit(clean)
        except (ValueError, PolicyError):
            return False
        if p.scheme == "data" and resource_type == "image":
            return True
        if method not in ("GET", "HEAD"):
            return (
                self.verified
                and self.submission_permit
                and (clean, method) in self.submission_targets
                and resource_type in ("document", "fetch", "xhr")
            )
        origins = {(urlsplit(u).scheme, urlsplit(u).netloc) for u in self.allowed_pages}
        if (p.scheme, p.netloc) not in origins:
            if p.scheme != "https" or p.port not in (None, 443):
                return False
            shard = re.search(r"\.(wd\d+)\.myworkdayjobs\.com$", self.origin.hostname or "")
            if (
                self.platform == "workday"
                and shard
                and p.hostname
                in (
                    shard[1] + ".myworkday.com",
                    "prod-" + shard[1] + ".myworkdaycdn.com",
                    shard[1] + ".myworkdaycdn.com",
                )
            ):
                if resource_type in ("xhr", "fetch"):
                    return (
                        p.scheme == "https"
                        and method == "GET"
                        and not p.query
                        and self.static_redirect(clean, resource_type)
                    )
                return (
                    p.scheme == "https"
                    and method == "GET"
                    and not p.query
                    and resource_type in ("script", "stylesheet", "font", "image")
                    and p.path.startswith("/wday/asset/")
                    and not p.path.startswith("/wday/asset/client-analytics/")
                )
            if self.platform == "avature" and p.hostname == "templates-static-assets.avacdn.net":
                return (
                    p.scheme == "https"
                    and method == "GET"
                    and not p.query
                    and resource_type in ("script", "stylesheet", "font", "image")
                    and p.path.startswith(("/cssLibrary/", "/jsLibrary/", "/assets/fonts/"))
                )
            if self.platform == "oracle" and p.hostname == "static.oracle.com":
                return (
                    p.scheme == "https"
                    and method == "GET"
                    and (not p.query or (resource_type == "font" and re.fullmatch(r"[a-f0-9]{32}", p.query)))
                    and resource_type in ("script", "stylesheet", "font", "image")
                    and p.path.startswith(("/cdn/jet/", "/cdn/fa/oj-hcm-ce/"))
                )
            return (
                self.platform == "workday"
                and p.scheme == "https"
                and p.hostname in ("wd5.myworkdaycdn.com", "wd1.myworkdaycdn.com", "wd3.myworkdaycdn.com")
                and resource_type in ("script", "stylesheet", "font", "image")
                and method == "GET"
                and not p.query
            )
        if resource_type == "document":
            return clean in self.allowed_pages and (not job_login_for(clean) or self.verified)
        if self.platform == "mock":
            return clean in self.allowed_pages
        if UNRELATED.search(unquote(p.path)):
            return (
                job_login_for(clean)
                and clean in self.allowed_pages
                and self.verified
                and resource_type in ("fetch", "xhr")
            )
        if self.platform == "oracle":
            lang = self.root.split("/CandidateExperience/", 1)[1].split("/", 1)[0]
            if (
                self.oracle_site
                and p.path == f"/hcmRestApi/CandidateExperience/{lang}/siteSettings/{self.oracle_site}"
            ):
                return method == "GET" and not p.query and resource_type in ("fetch", "xhr")
            if resource_type in ("fetch", "xhr") and method == "GET":
                pairs = parse_qsl(p.query, keep_blank_values=True)
                query = dict(pairs)
                if len(query) != len(pairs):
                    return False
                if p.path == "/hcmRestApi/CandidateExperience/translations":
                    return query == {"language": lang}
                if p.path == "/hcmRestApi/CandidateExperience/globalSettings":
                    return not query
                if self.oracle_site and re.fullmatch(
                    rf"/hcmRestApi/CandidateExperience/{re.escape(lang)}/sites/{self.oracle_site}/page/\d{{1,10}}",
                    p.path,
                ):
                    return set(query) <= {"statusCode", "onlyData"} and all(
                        re.fullmatch(r"[\w-]{1,20}", v) for v in query.values()
                    )
                if p.path == "/hcmRestApi/resources/latest/recruitingCEProfileImportConfigs":
                    return query == {"onlyData": "true"}
                job = re.search(r"/job/(\d+)", self.root)[1]
                if p.path == "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails":
                    return (
                        self.oracle_site is not None
                        and query.get("finder") == f'ById;Id="{job}",siteNumber={self.oracle_site}'
                        and set(query) <= {"finder", "expand", "onlyData"}
                        and query.get("onlyData", "true") in ("true", "false")
                        and re.fullmatch(r"[\w,.]{0,300}", query.get("expand", "")) is not None
                    )
                if p.path == "/hcmRestApi/resources/latest/recruitingCEApplyFlows":
                    return query == {"finder": f'findByRequisitionNumber;RequisitionNumber="{job}"'}
            if p.path.startswith("/hcmUI/CandExpStatic/") and resource_type in ("script", "stylesheet"):
                query = dict(parse_qsl(p.query, keep_blank_values=True))
                keys = {"themeNumber", "lang", "themeVersion", "brandVersion", "brandTlVersion", "siteNumber"}
                return (
                    method == "GET"
                    and set(query) <= keys
                    and all(re.fullmatch(r"[\w.-]{1,30}", v) for v in query.values())
                )
        if self.platform == "workday" and resource_type == "image" and method == "GET" and not p.query:
            site = self.root.strip("/").split("/")[1]
            if p.path in (f"/{site}/assets/logo", f"/{site}/assets/banner"):
                return True
        if resource_type in ("image", "font", "stylesheet", "script"):
            # Static version parameters only; no free-form data-bearing asset URLs.
            safe_query = all(
                k.casefold() in ("v", "version", "hash") and re.fullmatch(r"[\w.-]{1,80}", v)
                for k, v in parse_qsl(p.query)
            )
            return (
                method == "GET"
                and safe_query
                and bool(
                    re.search(r"\.(?:js|css|png|jpe?g|gif|webp|svg|ico|woff2?|ttf)$", p.path, re.I)
                    or p.path.startswith(("/assets/", "/static/", "/resources/", "/wday/asset/"))
                )
            )
        if self.platform == "workday" and p.netloc == self.origin.netloc:
            pieces = self.root.strip("/").split("/")
            site = (
                pieces[1] if len(pieces) > 1 and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", pieces[0]) else pieces[0]
            )
            tenant = self.origin.hostname.split(".")[0]
            cxs = f"/wday/cxs/{tenant}/{site}/"
            endpoint = p.path.removeprefix(cxs)
            slug = re.sub(
                r"/apply(?:/applyManually)?$", "", re.split(r"/(?:job|details)/", self.root, maxsplit=1)[1]
            )
            requisition = re.search(r"_([\w-]+)$", slug)
            info_prefix = f"/wday/calypso/cxs/jobdetails/{tenant}/job/"
            if p.path.startswith(info_prefix) and p.path.endswith("/info") and requisition:
                info_job = re.search(r"_([\w-]+)/info$", p.path)
                return (
                    method == "GET"
                    and not p.query
                    and resource_type in ("fetch", "xhr")
                    and info_job is not None
                    and info_job[1] == requisition[1]
                )
            exact_job = False
            if endpoint.startswith("job/") and requisition:
                candidate = re.sub(r"/apply(?:/applyManually)?$", "", endpoint)
                found = re.search(r"_([\w-]+)$", candidate)
                exact_job = found is not None and found[1] == requisition[1]
            return (
                method == "GET"
                and not p.query
                and resource_type in ("fetch", "xhr")
                and p.path.startswith(cxs)
                and (
                    exact_job
                    or endpoint
                    in (
                        "site",
                        "config",
                        "approot",
                        "sidebar",
                        "sidebar/" + slug,
                        "job/" + slug,
                        "job/" + slug + "/apply",
                    )
                )
            )
        return clean in self.allowed_pages and resource_type in ("fetch", "xhr")

    def require_submit(self):
        if not self.verified or not self.submission_permit or self.stopped:
            raise PolicyError("Final submission requires current explicit user approval.")
