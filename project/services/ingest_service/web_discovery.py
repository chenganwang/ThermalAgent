"""Topic search through public Crossref metadata, never automatic fulltext intake."""
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode

from services.ingest_service.web_sources import (
    AcquisitionError, SourceCollector, acquisition_lock, atomic_json,
    retry_delay, utc_now,
)

API_HOST = "api.crossref.org"
API_TERMS = "https://www.crossref.org/documentation/retrieve-metadata/rest-api/"


def normalize_topics(topics):
    result, seen = [], set()
    for topic in topics:
        if not isinstance(topic, str) or any(ord(c) < 32 for c in topic):
            raise ValueError("Topic must be plain text without control characters")
        topic = " ".join(topic.split())
        if not 3 <= len(topic) <= 240:
            raise ValueError("Topic length must be 3..240 characters")
        if topic.casefold() not in seen:
            result.append(topic)
            seen.add(topic.casefold())
    if not 1 <= len(result) <= 5:
        raise ValueError("Use one to five distinct bounded topics")
    return result


def crossref_candidates(payload, topic):
    if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("message"), dict) or not isinstance(payload["message"].get("items"), list):
        raise AcquisitionError("invalid_metadata", "Crossref response lacks successful items[]")
    candidates, rejected, seen = [], [], set()
    for item in payload["message"]["items"]:
        if not isinstance(item, dict):
            rejected.append({"reason": "invalid_item"})
            continue
        doi = str(item.get("DOI", "")).strip().lower()
        titles = item.get("title", [])
        title = " ".join(str(titles[0]).split()) if isinstance(titles, list) and titles else ""
        if not re.fullmatch(r"10\.\d{4,9}/[^\s<>]+", doi) or not 8 <= len(title) <= 2000:
            rejected.append({"doi": doi[:250], "reason": "missing_or_invalid_doi_or_title"})
            continue
        if doi in seen:
            rejected.append({"doi": doi, "reason": "duplicate_doi"})
            continue
        seen.add(doi)
        author_rows = item.get("author", []) if isinstance(item.get("author", []), list) else []
        authors = [" ".join(str(a.get(key, "")) for key in ("given", "family")).strip() or str(a.get("name", "")).strip() for a in author_rows if isinstance(a, dict)]
        authors = [name for name in authors if name]
        license_rows = item.get("license", []) if isinstance(item.get("license", []), list) else []
        hints = [{key: license_item.get(key) for key in ("URL", "content-version", "start")} for license_item in license_rows if isinstance(license_item, dict) and isinstance(license_item.get("URL"), str)]
        issues = []
        if not authors:
            issues.append("authors_missing")
        if not hints:
            issues.append("license_hint_missing")
        published = item.get("published") if isinstance(item.get("published"), dict) else {}
        date_parts = published.get("date-parts", [])
        if not date_parts:
            issues.append("publication_date_missing")
        candidates.append({
            "source_id": "crossref_" + sha256(doi.encode()).hexdigest()[:24],
            "doi": doi, "url": "https://doi.org/" + quote(doi, safe="/():;._-"),
            "title": title, "authors": authors, "publisher": item.get("publisher"),
            "published_date_parts": date_parts, "document_type": item.get("type"),
            "discovery_topic": topic, "discovery_provider": "Crossref REST API",
            "status": "metadata_only", "review_status": "pending_review", "knowledge_status": "machine_draft", "human_reviewed": False,
            "license": {"status": "unconfirmed", "allow_fulltext": False, "discovery_hints": hints},
            "qc": {"required_identity_fields_valid": True, "issues": issues, "semantic_relevance": "not_reviewed", "license_hints_are_not_permission": True},
        })
    return candidates, rejected


def discover_topics(project_root: Path, topics, *, output_dir=None, rows=8, refresh=False, fetcher=None, retries=1, sleep=time.sleep):
    topics = normalize_topics(topics)
    if not 1 <= rows <= 20 or not 0 <= retries <= 2:
        raise ValueError("Rows must be 1..20 and retries 0..2")
    guard = SourceCollector(project_root, output_dir=output_dir or Path(project_root) / "data/open_knowledge_discovery", fetcher=fetcher)
    guard.root.mkdir(parents=True, exist_ok=True)
    with acquisition_lock(guard.root):
        manifest_path = guard.root / "discovery_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema_version": "crossref-topic-discovery-v1", "api_terms": API_TERMS, "topics": [], "candidates": [], "human_reviewed_count": 0, "fulltext_requests": 0}
        if manifest.get("schema_version") != "crossref-topic-discovery-v1":
            raise AcquisitionError("manifest_version", "Unsupported discovery manifest")
        for topic in topics:
            key = sha256((topic.casefold() + "|" + str(rows)).encode()).hexdigest()[:24]
            old = next((row for row in manifest["topics"] if row["topic_key"] == key), {})
            if old and old["status"] == "discovered" and not refresh:
                continue
            request_url = "https://" + API_HOST + "/works?" + urlencode({"query.bibliographic": topic, "rows": rows, "filter": "type:journal-article", "select": "DOI,title,author,published,URL,license,type,publisher"})
            current = {"topic": topic, "topic_key": key, "request_url": request_url, "status": "pending", "attempts": list(old.get("attempts", [])), "responses": list(old.get("responses", []))}
            for attempt in range(retries + 1):
                started = utc_now()
                try:
                    current["robots"] = guard._robots(request_url, {API_HOST})[1]
                    response = guard.fetcher.get(request_url, allowed_hosts={API_HOST}, max_bytes=2 * 1024 * 1024, before_request=lambda url: guard._robots(url, {API_HOST})[0])
                    current["http_trace"] = response.trace
                    if response.status != 200:
                        delay = retry_delay(response.headers.get("retry-after")) if response.status in (429, 503) else None
                        raise AcquisitionError("http_error", f"Crossref HTTP {response.status}", retryable=response.status in (429, 500, 502, 503, 504), retry_after=delay)
                    if response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                        raise AcquisitionError("mime_mismatch", "Crossref returned non-JSON metadata")
                    try:
                        payload = json.loads(response.body)
                    except (ValueError, UnicodeError) as error:
                        raise AcquisitionError("invalid_json", "Crossref JSON cannot be decoded") from error
                    found, rejected = crossref_candidates(payload, topic)
                    digest = sha256(response.body).hexdigest()
                    # Metadata only, deliberately omit abstract and linked fulltext fields.
                    current["responses"].append({"sha256": digest, "bytes": len(response.body), "accessed_at": utc_now(), "received_items": len(payload["message"]["items"]), "candidates": found, "rejected": rejected})
                    current.update(status="discovered", candidate_count=len(found), response_sha256=digest)
                    current.pop("error_code", None)
                    current.pop("error", None)
                    current["attempts"].append({"at": started, "status": "discovered"})
                    identities = {row["doi"]: row for row in manifest["candidates"]}
                    for candidate in found:
                        if candidate["doi"] not in identities:
                            candidate["accessed_at"] = utc_now()
                            candidate["discovered_topics"] = [topic]
                            identities[candidate["doi"]] = candidate
                        elif topic not in identities[candidate["doi"]].get("discovered_topics", []):
                            identities[candidate["doi"]].setdefault("discovered_topics", []).append(topic)
                    manifest["candidates"] = list(identities.values())
                    break
                except AcquisitionError as error:
                    current.update(status="failed", error_code=error.code, error=str(error))
                    current["attempts"].append({"at": started, "status": "failed", "code": error.code, "message": str(error)})
                    if not error.retryable or attempt == retries:
                        break
                    sleep(max(2 ** attempt * 2, error.retry_after or 0))
                finally:
                    current["robots_request_evidence"] = list(guard.robot_evidence.values())
                    manifest["topics"] = [row for row in manifest["topics"] if row["topic_key"] != key] + [current]
                    manifest["updated_at"] = utc_now()
                    atomic_json(manifest_path, manifest)
        return manifest
