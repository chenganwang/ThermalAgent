"""Bounded, permission-gated public HTTPS acquisition into a local draft manifest.

No database/embedding imports. Reuses the existing local intake hash/path helpers.
Approved source metadata is input, never inferred from an HTTP 200 response.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import time
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import uuid4

from services.ingest_service.external_sources import is_path_within, sha256_file

USER_AGENT = "ThermalAgentResearch/1.0 (educational public-document acquisition)"
SCHEMA_VERSION = "open-knowledge-sources-v1"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class AcquisitionError(ValueError):
    def __init__(self, code, message, *, retryable=False, retry_after=None):
        super().__init__(message)
        self.code, self.retryable = code, retryable
        self.retry_after = retry_after


def canonical_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 33 for c in url) or "\\" in url:
        raise AcquisitionError("unsafe_url", "URL contains whitespace/control characters or is too long")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parts.port
    except (ValueError, UnicodeError) as error:
        raise AcquisitionError("unsafe_url", "Invalid HTTPS authority") from error
    if parts.scheme.lower() != "https" or not host or parts.username or parts.password or port not in (None, 443):
        raise AcquisitionError("unsafe_url", "Only credential-free HTTPS on port 443 is permitted")
    if re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f)", url, re.I):
        raise AcquisitionError("unsafe_url", "Encoded control character")
    authority = f"[{host}]" if ":" in host else host
    return urlunsplit(("https", authority, parts.path or "/", parts.query, ""))


def public_addresses(host: str, resolver=socket.getaddrinfo) -> list[str]:
    try:
        addresses = list(dict.fromkeys(row[4][0] for row in resolver(host, 443, type=socket.SOCK_STREAM)))
    except OSError as error:
        raise AcquisitionError("dns_failure", "Public hostname resolution failed", retryable=True) from error
    if not addresses:
        raise AcquisitionError("dns_failure", "No public address resolved", retryable=True)
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise AcquisitionError("private_address", "Private, loopback, link-local, reserved or mixed DNS answers are blocked")
    return addresses


@dataclass
class Response:
    url: str
    status: int
    headers: dict
    body: bytes
    trace: list


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the validated address, but authenticate TLS against hostname.
        # The second DNS lookup in ordinary HTTPSConnection is deliberately avoided.
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            peer = sock.getpeername()[0]
            if ipaddress.ip_address(peer) != ipaddress.ip_address(self.address):
                raise AcquisitionError("peer_mismatch", "Connected peer differs from validated address")
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class HTTPSFetcher:
    def __init__(self, *, interval_seconds=1.0, timeout_seconds=25, max_redirects=4, resolver=socket.getaddrinfo):
        if not 0 <= interval_seconds <= 60 or not 0 < timeout_seconds <= 120 or not 0 <= max_redirects <= 10:
            raise ValueError("Invalid bounded fetch settings")
        self.interval = interval_seconds
        self.timeout = timeout_seconds
        self.max_redirects = max_redirects
        self.resolver = resolver
        self.last_request = {}

    def get(self, url, *, allowed_hosts, max_bytes, before_request=None):
        if not 0 < max_bytes <= 64 * 1024 * 1024:
            raise ValueError("Invalid bounded response size")
        current, trace, visited = canonical_url(url), [], set()
        for _ in range(self.max_redirects + 1):
            host = urlsplit(current).hostname
            if host not in allowed_hosts:
                raise AcquisitionError("redirect_host_blocked", "Host is outside this source's explicit allowlist")
            if current in visited:
                raise AcquisitionError("redirect_cycle", "Redirect cycle")
            visited.add(current)
            delay = before_request(current) if before_request else 0
            wait = max(self.interval, delay or 0) - (time.monotonic() - self.last_request.get(host, -1e20))
            if wait > 0:
                time.sleep(wait)
            addresses = public_addresses(host, self.resolver)
            conn = _PinnedHTTPS(host, addresses[0], self.timeout)
            try:
                deadline = time.monotonic() + self.timeout
                parts = urlsplit(current)
                self.last_request[host] = time.monotonic()
                conn.request("GET", parts.path + ("?" + parts.query if parts.query else ""), headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", "Accept": "application/pdf,text/html,text/plain,application/json;q=0.8"})
                reply = conn.getresponse()
                headers = {key.lower(): value for key, value in reply.getheaders()}
                trace.append({"url": current, "status": reply.status, "connected_public_ip": addresses[0], "accessed_at": utc_now()})
                if reply.status in (301, 302, 303, 307, 308):
                    if not headers.get("location"):
                        raise AcquisitionError("bad_redirect", "Redirect has no Location")
                    current = canonical_url(urljoin(current, headers["location"]))
                    continue
                length = headers.get("content-length")
                if length and (not length.isdigit() or int(length) > max_bytes):
                    raise AcquisitionError("too_large", "Content-Length exceeds bound or is invalid")
                if headers.get("content-encoding", "identity").lower() not in ("", "identity"):
                    raise AcquisitionError("content_encoding", "Unexpected compression; cannot bypass byte limit")
                chunks, size = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise AcquisitionError("response_deadline", "Response exceeded total time bound", retryable=True)
                    chunk = reply.read(min(65536, max_bytes - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise AcquisitionError("too_large", "Response stream exceeds byte limit")
                    chunks.append(chunk)
                if length and size != int(length):
                    raise AcquisitionError("truncated", "Response differs from Content-Length", retryable=True)
                return Response(current, reply.status, headers, b"".join(chunks), trace)
            except (TimeoutError, OSError, http.client.HTTPException) as error:
                raise AcquisitionError("network_failure", type(error).__name__, retryable=True) from error
            finally:
                conn.close()
        raise AcquisitionError("redirect_limit", "Too many redirects")


def robots_rules(text: str, url: str, user_agent=USER_AGENT):
    """Longest-path Allow/Disallow with wildcard/end anchors and UA groups."""
    # Match our product token, not words in the descriptive HTTP UA comment.
    # For example, a DOC crawler exclusion must not match "public-document".
    product_token = user_agent.split("/", 1)[0].split(" ", 1)[0].lower()
    groups, agents, rules, delay, global_delay = [], [], [], 0.0, 0.0
    rules_started = False
    for line in text.splitlines() + ["User-agent: __end__"]:
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "crawl-delay" and not agents:
            try:
                global_delay = max(global_delay, float(value))
            except ValueError as error:
                raise AcquisitionError("robots_delay", "Unparseable global robots crawl delay") from error
            if not math_finite_delay(float(value)):
                raise AcquisitionError("robots_delay", "Global robots crawl delay exceeds safe session bounds")
        if key == "user-agent":
            if rules_started:
                groups.append((agents, rules, delay))
                agents, rules, delay, rules_started = [], [], 0.0, False
            agents.append(value.lower())
        elif agents:
            rules_started = True
            if key in ("allow", "disallow") and value:
                rules.append((key, value))
            elif key == "crawl-delay":
                try:
                    parsed_delay = float(value)
                except ValueError as error:
                    raise AcquisitionError("robots_delay", "Unparseable robots crawl delay; access deferred") from error
                if not math_finite_delay(parsed_delay):
                    raise AcquisitionError("robots_delay", "Robots crawl delay exceeds safe session bounds")
                delay = max(delay, parsed_delay)
            elif key == "request-rate" and re.fullmatch(r"\d+/\d+", value):
                requests, seconds = map(int, value.split("/"))
                if requests:
                    delay = max(delay, seconds / requests)
    ranked = []
    for agents, rules, delay in groups:
        specificity = max((0 if agent == "*" else len(agent) for agent in agents if agent == "*" or agent in product_token), default=-1)
        if specificity >= 0:
            ranked.append((specificity, rules, delay))
    if not ranked:
        return True, global_delay
    best = max(item[0] for item in ranked)
    path = urlsplit(url).path or "/"
    if urlsplit(url).query:
        path += "?" + urlsplit(url).query
    path = normalize_robots_path(path)
    matches, delay = [], global_delay
    for specificity, rules, crawl in ranked:
        if specificity != best:
            continue
        delay = max(delay, crawl)
        for kind, value in rules:
            value = normalize_robots_path(value)
            pattern = re.escape(value).replace(r"\*", ".*")
            pattern = pattern[:-2] + "$" if value.endswith("$") else pattern
            if re.match(pattern, path):
                matches.append((len(value.replace("*", "").rstrip("$")), kind == "allow"))
    if not math_finite_delay(delay):
        raise AcquisitionError("robots_delay", "Robots crawl delay exceeds safe session bounds")
    return (max(matches)[1] if matches else True), delay


def normalize_robots_path(value):
    """RFC 9309 comparison: decode unreserved octets, preserve reserved ones."""
    unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    def replace(match):
        character = chr(int(match.group(1), 16))
        return character if character in unreserved else "%" + match.group(1).upper()
    value = re.sub(r"%([0-9a-fA-F]{2})", replace, value)
    return "".join(character if ord(character) < 128 else "".join(f"%{byte:02X}" for byte in character.encode("utf-8")) for character in value)


def math_finite_delay(delay):
    return 0 <= delay <= 60


def retry_delay(header):
    if not header:
        return None
    try:
        value = float(header) if str(header).isdigit() else (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
    except (TypeError, ValueError, OverflowError):
        raise AcquisitionError("invalid_retry_after", "Invalid Retry-After; defer retry")
    if not 0 <= value <= 60:
        raise AcquisitionError("retry_deferred", "Retry-After exceeds bounded session; resume later")
    return value


def atomic_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def acquisition_lock(root: Path):
    """OS lock is released by the kernel on crash; lock-file existence is harmless."""
    path = root / ".acquisition.lock"
    with path.open("a+b") as handle:
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise AcquisitionError("busy", "Another collector owns this manifest") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def validate_document(body: bytes, content_type: str, expected_mime: str):
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime != expected_mime or expected_mime not in ("application/pdf", "text/html", "text/plain"):
        raise AcquisitionError("mime_mismatch", "Returned MIME differs from approved document type")
    if not body:
        raise AcquisitionError("empty_body", "Empty document")
    if mime == "application/pdf":
        if not body.startswith(b"%PDF-") or b"%%EOF" not in body[-2048:]:
            raise AcquisitionError("damaged_pdf", "PDF signature or final EOF missing")
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(body), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 5000:
                raise ValueError("Encrypted or unbounded PDF")
        except Exception as error:
            raise AcquisitionError("damaged_pdf", "PDF structural validation failed") from error
        return ".pdf", {"page_count": len(reader.pages), "structurally_valid": True}
    if mime == "text/html" and not re.search(br"<(?:!doctype\s+html|html)[\s>]", body[:4096], re.I):
        raise AcquisitionError("invalid_html", "Expected an HTML document")
    if mime == "text/html" and re.search(br"(?:<title>\s*(?:access denied|just a moment|captcha)|/cdn-cgi/challenge-platform/|cf-chl-)", body, re.I):
        raise AcquisitionError("access_challenge", "Access challenge is not a source document; no bypass")
    if mime == "text/plain":
        try:
            body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AcquisitionError("invalid_text", "Plain text must be UTF-8") from error
    return (".html" if mime == "text/html" else ".txt"), {"structurally_valid": True}


class SourceCollector:
    def __init__(self, project_root: Path, *, output_dir=None, fetcher=None, max_bytes=32 * 1024 * 1024, retries=2, sleep: Callable=time.sleep):
        self.project_root = Path(project_root).resolve()
        self.root = Path(output_dir or self.project_root / "data/open_knowledge").resolve()
        if not is_path_within(self.root, self.project_root):
            raise AcquisitionError("output_escape", "Output must remain inside project")
        if not 1 <= max_bytes <= 64 * 1024 * 1024 or not 0 <= retries <= 3:
            raise ValueError("Invalid bounded collection settings")
        self.fetcher, self.max_bytes, self.retries, self.sleep = fetcher or HTTPSFetcher(), max_bytes, retries, sleep
        self.robot_cache, self.policy_cache, self.robot_evidence = {}, {}, {}

    def _robots(self, url, hosts):
        origin = "https://" + urlsplit(url).netloc
        if origin not in self.robot_cache:
            response = self.fetcher.get(origin + "/robots.txt", allowed_hosts=hosts, max_bytes=512 * 1024)
            self.robot_evidence[origin] = {"url": origin + "/robots.txt", "status": response.status, "sha256": sha256(response.body).hexdigest(), "accessed_at": utc_now(), "trace": response.trace, "permission_inferred": False}
            if response.status not in (200, 404, 410):
                raise AcquisitionError("robots_unavailable", f"Robots {origin}/robots.txt status {response.status}; access not assumed", retryable=response.status >= 500)
            raw = response.body.decode("utf-8", errors="replace") if response.status == 200 else ""
            if response.status == 200 and "<html" in raw[:1000].lower():
                raise AcquisitionError("invalid_robots", "Robots endpoint returned an HTML challenge")
            self.robot_cache[origin] = (raw, {**self.robot_evidence[origin], "text": raw})
        raw, evidence = self.robot_cache[origin]
        allowed, delay = robots_rules(raw, url)
        if not allowed:
            raise AcquisitionError("robots_denied", "Applicable robots rule prohibits this URL")
        return delay, {**evidence, "checked_url": url, "allowed": True, "crawl_delay_seconds": delay}

    def _policy(self, spec, hosts):
        license_data = spec.get("license", {})
        terms = spec.get("terms", {})
        if license_data.get("status") != "confirmed" or license_data.get("allow_fulltext") is not True or not license_data.get("basis"):
            return None
        if terms.get("review_status") != "compatible" or not terms.get("basis"):
            raise AcquisitionError("terms_unreviewed", "Full text requires a specific compatible terms assessment")
        results = []
        for url in dict.fromkeys([license_data.get("url"), terms.get("url")]):
            url = canonical_url(url)
            if url not in self.policy_cache:
                response = self.fetcher.get(url, allowed_hosts=hosts, max_bytes=2 * 1024 * 1024, before_request=lambda target: self._robots(target, hosts)[0])
                if response.status != 200:
                    raise AcquisitionError("policy_unavailable", f"License/terms HTTP {response.status}; no full text collected", retryable=response.status >= 500)
                self.policy_cache[url] = {"url": url, "final_url": response.url, "status": response.status, "sha256": sha256(response.body).hexdigest(), "accessed_at": utc_now(), "trace": response.trace}
            results.append(self.policy_cache[url])
        return results

    def collect(self, candidates: list[dict], *, refresh=False):
        self.root.mkdir(parents=True, exist_ok=True)
        with acquisition_lock(self.root):
            manifest_path = self.root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema_version": SCHEMA_VERSION, "sources": [], "human_reviewed_count": 0}
            if manifest.get("schema_version") != SCHEMA_VERSION:
                raise AcquisitionError("manifest_version", "Unsupported manifest schema")
            rows = {row["source_id"]: row for row in manifest["sources"]}
            for spec in candidates:
                source_id = spec.get("source_id", "")
                if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,100}", source_id):
                    raise AcquisitionError("source_id", "Unsafe source ID")
                url = canonical_url(spec["url"])
                old = rows.get(source_id, {})
                if old.get("human_reviewed") or old.get("review_status") in ("reviewed", "published") or old.get("knowledge_status") in ("reviewed", "published"):
                    raise AcquisitionError("reviewed_source_immutable", "Collector cannot overwrite human review or published state")
                if old and old["url"] != url:
                    raise AcquisitionError("source_identity", "Source ID may not silently change canonical URL")
                if old.get("status") == "downloaded" and not refresh:
                    file_path = (self.project_root / old["local_path"]).resolve()
                    if not is_path_within(file_path, self.root) or not file_path.is_file() or sha256_file(file_path) != old["sha256"]:
                        raise AcquisitionError("cache_integrity", "Previously acquired source failed local hash/path validation; preserved for investigation")
                    if spec.get("expected_sha256") and spec["expected_sha256"] != old["sha256"]:
                        raise AcquisitionError("hash_mismatch", "Cached source differs from requested expected hash")
                    if spec.get("expected_mime") != old["mime"]:
                        raise AcquisitionError("mime_mismatch", "Cached source differs from requested MIME")
                    continue
                row = {**spec, "url": url, "review_status": "pending_review", "knowledge_status": "machine_draft", "human_reviewed": False, "status": "pending", "attempts": list(old.get("attempts", [])), "versions": list(old.get("versions", [])), "local_path": None, "sha256": None}
                hosts = {urlsplit(canonical_url("https://" + host)).hostname for host in spec.get("allowed_hosts", [])}
                if not hosts:
                    raise AcquisitionError("allowlist_required", "Every source needs explicit allowed hosts")
                duplicate_url = next((item for item in rows.values() if item.get("url") == url and item.get("status") == "downloaded" and item["source_id"] != source_id), None)
                # Reuse only the same explicit permission/terms assessment. An
                # unapproved alias must not acquire content through deduplication.
                same_permission = bool(duplicate_url) and spec.get("license") == duplicate_url.get("license") and spec.get("terms") == duplicate_url.get("terms")
                approved = spec.get("license", {}).get("status") == "confirmed" and spec.get("license", {}).get("allow_fulltext") is True and bool(spec.get("license", {}).get("basis")) and spec.get("terms", {}).get("review_status") == "compatible" and bool(spec.get("terms", {}).get("basis"))
                same_expectation = bool(duplicate_url) and spec.get("expected_mime") == duplicate_url.get("mime") and spec.get("expected_sha256", duplicate_url.get("sha256")) == duplicate_url.get("sha256")
                if duplicate_url and not refresh and same_permission and approved and same_expectation:
                    target = (self.project_root / duplicate_url["local_path"]).resolve()
                    if not is_path_within(target, self.root) or not target.is_file() or sha256_file(target) != duplicate_url["sha256"]:
                        raise AcquisitionError("cache_integrity", "Duplicate URL cache failed integrity validation")
                    row.update({key: duplicate_url[key] for key in ("local_path", "sha256", "bytes", "mime", "validation", "policy_evidence", "robots", "versions")})
                    row.update(status="downloaded", duplicate_of=duplicate_url["source_id"], accessed_at=utc_now())
                    row["attempts"].append({"at": utc_now(), "status": "deduplicated_url", "network_request_sent": False})
                    rows[source_id] = row
                    manifest.update(sources=list(rows.values()), updated_at=utc_now(), human_reviewed_count=sum(item.get("human_reviewed") is True for item in rows.values()))
                    atomic_json(manifest_path, manifest)
                    continue
                for attempt in range(self.retries + 1):
                    started = utc_now()
                    try:
                        policy = self._policy(spec, hosts)
                        if policy is None:
                            row.update(status="metadata_only", accessed_at=started, collection_note="Full-copy permission unconfirmed; no content request sent")
                            row["attempts"].append({"at": started, "status": "metadata_only"})
                            break
                        row["policy_evidence"] = policy
                        row["robots"] = self._robots(url, hosts)[1]
                        response = self.fetcher.get(url, allowed_hosts=hosts, max_bytes=self.max_bytes, before_request=lambda target: self._robots(target, hosts)[0])
                        row["http_trace"] = response.trace
                        if response.status != 200:
                            wait = retry_delay(response.headers.get("retry-after")) if response.status in (429, 503) else None
                            raise AcquisitionError("http_error", f"HTTP {response.status}; no bypass attempted", retryable=response.status in (408, 429, 500, 502, 503, 504), retry_after=wait)
                        extension, checks = validate_document(response.body, response.headers.get("content-type", ""), spec["expected_mime"])
                        digest = sha256(response.body).hexdigest()
                        if spec.get("expected_sha256") and digest != spec["expected_sha256"]:
                            raise AcquisitionError("hash_mismatch", "Downloaded file differs from expected hash")
                        existing = next((item for item in rows.values() if item.get("sha256") == digest and item.get("status") == "downloaded"), None)
                        target = self.project_root / existing["local_path"] if existing else self.root / "sources" / source_id / digest / ("document" + extension)
                        if not is_path_within(target, self.root):
                            raise AcquisitionError("cache_escape", "Cache target escapes acquisition directory")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            if sha256_file(target) != digest:
                                raise AcquisitionError("cache_integrity", "Existing version differs; never overwrite")
                        else:
                            temporary = target.with_name("download-" + uuid4().hex + ".tmp")
                            try:
                                with temporary.open("xb") as handle:
                                    handle.write(response.body)
                                    handle.flush()
                                    os.fsync(handle.fileno())
                                # Atomic publish without replacing an existing
                                # content-addressed version, including local races.
                                try:
                                    os.link(temporary, target)
                                except FileExistsError:
                                    if sha256_file(target) != digest:
                                        raise AcquisitionError("cache_integrity", "Concurrent version differs; never overwrite")
                            finally:
                                temporary.unlink(missing_ok=True)
                        version = {"sha256": digest, "local_path": str(target.relative_to(self.project_root)).replace("\\", "/"), "bytes": len(response.body), "accessed_at": utc_now(), "final_url": response.url, "etag": response.headers.get("etag"), "last_modified": response.headers.get("last-modified")}
                        if digest not in {item["sha256"] for item in row["versions"]}:
                            row["versions"].append(version)
                        row.update(version, status="downloaded", mime=spec["expected_mime"], validation=checks, duplicate_of=existing["source_id"] if existing and existing["source_id"] != source_id else None)
                        row.pop("error_code", None)
                        row.pop("error", None)
                        row["attempts"].append({"at": started, "status": "downloaded", "sha256": digest})
                        break
                    except AcquisitionError as error:
                        row.update(status="failed", accessed_at=utc_now(), error_code=error.code, error=str(error))
                        row["attempts"].append({"at": started, "status": "failed", "code": error.code, "message": str(error), "retryable": error.retryable})
                        if not error.retryable or attempt == self.retries:
                            break
                        self.sleep(max(min(2 ** attempt * 2, 8), error.retry_after or 0))
                    finally:
                        row["robots_request_evidence"] = [item for origin, item in self.robot_evidence.items() if urlsplit(origin).hostname in hosts]
                        rows[source_id] = row
                        manifest.update(sources=list(rows.values()), updated_at=utc_now(), human_reviewed_count=sum(item.get("human_reviewed") is True for item in rows.values()))
                        atomic_json(manifest_path, manifest)
            return manifest
