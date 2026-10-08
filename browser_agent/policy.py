"""Fail-closed URL/request policy. No AI or page content can extend this allowlist."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit, unquote
import ipaddress
import re
import socket
import hashlib


class PolicyError(ValueError):
    pass


def canonical(url):
    p = urlsplit(url)
    if p.username or p.password or p.fragment:
        raise PolicyError("Credentials and fragments are not accepted in job URLs.")
    path = unquote(p.path).rstrip("/")
    if any(c in path for c in ("\\", "\x00")) or "/../" in f"{path}/" or "/./" in f"{path}/":
        raise PolicyError("Invalid URL path.")
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))


def platform_for(url, mock=False):
    p = urlsplit(canonical(url))
    if (
        mock
        and p.scheme == "http"
        and p.netloc in ("127.0.0.1:8001", "localhost:8001")
        and re.fullmatch(r"/mock/jobs/[\w-]+", p.path)
    ):
        return "mock"
    if p.scheme != "https" or p.port not in (None, 443):
        raise PolicyError("Only public HTTPS job URLs on supported application portals are accepted.")
    host = p.hostname or ""
    if host.endswith(".myworkdayjobs.com") and "/job/" in p.path:
        return "workday"
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io") and re.fullmatch(
        r"/[^/]+/jobs/\d+", p.path
    ):
        return "greenhouse"
    if host == "jobs.lever.co" and re.fullmatch(r"/[^/]+/[a-f\d-]{36}", p.path):
        return "lever"
    raise PolicyError("Paste a direct Workday, Greenhouse, or Lever job URL. Other portals are not enabled.")


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
    identity = p.path
    if platform == "workday":
        # Location/title/localization can change while the requisition remains the same.
        match = re.search(r"_([\w-]+)$", p.path)
        identity = match.group(1) if match else p.path
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

    def __post_init__(self):
        self.initial_url = canonical(self.initial_url)
        self.platform = platform_for(self.initial_url, self.mock)
        self.origin = urlsplit(self.initial_url)
        self.root = self.origin.path
        self.allowed_pages.add(self.initial_url)
        if self.platform != "mock":
            public_host(self.origin.hostname)
        suffix = "/apply"
        self.allowed_pages.add(self.initial_url + suffix)
        if self.platform == "mock":
            self.allowed_pages.add(self.initial_url + "/confirmation")

    def permit_apply_link(self, url):
        """A link may only select a precomputed path for this exact requisition."""
        url = canonical(url)
        if url not in self.allowed_pages or not self.verified:
            raise PolicyError(
                "Application link leaves the verified requisition. Manual adapter support is required."
            )
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

    def request_allowed(self, url, resource_type, method="GET"):
        if self.stopped:
            return False
        try:
            p = urlsplit(canonical(url))
        except (ValueError, PolicyError):
            return False
        if p.scheme == "data" and resource_type == "image":
            return True
        if p.scheme != self.origin.scheme or p.netloc != self.origin.netloc:
            # Workday's static CDN is read-only. No other cross-origin network calls.
            return (
                self.platform == "workday"
                and p.scheme == "https"
                and p.hostname in ("wd5.myworkdaycdn.com", "wd1.myworkdaycdn.com", "wd3.myworkdaycdn.com")
                and resource_type in ("script", "stylesheet", "font", "image")
                and method == "GET"
            )
        if resource_type == "document":
            if canonical(url) not in self.allowed_pages:
                return False
            return method in ("GET", "HEAD") or (self.verified and self.submission_permit)
        if self.platform == "mock":
            if method not in ("GET", "HEAD"):
                return self.verified and self.submission_permit and p.path == self.root + "/submit"
            return p.path in (self.root, self.root + "/apply", self.root + "/confirmation")
        if resource_type in ("image", "font", "stylesheet", "script"):
            return method == "GET" and bool(
                re.search(r"\.(?:js|css|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|map)$", p.path, re.I)
                or p.path.startswith(("/assets/", "/static/", "/resources/", "/wday/asset/"))
            )
        if self.platform == "workday":
            pieces = self.root.strip("/").split("/")
            site = (
                pieces[1] if len(pieces) > 1 and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", pieces[0]) else pieces[0]
            )
            tenant = self.origin.hostname.split(".")[0]
            cxs = f"/wday/cxs/{tenant}/{site}/"
            endpoint = p.path.removeprefix(cxs)
            if p.path.startswith(cxs) and (endpoint.startswith("job/") or endpoint in ("site", "config")):
                return method == "GET" and (
                    not endpoint.startswith("job/") or endpoint == "job/" + self.root.split("/job/", 1)[1]
                )
            # Employer-specific draft/upload endpoints are deliberately NOT granted wholesale.
            return False
        if self.platform in ("greenhouse", "lever"):
            return method == "GET" and p.path in (self.root, self.root + "/apply")
        return False

    def require_submit(self):
        if not self.verified or not self.submission_permit or self.stopped:
            raise PolicyError("Final submission requires current explicit user approval.")
