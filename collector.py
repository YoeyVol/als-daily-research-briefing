"""Collect ALS intelligence from independent, failure-isolated sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from calendar import month_abbr
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable

import feedparser
import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
LOGGER = logging.getLogger("als_intelligence")


def configure_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S%z"
    )
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    LOGGER.addHandler(stream)
    file_handler = logging.FileHandler(LOG_DIR / "als-intelligence.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def expand_env(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    pattern = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?}")
    return pattern.sub(lambda m: os.getenv(m.group(1), m.group(2) or ""), value)


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(value) for value in node]
        return expand_env(node)

    return walk(raw)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.error("Cannot read %s: %s", path, exc)
        return default


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def build_session(collection: dict[str, Any]) -> requests.Session:
    retry = Retry(
        total=int(collection.get("retries", 3)),
        connect=int(collection.get("retries", 3)),
        read=int(collection.get("retries", 3)),
        status=int(collection.get("retries", 3)),
        backoff_factor=float(collection.get("backoff_factor", 0.8)),
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": collection.get("user_agent", "ALSGlobalIntelligence/1.0")})
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def text_of(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def normalize_month(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return value.zfill(2)
    lookup = {name.lower(): f"{number:02d}" for number, name in enumerate(month_abbr) if name}
    return lookup.get(value[:3].lower(), "01")


def pubmed_date(citation: ET.Element) -> str:
    candidates = [
        citation.find("./Article/ArticleDate"),
        citation.find("./Article/Journal/JournalIssue/PubDate"),
    ]
    for node in candidates:
        if node is None:
            continue
        medline = text_of(node.find("MedlineDate"))
        if medline:
            return medline
        year = text_of(node.find("Year"))
        if year:
            month = normalize_month(text_of(node.find("Month")) or "1")
            day = (text_of(node.find("Day")) or "01").zfill(2)
            return f"{year}-{month}-{day}"
    return ""


def classify_article(title: str, abstract: str, config: dict[str, Any]) -> str:
    haystack = f"{title} {abstract}".lower()
    keywords = config.get("classification", {}).get("drug_development_keywords", [])
    return "Drug Development" if any(str(word).lower() in haystack for word in keywords) else "Research"


def pubmed_source_config(config: dict[str, Any]) -> dict[str, Any]:
    return next((source for source in config.get("sources", []) if source.get("id") == "pubmed"), {})


def is_pubmed_relevant(
    title: str,
    abstract: str,
    source: dict[str, Any],
    mesh_terms: Iterable[str] = (),
    keywords: Iterable[str] = (),
) -> bool:
    if not source.get("relevance_filter", True):
        return True
    combined = " ".join([title, abstract, *mesh_terms, *keywords]).lower()
    phrases = [str(value).lower() for value in source.get("relevance_phrases", [])]
    if any(phrase in combined for phrase in phrases):
        return True
    acronyms = [str(value) for value in source.get("title_acronyms", ["ALS", "MND"])]
    if any(re.search(rf"\b{re.escape(acronym)}\b", title, flags=re.IGNORECASE) for acronym in acronyms):
        return True
    has_als = bool(re.search(r"\bALS\b", abstract, flags=re.IGNORECASE))
    context_terms = [str(value).lower() for value in source.get("als_context_terms", [])]
    return has_als and any(term in combined for term in context_terms)


def stored_pubmed_record_relevant(item: dict[str, Any], source: dict[str, Any]) -> bool:
    return is_pubmed_relevant(
        str(item.get("title", "")),
        str(item.get("abstract", "")),
        source,
        item.get("mesh_terms", []),
        item.get("keywords", []),
    )


def parse_pubmed_xml(xml_text: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    records: list[dict[str, Any]] = []
    source_config = pubmed_source_config(config)
    for article in root.findall(".//PubmedArticle"):
        citation = article.find("MedlineCitation")
        if citation is None:
            continue
        pmid = text_of(citation.find("PMID"))
        article_node = citation.find("Article")
        if not pmid or article_node is None:
            continue
        title = text_of(article_node.find("ArticleTitle"))
        authors: list[str] = []
        for author in article_node.findall("./AuthorList/Author"):
            collective = text_of(author.find("CollectiveName"))
            if collective:
                authors.append(collective)
                continue
            name = " ".join(
                value
                for value in (
                    text_of(author.find("ForeName")),
                    text_of(author.find("LastName")),
                )
                if value
            )
            if name:
                authors.append(name)
        abstract_parts: list[str] = []
        for abstract_node in article_node.findall("./Abstract/AbstractText"):
            value = text_of(abstract_node)
            label = abstract_node.attrib.get("Label", "").strip()
            if value:
                abstract_parts.append(f"{label}: {value}" if label else value)
        abstract = "\n\n".join(abstract_parts)
        mesh_terms = [text_of(node.find("DescriptorName")) for node in citation.findall("./MeshHeadingList/MeshHeading")]
        mesh_terms = [value for value in mesh_terms if value]
        keywords = [text_of(node) for node in citation.findall("./KeywordList/Keyword")]
        keywords = [value for value in keywords if value]
        if not is_pubmed_relevant(title, abstract, source_config, mesh_terms, keywords):
            continue
        journal = text_of(article_node.find("./Journal/Title")) or text_of(
            article_node.find("./Journal/ISOAbbreviation")
        )
        doi = ""
        for identifier in article.findall("./PubmedData/ArticleIdList/ArticleId"):
            if identifier.attrib.get("IdType", "").lower() == "doi":
                doi = text_of(identifier)
                break
        if not doi:
            for identifier in article_node.findall("ELocationID"):
                if identifier.attrib.get("EIdType", "").lower() == "doi":
                    doi = text_of(identifier)
                    break
        records.append(
            {
                "id": pmid,
                "event_key": f"pubmed:{pmid}",
                "source_id": "pubmed",
                "source_name": "PubMed",
                "category": classify_article(title, abstract, config),
                "title": title,
                "authors": authors,
                "journal": journal,
                "publication_date": pubmed_date(citation),
                "pmid": pmid,
                "doi": doi,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "abstract": abstract,
                "mesh_terms": mesh_terms,
                "keywords": keywords,
            }
        )
    return records


def collect_pubmed(
    source: dict[str, Any], config: dict[str, Any], session: requests.Session, lookback_days: int
) -> list[dict[str, Any]]:
    collection = config["collection"]
    timeout = int(collection.get("request_timeout_seconds", 30))
    base_url = source["base_url"].rstrip("/")
    params: dict[str, Any] = {
        "db": "pubmed",
        "term": source["query"],
        "retmode": "json",
        "retmax": int(source.get("max_results", 200)),
        "sort": "pub date",
        "datetype": source.get("date_type", "edat"),
        "reldate": lookback_days,
    }
    api_key = os.getenv(str(source.get("api_key_env", "NCBI_API_KEY")), "")
    email = os.getenv(str(source.get("email_env", "NCBI_EMAIL")), "")
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email
    response = session.get(f"{base_url}/esearch.fcgi", params=params, timeout=timeout)
    response.raise_for_status()
    ids = response.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    batch_size = int(source.get("batch_size", 100))
    records: list[dict[str, Any]] = []
    for offset in range(0, len(ids), batch_size):
        batch = ids[offset : offset + batch_size]
        fetch_params: dict[str, Any] = {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"}
        if api_key:
            fetch_params["api_key"] = api_key
        if email:
            fetch_params["email"] = email
        fetched = session.get(f"{base_url}/efetch.fcgi", params=fetch_params, timeout=timeout)
        fetched.raise_for_status()
        records.extend(parse_pubmed_xml(fetched.text, config))
        if offset + batch_size < len(ids):
            time.sleep(0.12 if api_key else 0.36)
    return records


def parse_trial(study: dict[str, Any]) -> dict[str, Any] | None:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
    design = protocol.get("designModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    nct_id = identification.get("nctId", "")
    if not nct_id:
        return None
    update = status.get("lastUpdatePostDateStruct", {}).get("date", "")
    interventions = []
    for intervention in arms.get("interventions", []):
        label = ": ".join(
            value for value in (intervention.get("type", "").title(), intervention.get("name", "")) if value
        )
        if label and label not in interventions:
            interventions.append(label)
    lead_sponsor = sponsor_module.get("leadSponsor", {}).get("name", "")
    phases = design.get("phases", []) or ["NOT_APPLICABLE"]
    return {
        "id": nct_id,
        "event_key": f"clinicaltrials:{nct_id}:{update or 'unknown'}",
        "source_id": "clinicaltrials_gov",
        "source_name": "ClinicalTrials.gov",
        "category": "Clinical Trials",
        "nct_id": nct_id,
        "title": identification.get("briefTitle") or identification.get("officialTitle", ""),
        "sponsor": lead_sponsor,
        "phase": phases,
        "recruitment_status": status.get("overallStatus", ""),
        "intervention": interventions or ["Not provided"],
        "start_date": status.get("startDateStruct", {}).get("date", ""),
        "last_update_date": update,
        "url": f"https://clinicaltrials.gov/study/{nct_id}",
    }


def collect_clinical_trials(
    source: dict[str, Any], config: dict[str, Any], session: requests.Session, lookback_days: int
) -> list[dict[str, Any]]:
    timeout = int(config["collection"].get("request_timeout_seconds", 30))
    cutoff = date.today() - timedelta(days=lookback_days)
    token = ""
    records: list[dict[str, Any]] = []
    page_size = min(int(source.get("page_size", 100)), 1000)
    max_pages = int(source.get("max_pages", 10))
    for _page in range(max_pages):
        params: dict[str, Any] = {
            "query.cond": source["query"],
            "format": "json",
            "pageSize": page_size,
            "sort": source.get("sort", "LastUpdatePostDate:desc"),
        }
        if token:
            params["pageToken"] = token
        response = session.get(source["api_url"], params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        page_records = [record for study in payload.get("studies", []) if (record := parse_trial(study))]
        records.extend(page_records)
        if page_records:
            oldest = page_records[-1].get("last_update_date", "")
            try:
                if oldest and date.fromisoformat(oldest[:10]) < cutoff:
                    break
            except ValueError:
                LOGGER.warning("ClinicalTrials.gov returned an unrecognized update date: %s", oldest)
        token = payload.get("nextPageToken", "")
        if not token:
            break
    filtered: list[dict[str, Any]] = []
    for record in records:
        value = record.get("last_update_date", "")
        try:
            if value and date.fromisoformat(value[:10]) >= cutoff:
                filtered.append(record)
        except ValueError:
            filtered.append(record)
    return filtered


def entry_datetime(entry: Any) -> str:
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    for field in ("published", "updated"):
        value = entry.get(field, "")
        if value:
            try:
                return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except (TypeError, ValueError, OverflowError):
                pass
    return ""


def clean_html(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value or "").split())


def collect_rss(
    source: dict[str, Any], config: dict[str, Any], session: requests.Session, _lookback_days: int
) -> list[dict[str, Any]]:
    timeout = int(config["collection"].get("request_timeout_seconds", 30))
    response = session.get(source["url"], timeout=timeout)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise ValueError(f"Invalid RSS/Atom feed: {getattr(feed, 'bozo_exception', 'unknown error')}")
    results: list[dict[str, Any]] = []
    for entry in feed.entries[: int(source.get("max_entries", 30))]:
        title = clean_html(entry.get("title", ""))
        link = entry.get("link", "")
        raw_id = entry.get("id") or link or title
        if not raw_id:
            continue
        digest = hashlib.sha256(f"{source['id']}:{raw_id}".encode("utf-8")).hexdigest()[:24]
        results.append(
            {
                "id": digest,
                "event_key": f"rss:{source['id']}:{digest}",
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source.get("category", "Organization News"),
                "title": title,
                "published_date": entry_datetime(entry),
                "url": link,
                "summary": clean_html(entry.get("summary", "")),
            }
        )
    return results


COLLECTORS = {
    "pubmed": collect_pubmed,
    "clinicaltrials": collect_clinical_trials,
    "rss": collect_rss,
}


def upsert_items(existing: list[dict[str, Any]], incoming: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(item.get("id")): item for item in existing if item.get("id")}
    for item in incoming:
        current = by_id.get(str(item["id"]), {})
        first_seen = current.get("first_seen_at") or item.get("first_seen_at") or iso_now()
        by_id[str(item["id"])] = {**current, **item, "first_seen_at": first_seen, "last_seen_at": iso_now()}
    return list(by_id.values())


def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[str, str]:
        date_value = (
            item.get("last_update_date")
            or item.get("publication_date")
            or item.get("published_date")
            or item.get("first_seen_at")
            or ""
        )
        return str(date_value), str(item.get("id", ""))

    return sorted(items, key=key, reverse=True)


def run(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    DATA_DIR.mkdir(exist_ok=True)
    seen_path = DATA_DIR / "seen.json"
    seen = load_json(seen_path, {"version": 1, "keys": {}, "source_last_success": {}})
    seen.setdefault("keys", {})
    seen.setdefault("source_last_success", {})
    bootstrap = not bool(seen["keys"])
    collection = config.get("collection", {})
    lookback_days = int(collection.get("bootstrap_days" if bootstrap else "lookback_days", 3))
    limit = int(collection.get("history_limit_per_dataset", 1000))
    session = build_session(collection)
    stores = {
        "articles": load_json(DATA_DIR / "articles.json", {"items": []}),
        "trials": load_json(DATA_DIR / "trials.json", {"items": []}),
        "news": load_json(DATA_DIR / "news.json", {"items": []}),
    }
    for store in stores.values():
        store["new_keys"] = []
    run_started = iso_now()
    statuses: list[dict[str, Any]] = []

    for source in config.get("sources", []):
        source_id = source.get("id", "unknown")
        source_type = source.get("type", "")
        if not source.get("enabled", False):
            statuses.append({"source_id": source_id, "status": "disabled", "new": 0})
            continue
        collector = COLLECTORS.get(source_type)
        if collector is None:
            LOGGER.warning("Skipping %s: no collector registered for type '%s'", source_id, source_type)
            statuses.append({"source_id": source_id, "status": "unsupported", "new": 0})
            continue
        try:
            LOGGER.info("Collecting %s (%s)", source.get("name", source_id), source_type)
            records = collector(source, config, session, lookback_days)
            new_records = [record for record in records if record["event_key"] not in seen["keys"]]
            collected_at = iso_now()
            for record in new_records:
                record["collected_at"] = collected_at
                seen["keys"][record["event_key"]] = collected_at
            dataset = "articles" if source_type == "pubmed" else "trials" if source_type == "clinicaltrials" else "news"
            existing_items = stores[dataset].get("items", [])
            if source_type == "pubmed" and source.get("relevance_filter", True):
                before = len(existing_items)
                existing_items = [item for item in existing_items if stored_pubmed_record_relevant(item, source)]
                removed = before - len(existing_items)
                if removed:
                    LOGGER.info("pubmed: removed %d previously stored acronym false-positive(s)", removed)
            stores[dataset]["items"] = upsert_items(existing_items, records)
            stores[dataset]["new_keys"].extend(record["event_key"] for record in new_records)
            seen["source_last_success"][source_id] = collected_at
            statuses.append(
                {"source_id": source_id, "status": "ok", "fetched": len(records), "new": len(new_records)}
            )
            LOGGER.info("%s: fetched=%d new=%d", source_id, len(records), len(new_records))
        except Exception as exc:  # source isolation is intentional
            LOGGER.exception("Source %s failed: %s", source_id, exc)
            statuses.append({"source_id": source_id, "status": "error", "new": 0, "error": str(exc)})

    updated_at = iso_now()
    for name, store in stores.items():
        store["updated_at"] = updated_at
        store["items"] = sort_items(store.get("items", []))[:limit]
        store["new_keys"] = list(dict.fromkeys(store.get("new_keys", [])))
        atomic_write_json(DATA_DIR / f"{name}.json", store)
    seen["updated_at"] = updated_at
    atomic_write_json(seen_path, seen)
    summary = {
        "started_at": run_started,
        "completed_at": updated_at,
        "bootstrap": bootstrap,
        "lookback_days": lookback_days,
        "new_total": sum(int(status.get("new", 0)) for status in statuses),
        "sources": statuses,
    }
    atomic_write_json(DATA_DIR / "run_status.json", summary)
    LOGGER.info("Collection complete: %d new item(s)", summary["new_total"])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "sources.yaml")
    args = parser.parse_args()
    configure_logging()
    try:
        run(args.config.resolve())
        return 0
    except Exception as exc:
        LOGGER.exception("Fatal collector error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
