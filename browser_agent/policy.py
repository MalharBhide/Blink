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
    if UNRELATED.search(unquote(p.path)):
        raise PolicyError("Account and unrelated personal sections are blocked.")
    if not p.path and not p.query:
        raise PolicyError("Paste the direct internship listing, rather than a website homepage.")
    host = p.hostname
    if host.endswith(".myworkdayjobs.com") and "/job/" in p.path:
        return "workday"
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
        match = re.search(r"_([\w-]+)$", p.path)
        identity = match.group(1) if match else identity
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

    def __post_init__(self):
        self.initial_url = canonical(self.initial_url)
        self.platform = platform_for(self.initial_url, self.mock)
        self.origin = urlsplit(self.initial_url)
        self.root = self.origin.path
        self.allowed_pages.add(self.initial_url)
        if self.platform != "mock":
            public_host(self.origin.hostname)
        # Computed transitions are restricted to this exact job, not its ATS domain.
        p = self.origin
        if not p.path.endswith("/apply"):
            self.allowed_pages.add(urlunsplit((p.scheme, p.netloc, p.path + "/apply", p.query, "")))
        if all(k.casefold() in TRACKING or k.casefold().startswith("utm_") for k, _ in parse_qsl(p.query)):
            self.allowed_pages.add(urlunsplit((p.scheme, p.netloc, p.path, "", "")))
            self.allowed_pages.add(urlunsplit((p.scheme, p.netloc, p.path + "/apply", "", "")))
        if self.platform == "mock":
            self.allowed_pages.add(urlunsplit((p.scheme, p.netloc, p.path + "/confirmation", "", "")))
            self.submission_targets.add(
                (urlunsplit((p.scheme, p.netloc, p.path + "/submit", "", "")), "POST")
            )

    def validate_destination(self, url):
        url = canonical(url)
        p = urlsplit(url)
        # The local test exception never extends to other localhost paths/ports.
        if self.platform == "mock":
            if url not in self.allowed_pages and url not in {u for u, _ in self.submission_targets}:
                raise PolicyError("The practice portal is confined to its exact mock requisition.")
        else:
            platform_for(url)  # scheme, port, unrelated sections
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
            return (
                self.platform == "workday"
                and p.scheme == "https"
                and p.hostname in ("wd5.myworkdaycdn.com", "wd1.myworkdaycdn.com", "wd3.myworkdaycdn.com")
                and resource_type in ("script", "stylesheet", "font", "image")
                and method == "GET"
                and not p.query
            )
        if resource_type == "document":
            return clean in self.allowed_pages
        if self.platform == "mock":
            return clean in self.allowed_pages
        if UNRELATED.search(unquote(p.path)):
            return False
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
            if p.path.startswith(cxs) and (endpoint.startswith("job/") or endpoint in ("site", "config")):
                return (
                    method == "GET"
                    and not p.query
                    and (
                        not endpoint.startswith("job/") or endpoint == "job/" + self.root.split("/job/", 1)[1]
                    )
                )
        return clean in self.allowed_pages and resource_type in ("fetch", "xhr")

    def require_submit(self):
        if not self.verified or not self.submission_permit or self.stopped:
            raise PolicyError("Final submission requires current explicit user approval.")
