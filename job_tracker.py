from __future__ import annotations

import argparse
import hashlib
import html
import logging
import os
import re
import sys
import time
import webbrowser
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
import warnings
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

APP_DIR = Path(__file__).resolve().parent
LOG_FILE = APP_DIR / "job_tracker.log"
TOKEN_FILE = APP_DIR / "token.json"
CREDENTIALS_FILE = APP_DIR / "credentials.json"

DEFAULT_INTERVAL_MINUTES = 360
DEFAULT_SHEET_TITLE = "Entry-Level Non-Voice VA Job Tracker"
REQUEST_TIMEOUT = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JobTracker/1.0"
}

POSITIVE_KEYWORDS = [
    # Core target roles / work types
    "non-voice", "non voice", "chat support", "email support", "messaging support",
    "data entry", "data processing", "virtual assistant", "virtual admin",
    "administrative assistant", "admin assistant", "back office", "customer support",
    "customer service", "lead generation", "lead follow-up", "appointment setter",
    "healthcare virtual assistant", "ecommerce assistant", "executive assistant",
    "operations assistant", "sales support", "recruitment assistant",
    # Entry-level / no-experience signals
    "no experience required", "no experience needed", "without experience",
    "experience not required", "entry level", "entry-level", "entrylevel",
    "training provided", "training will be provided", "open to beginners",
    "beginner friendly", "beginner-friendly", "will train", "willing to train",
    "fresh graduate", "fresh graduates", "shs graduate", "senior high school graduate",
    "open to fresh graduates", "junior",
]

# These are phrases indicating a role is actually voice/call based or clearly senior/experienced.
NEGATIVE_PHRASES = [
    "voice account", "call center", "inbound call", "outbound call", "phone support",
    "telemarketer", "cold calling", "cold-call", "cold call", "phone sales",
    "voice process", "voice campaign", "voice support", "senior va",
    "senior virtual assistant", "senior administrative assistant", "senior admin assistant",
    "lead generation voice", "appointment setter voice",
]

EXPERIENCE_PATTERNS = [
    # Multi-year requirements are incompatible with the user's entry-level target.
    r"\b(?:[2-9]|1[0-9])\+?\s+years?\s+(?:of\s+)?experience\b",
    r"\b(?:[2-9]|1[0-9])\+?\s+years?\s+experience\b",
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten)\s+years?\s+(?:of\s+)?experience\b",
]

ONE_YEAR_OR_MORE_PATTERNS = [
    r"\b1\+?\s+year\s+(?:of\s+)?experience\b",
    r"\bat\s+least\s+1\s+year\b",
    r"\bminimum\s+1\s+year\b",
    r"\b12\s+months?\s+(?:of\s+)?experience\b",
]

VOICE_PATTERNS = [
    r"\bvoice\s+(?:account|process|campaign|support|sales|agent|role)\b",
    r"\b(?:voice|calls?)\s+(?:are|is)\s+required\b",
    r"\bhandle\s+(?:inbound|outbound)\s+calls?\b",
    r"\bmake\s+(?:inbound|outbound)?\s*calls?\b",
]

# Only keep listings that explicitly indicate they are for applicants in the Philippines
# or for Filipino applicants. Generic "worldwide/anywhere" roles are NOT treated as
# Philippines-eligible because the user wants jobs specifically open to Filipinos.
PHILIPPINES_TERMS = [
    "philippines", "philippine", "filipino", "filipinos",
    "manila", "davao", "cebu", "mindanao", "luzon", "visayas",
    "philippine applicants", "philippine residents", "philippines-based",
    "philippines based", "based in the philippines", "remote philippines",
    "remote - philippines", "remote, philippines", "ph applicants",
    "ph-based", "ph based",
]


@dataclass
class Job:
    job_id: str
    date_found: str
    last_checked: str
    job_title: str
    company_name: str
    location: str
    work_type: str
    job_source: str
    description_snippet: str
    matched_keywords: str
    why_it_matches: str
    application_url: str
    match_score: int


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def setup_logging() -> None:
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        encoding="utf-8",
    )


def clean_html_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_text(value: Any) -> str:
    text = clean_html_text(value).lower()
    text = re.sub(r"[^a-z0-9+\-\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    # Remove fragments; retain query because some apply links need it.
    return parsed._replace(fragment="").geturl()


def extract_application_url(description: Any, fallback_url: str, explicit_apply_url: Any = None) -> str:
    """Prefer an explicit apply URL, then an obvious Apply link in HTML, then the source listing URL."""
    explicit = canonical_url(str(explicit_apply_url or ""))
    if explicit:
        return explicit
    raw = str(description or "")
    try:
        soup = BeautifulSoup(raw, "html.parser")
        for a in soup.find_all("a", href=True):
            label = normalize_text(a.get_text(" ", strip=True))
            href = canonical_url(a.get("href", ""))
            if href and ("apply" in label or "application" in label or "submit" in label):
                return href
    except Exception:
        pass
    return canonical_url(fallback_url)


def stable_job_id(source: str, source_id: Any, url: str, title: str, company: str) -> str:
    raw = f"{source}|{source_id or ''}|{canonical_url(url)}|{title.strip().lower()}|{company.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def is_philippines_eligible(location: str, description: str) -> bool:
    text = normalize_text(f"{location} {description}")
    if any(term in text for term in PHILIPPINES_TERMS):
        return True
    # Handle standalone "PH" without matching words such as "phone".
    if re.search(r"\bph\b", text):
        return True
    return False


def experience_excluded(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in EXPERIENCE_PATTERNS)


def voice_excluded(text: str) -> bool:
    if any(phrase in text for phrase in NEGATIVE_PHRASES):
        return True
    return any(re.search(pattern, text, flags=re.I) for pattern in VOICE_PATTERNS)


def score_job(title: str, description: str, location: str) -> tuple[bool, int, list[str], str]:
    combined = normalize_text(f"{title} {description}")
    loc_text = normalize_text(location)

    if not title.strip() or not description.strip():
        return False, 0, [], "Missing title or description"
    if voice_excluded(combined):
        return False, 0, [], "Excluded because the listing indicates voice/call-based work"
    if experience_excluded(combined):
        return False, 0, [], "Excluded because the listing requires multiple years of experience"
    if not is_philippines_eligible(location, description):
        return False, 0, [], "Excluded because Philippine/Filipino eligibility was not established"

    matched = [kw for kw in POSITIVE_KEYWORDS if normalize_text(kw) in combined]
    score = 0
    reasons: list[str] = []

    role_indicators = [
        "virtual assistant", "virtual admin", "administrative assistant", "admin assistant",
        "non-voice", "non voice", "chat support", "email support", "messaging support",
        "data entry", "data processing", "back office", "customer support", "customer service",
        "lead generation", "lead follow-up", "appointment setter", "healthcare virtual assistant",
        "ecommerce assistant", "operations assistant", "sales support", "recruitment assistant",
    ]
    entry_indicators = [
        "no experience required", "no experience needed", "without experience",
        "experience not required", "entry level", "entry-level", "entrylevel",
        "training provided", "training will be provided", "open to beginners",
        "beginner friendly", "beginner-friendly", "will train", "willing to train",
        "fresh graduate", "fresh graduates", "open to fresh graduates", "junior",
    ]

    has_target_role = any(k in combined for k in role_indicators)
    has_entry_signal = any(k in combined for k in entry_indicators)
    has_explicit_one_year = any(re.search(pattern, combined, flags=re.I) for pattern in ONE_YEAR_OR_MORE_PATTERNS)

    if has_target_role:
        score += 4
        reasons.append("VA/non-voice/support role")
    if has_entry_signal:
        score += 4
        reasons.append("entry-level/no-experience indicator")
    elif not has_explicit_one_year:
        # Many legitimate entry-level listings omit an explicit "no experience" phrase.
        score += 1
        reasons.append("no explicit multi-year requirement found")
    if any(k in combined for k in ["data entry", "data processing", "customer support", "customer service", "back office"]):
        score += 2
        reasons.append("relevant support/data work")

    eligibility_text = normalize_text(f"{loc_text} {description}")
    if any(term in eligibility_text for term in PHILIPPINES_TERMS) or re.search(r"\bph\b", eligibility_text):
        score += 3
        reasons.append("Philippines/Filipino eligibility")

    # Require an actual target role/work-type indicator. This prevents unrelated remote jobs
    # from flooding the sheet while allowing multiple VA/support job titles.
    if not has_target_role:
        return False, score, [], "Not a target VA/non-voice/support role"

    reason = "; ".join(dict.fromkeys(reasons)) or "Matched stated job-search criteria"
    return True, score, matched, reason


def fetch_json(url: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_remotive() -> list[dict[str, Any]]:
    url = "https://remotive.com/api/remote-jobs"
    data = fetch_json(url, params={"limit": 100})
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    result = []
    for item in jobs:
        result.append({
            "source": "Remotive",
            "source_id": item.get("id"),
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "location": item.get("candidate_required_location", ""),
            "work_type": item.get("job_type", "remote"),
            "description": item.get("description", ""),
            "url": item.get("url", ""),
        })
    return result


def fetch_remoteok() -> list[dict[str, Any]]:
    data = fetch_json("https://remoteok.com/api")
    if not isinstance(data, list):
        return []
    result = []
    for item in data:
        if not isinstance(item, dict) or not item.get("position"):
            continue
        tags = item.get("tags") or []
        description = item.get("description", "")
        location = item.get("location", "Remote")
        result.append({
            "source": "Remote OK",
            "source_id": item.get("id"),
            "title": item.get("position", ""),
            "company": item.get("company", ""),
            "location": location,
            "work_type": "remote",
            "description": f"{description} {' '.join(tags)}",
            "url": item.get("url", ""),
            "apply_url": item.get("apply_url", ""),
        })
    return result


def fetch_arbeitnow() -> list[dict[str, Any]]:
    # Public API; pagination is capped to keep scheduled polling reasonable.
    result: list[dict[str, Any]] = []
    for page in range(1, 4):
        data = fetch_json("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
        jobs = data.get("data", []) if isinstance(data, dict) else []
        if not jobs:
            break
        for item in jobs:
            result.append({
                "source": "Arbeitnow",
                "source_id": item.get("slug") or item.get("id"),
                "title": item.get("title", ""),
                "company": item.get("company_name", ""),
                "location": item.get("location", ""),
                "work_type": "remote" if item.get("remote") else "onsite/unspecified",
                "description": item.get("description", ""),
                "url": item.get("url", ""),
            })
    return result



def fetch_himalayas() -> list[dict[str, Any]]:
    """Use Himalayas' public remote-jobs API with a Philippines + entry-level query."""
    result: list[dict[str, Any]] = []
    for page in range(1, 4):
        data = fetch_json(
            "https://himalayas.app/jobs/api/search",
            params={"country": "PH", "seniority": "Entry-level", "page": page},
        )
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        if not jobs:
            break
        for item in jobs:
            location_parts = []
            location_parts.extend(item.get("locationRestrictions") or [])
            timezone_parts = item.get("timezoneRestriction") or []
            result.append({
                "source": "Himalayas",
                "source_id": item.get("guid") or item.get("id"),
                "title": item.get("title", ""),
                "company": item.get("companyName", ""),
                "location": ", ".join(str(x) for x in location_parts) or "Philippines",
                "work_type": "remote",
                "description": item.get("description") or item.get("excerpt", ""),
                "url": item.get("applicationLink") or item.get("url") or "",
            })
    return result


def fetch_jobicy() -> list[dict[str, Any]]:
    """Use Jobicy's public remote-jobs API and let local filtering enforce PH eligibility."""
    data = fetch_json("https://jobicy.com/api/v2/remote-jobs", params={"count": 200})
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    result: list[dict[str, Any]] = []
    for item in jobs:
        if not isinstance(item, dict) or not item.get("jobTitle"):
            continue
        industries = item.get("jobIndustry") or []
        job_types = item.get("jobType") or []
        geo = item.get("jobGeo", "")
        result.append({
            "source": "Jobicy",
            "source_id": item.get("id"),
            "title": item.get("jobTitle", ""),
            "company": item.get("companyName", ""),
            "location": geo,
            "work_type": ", ".join(str(x) for x in job_types) or "remote",
            "description": f"{item.get('jobDescription', '')} {' '.join(str(x) for x in industries)} {item.get('jobLevel', '')}",
            "url": item.get("url", ""),
        })
    return result

def fetch_all_sources() -> list[dict[str, Any]]:
    all_jobs: list[dict[str, Any]] = []
    fetchers = [fetch_remotive, fetch_remoteok, fetch_arbeitnow, fetch_himalayas, fetch_jobicy]
    for fetcher in fetchers:
        try:
            jobs = fetcher()
            logging.info("%s returned %d records", fetcher.__name__, len(jobs))
            all_jobs.extend(jobs)
        except Exception as exc:
            logging.exception("Source %s failed: %s", fetcher.__name__, exc)
    return all_jobs


def validate_application_url(url: str, source: str) -> tuple[bool, str]:
    clean = canonical_url(url)
    if not clean:
        return False, ""
    try:
        response = requests.head(clean, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if response.status_code >= 400:
            response = requests.get(clean, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
        if response.status_code >= 400:
            return False, clean
        return True, clean
    except requests.RequestException as exc:
        logging.warning("URL validation failed for %s (%s): %s", source, clean, exc)
        # A temporary network failure is not proof the URL is bad.
        return True, clean


def process_jobs(raw_jobs: Iterable[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    now = utc_now()
    seen: set[str] = set()

    for raw in raw_jobs:
        title = clean_html_text(raw.get("title"))
        company = clean_html_text(raw.get("company")) or "Unknown"
        location = clean_html_text(raw.get("location")) or "Unspecified"
        description = clean_html_text(raw.get("description"))
        listing_url = canonical_url(str(raw.get("url") or ""))
        url = extract_application_url(raw.get("description"), listing_url, raw.get("apply_url"))
        source = clean_html_text(raw.get("source")) or "Unknown"
        job_id = stable_job_id(source, raw.get("source_id"), url, title, company)

        if job_id in seen:
            continue
        seen.add(job_id)

        passed, score, matched, reason = score_job(title, description, location)
        if not passed or not url:
            continue

        valid, final_url = validate_application_url(url, source)
        if not valid:
            continue

        snippet = description[:500].strip()
        rows.append(asdict(Job(
            job_id=job_id,
            date_found=now,
            last_checked=now,
            job_title=title,
            company_name=company,
            location=location,
            work_type=clean_html_text(raw.get("work_type")) or "Remote",
            job_source=source,
            description_snippet=snippet,
            matched_keywords=", ".join(matched),
            why_it_matches=reason,
            application_url=final_url,
            match_score=score,
        )))

    return pd.DataFrame(rows)


HEADERS_SHEET = [
    "Job ID", "Date Found", "Last Checked", "Job Title", "Company Name", "Location", "Work Type",
    "Job Source", "Description Snippet", "Matched Keywords", "Why It Matches", "Application URL",
    "Match Score", "Application Status", "Date Applied", "Response Status", "Date of Response",
    "Interview Status", "Date of Interview", "Final Result", "Follow-Up Date", "Notes",
]

MANUAL_COLUMNS = [
    "Application Status", "Date Applied", "Response Status", "Date of Response", "Interview Status",
    "Date of Interview", "Final Result", "Follow-Up Date", "Notes",
]

DEFAULT_MANUAL = ["Not Applied", "", "No Response", "", "Not Scheduled", "", "Pending", "", ""]


def require_google_dependencies() -> None:
    try:
        import google.auth  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        import googleapiclient  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Google dependencies are missing. Run: python -m pip install -r requirements.txt") from exc


def get_google_service():
    require_google_dependencies()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Missing {CREDENTIALS_FILE.name}. Download a Desktop App OAuth credential from Google Cloud and save it here."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), scopes)
            creds = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("sheets", "v4", credentials=creds)


SHEET_ID_FILE = APP_DIR / "sheet_id.txt"


def spreadsheet_id_from_env() -> str:
    env_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if env_id:
        return env_id
    try:
        if SHEET_ID_FILE.exists():
            return SHEET_ID_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def create_or_get_spreadsheet(service, title: str) -> str:
    sheet_id = spreadsheet_id_from_env()
    if sheet_id:
        return sheet_id
    body = {"properties": {"title": title}}
    result = service.spreadsheets().create(body=body, fields="spreadsheetId,spreadsheetUrl").execute()
    sid = result["spreadsheetId"]
    try:
        SHEET_ID_FILE.write_text(sid, encoding="utf-8")
    except OSError as exc:
        logging.warning("Could not persist spreadsheet ID locally: %s", exc)
    print(f"Created Google Sheet: {result.get('spreadsheetUrl', sid)}")
    return sid


def get_sheet_metadata(service, spreadsheet_id: str) -> dict[str, Any]:
    return service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()


def ensure_tabs_and_headers(service, spreadsheet_id: str) -> None:
    metadata = get_sheet_metadata(service, spreadsheet_id)
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in metadata.get("sheets", [])}
    requests_body = []
    for title in ["Jobs", "Applications", "Dashboard", "Settings"]:
        if title not in existing:
            requests_body.append({"addSheet": {"properties": {"title": title}}})
    if requests_body:
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests_body}).execute()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Jobs!A1:V1",
        valueInputOption="RAW",
        body={"values": [HEADERS_SHEET]},
    ).execute()

    # Applications is a live view of tracked applications.
    applications_headers = ["Job ID", "Job Title", "Company Name", "Application URL", "Application Status", "Date Applied", "Response Status", "Interview Status", "Final Result", "Follow-Up Date", "Notes"]
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Applications!A1:K1",
        valueInputOption="RAW",
        body={"values": [applications_headers]},
    ).execute()

    settings = [
        ["Setting", "Value"],
        ["Search Interval Minutes", os.getenv("SEARCH_INTERVAL_MINUTES", str(DEFAULT_INTERVAL_MINUTES))],
        ["Target Applicant", "Filipino / Philippines-eligible applicants"],
        ["Target Roles", "Non-voice; VA; Admin; Chat; Email; Data Entry; Customer Support; Lead Follow-Up; Healthcare VA"],
        ["Excluded", "Voice/call roles; clearly senior/multi-year roles; unclear Philippines eligibility"],
        ["Sources", "Remotive; Remote OK; Arbeitnow; Himalayas; Jobicy"],
        ["Automatic Application Submission", "DISABLED"],
        ["Note", "Manual application tracking fields are preserved during sync; the same Google Sheet is reused."],
    ]
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Settings!A1:B8",
        valueInputOption="RAW",
        body={"values": settings},
    ).execute()


def read_jobs_sheet(service, spreadsheet_id: str) -> pd.DataFrame:
    result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="Jobs!A:V").execute()
    values = result.get("values", [])
    if not values:
        return pd.DataFrame(columns=HEADERS_SHEET)
    header = values[0]
    rows = []
    for row in values[1:]:
        padded = row + [""] * (len(header) - len(row))
        rows.append(padded[:len(header)])
    return pd.DataFrame(rows, columns=header)


def row_to_values(job: dict[str, Any], existing: dict[str, Any] | None = None) -> list[Any]:
    existing = existing or {}
    return [
        job.get("job_id", ""), job.get("date_found", ""), job.get("last_checked", ""), job.get("job_title", ""),
        job.get("company_name", ""), job.get("location", ""), job.get("work_type", ""), job.get("job_source", ""),
        job.get("description_snippet", ""), job.get("matched_keywords", ""), job.get("why_it_matches", ""),
        job.get("application_url", ""), job.get("match_score", ""),
        existing.get("Application Status", "Not Applied"), existing.get("Date Applied", ""),
        existing.get("Response Status", "No Response"), existing.get("Date of Response", ""),
        existing.get("Interview Status", "Not Scheduled"), existing.get("Date of Interview", ""),
        existing.get("Final Result", "Pending"), existing.get("Follow-Up Date", ""), existing.get("Notes", ""),
    ]


def sync_to_google_sheet(service, spreadsheet_id: str, jobs_df: pd.DataFrame) -> tuple[int, int]:
    existing_df = read_jobs_sheet(service, spreadsheet_id)
    existing_map: dict[str, dict[str, Any]] = {}
    row_index: dict[str, int] = {}
    if not existing_df.empty and "Job ID" in existing_df.columns:
        for idx, row in existing_df.iterrows():
            jid = str(row.get("Job ID", "")).strip()
            if jid:
                existing_map[jid] = row.to_dict()
                row_index[jid] = idx + 2

    values_to_append: list[list[Any]] = []
    update_requests: list[dict[str, Any]] = []
    added = updated = 0
    now = utc_now()

    for _, row in jobs_df.iterrows():
        job = row.to_dict()
        jid = str(job["job_id"])
        if jid in existing_map:
            old = existing_map[jid]
            merged = dict(job)
            merged["date_found"] = old.get("Date Found") or job.get("date_found", now)
            merged["last_checked"] = now
            # Only update automated columns. Manual columns are copied from old.
            for col in MANUAL_COLUMNS:
                merged[col] = old.get(col, "")
            values = row_to_values(merged, old)
            row_num = row_index[jid]
            update_requests.append({
                "range": f"Jobs!A{row_num}:V{row_num}",
                "values": [values],
            })
            updated += 1
        else:
            values_to_append.append(row_to_values(job))
            added += 1

    if values_to_append:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Jobs!A:V",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values_to_append},
        ).execute()

    if update_requests:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": update_requests},
        ).execute()

    rebuild_views(service, spreadsheet_id)
    return added, updated


def rebuild_views(service, spreadsheet_id: str) -> None:
    # Applications view: all jobs with an application-related status or response.
    jobs = read_jobs_sheet(service, spreadsheet_id)
    app_headers = ["Job ID", "Job Title", "Company Name", "Application URL", "Application Status", "Date Applied", "Response Status", "Interview Status", "Final Result", "Follow-Up Date", "Notes"]
    app_rows = []
    if not jobs.empty:
        for _, r in jobs.iterrows():
            status = str(r.get("Application Status", "Not Applied"))
            response = str(r.get("Response Status", "No Response"))
            if status != "Not Applied" or response != "No Response":
                app_rows.append([
                    r.get("Job ID", ""), r.get("Job Title", ""), r.get("Company Name", ""), r.get("Application URL", ""),
                    status, r.get("Date Applied", ""), response, r.get("Interview Status", ""), r.get("Final Result", ""),
                    r.get("Follow-Up Date", ""), r.get("Notes", ""),
                ])
    service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range="Applications!A2:K").execute()
    if app_rows:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"Applications!A2:K{len(app_rows)+1}",
            valueInputOption="RAW",
            body={"values": app_rows},
        ).execute()

    build_dashboard(service, spreadsheet_id, jobs)
    apply_sheet_formatting(service, spreadsheet_id)


def build_dashboard(service, spreadsheet_id: str, jobs: pd.DataFrame) -> None:
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    rows = [
        ["Metric", "Value"],
        ["Total Jobs Found", "=COUNTA(Jobs!A2:A)"],
        ["Jobs Found Today", f'=COUNTIF(Jobs!B2:B,"{today}*")'],
        ["Not Applied", '=COUNTIF(Jobs!N2:N,"Not Applied")'],
        ["Applications Submitted", '=COUNTIF(Jobs!N2:N,"Applied")+COUNTIF(Jobs!N2:N,"Application Submitted")'],
        ["Follow-Ups Needed", '=COUNTIF(Jobs!N2:N,"Follow-Up Needed")'],
        ["Interviews Scheduled", '=COUNTIF(Jobs!R2:R,"Scheduled")+COUNTIF(Jobs!N2:N,"Interview Scheduled")'],
        ["Offers Received", '=COUNTIF(Jobs!N2:N,"Offer Received")'],
        ["Rejections", '=COUNTIF(Jobs!N2:N,"Rejected")+COUNTIF(Jobs!P2:P,"Rejected")+COUNTIF(Jobs!T2:T,"Rejected")'],
        ["Follow-Ups Due", '=COUNTIFS(Jobs!U2:U,"<="&TODAY(),Jobs!U2:U,"<>",Jobs!N2:N,"<>Rejected",Jobs!N2:N,"<>Withdrawn")'],
        ["Last Local Sync", utc_now()],
    ]
    service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range="Dashboard!A1:H20").execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Dashboard!A5:B15",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()

    # Add a polished title/subtitle and live KPI cards in the unused area.
    card_values = [
        ["CVA JOB TRACKER", "", "", ""],
        ["Filipino / Philippines-eligible • Entry-Level • Non-Voice", "", "", ""],
        ["Total Jobs", "", "Applied", ""],
        ["=COUNTA(Jobs!A2:A)", "", '=COUNTIF(Jobs!N2:N,"Applied")+COUNTIF(Jobs!N2:N,"Application Submitted")', ""],
        ["", "", "", ""],
        ["Interviews", "", "Rejected", ""],
        ['=COUNTIF(Jobs!R2:R,"Scheduled")+COUNTIF(Jobs!N2:N,"Interview Scheduled")', "", '=COUNTIF(Jobs!N2:N,"Rejected")+COUNTIF(Jobs!P2:P,"Rejected")+COUNTIF(Jobs!T2:T,"Rejected")', ""],
    ]
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Dashboard!D1:G7",
        valueInputOption="USER_ENTERED",
        body={"values": card_values},
    ).execute()


def apply_sheet_formatting(service, spreadsheet_id: str) -> None:
    metadata = get_sheet_metadata(service, spreadsheet_id)
    sheet_props = {s["properties"]["title"]: s["properties"] for s in metadata.get("sheets", [])}
    sheet_ids = {title: props["sheetId"] for title, props in sheet_props.items()}

    # Professional but restrained palette.
    navy = {"red": 0.09, "green": 0.22, "blue": 0.36}
    blue = {"red": 0.18, "green": 0.36, "blue": 0.62}
    light_blue = {"red": 0.91, "green": 0.95, "blue": 0.99}
    very_light = {"red": 0.97, "green": 0.98, "blue": 1.0}
    green = {"red": 0.84, "green": 0.93, "blue": 0.86}
    red = {"red": 0.97, "green": 0.86, "blue": 0.86}
    yellow = {"red": 1.0, "green": 0.95, "blue": 0.80}
    white = {"red": 1.0, "green": 1.0, "blue": 1.0}
    dark = {"red": 0.12, "green": 0.12, "blue": 0.14}
    border = {"red": 0.82, "green": 0.86, "blue": 0.92}

    requests_body = []

    def update_props(title: str, hidden_gridlines: bool, frozen_rows: int) -> None:
        sid = sheet_ids.get(title)
        if sid is None:
            return
        requests_body.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sid,
                    "gridProperties": {"frozenRowCount": frozen_rows, "hideGridlines": hidden_gridlines},
                },
                "fields": "gridProperties.frozenRowCount,gridProperties.hideGridlines",
            }
        })

    def format_range(title: str, start_row: int, end_row: int, start_col: int, end_col: int,
                     bg: dict | None = None, fg: dict | None = None, bold: bool | None = None,
                     font_size: int | None = None, wrap: bool | None = None, h_align: str | None = None,
                     v_align: str | None = None) -> None:
        sid = sheet_ids.get(title)
        if sid is None:
            return
        cell_format = {}
        if bg is not None:
            cell_format["backgroundColor"] = bg
        text_format = {}
        if fg is not None:
            text_format["foregroundColor"] = fg
        if bold is not None:
            text_format["bold"] = bold
        if font_size is not None:
            text_format["fontSize"] = font_size
        if text_format:
            cell_format["textFormat"] = text_format
        if wrap is not None:
            cell_format["wrapStrategy"] = "WRAP" if wrap else "OVERFLOW_CELL"
        if h_align is not None:
            cell_format["horizontalAlignment"] = h_align
        if v_align is not None:
            cell_format["verticalAlignment"] = v_align
        fields = []
        if bg is not None: fields.append("userEnteredFormat.backgroundColor")
        if text_format: fields.append("userEnteredFormat.textFormat")
        if wrap is not None: fields.append("userEnteredFormat.wrapStrategy")
        if h_align is not None: fields.append("userEnteredFormat.horizontalAlignment")
        if v_align is not None: fields.append("userEnteredFormat.verticalAlignment")
        requests_body.append({
            "repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": start_row, "endRowIndex": end_row,
                          "startColumnIndex": start_col, "endColumnIndex": end_col},
                "cell": {"userEnteredFormat": cell_format},
                "fields": ",".join(fields),
            }
        })

    def border_range(title: str, start_row: int, end_row: int, start_col: int, end_col: int) -> None:
        sid = sheet_ids.get(title)
        if sid is None:
            return
        requests_body.append({
            "updateBorders": {
                "range": {"sheetId": sid, "startRowIndex": start_row, "endRowIndex": end_row,
                          "startColumnIndex": start_col, "endColumnIndex": end_col},
                "top": {"style": "SOLID", "color": border},
                "bottom": {"style": "SOLID", "color": border},
                "left": {"style": "SOLID", "color": border},
                "right": {"style": "SOLID", "color": border},
                "innerHorizontal": {"style": "SOLID", "color": border},
                "innerVertical": {"style": "SOLID", "color": border},
            }
        })

    for title, frozen in [("Jobs", 1), ("Applications", 1), ("Dashboard", 4), ("Settings", 1)]:
        update_props(title, True, frozen)

    # Jobs sheet.
    format_range("Jobs", 0, 1, 0, 22, bg=navy, fg=white, bold=True, font_size=10, wrap=True, h_align="CENTER", v_align="MIDDLE")
    format_range("Jobs", 1, 5000, 0, 22, bg=white, fg=dark, font_size=10, wrap=True, v_align="TOP")
    border_range("Jobs", 0, 500, 0, 22)

    # Applications sheet.
    format_range("Applications", 0, 1, 0, 11, bg=blue, fg=white, bold=True, font_size=10, wrap=True, h_align="CENTER", v_align="MIDDLE")
    format_range("Applications", 1, 5000, 0, 11, bg=white, fg=dark, font_size=10, wrap=True, v_align="TOP")
    border_range("Applications", 0, 500, 0, 11)

    # Settings sheet.
    format_range("Settings", 0, 1, 0, 2, bg=navy, fg=white, bold=True, font_size=10, wrap=True, h_align="CENTER")
    format_range("Settings", 1, 20, 0, 2, bg=very_light, fg=dark, font_size=10, wrap=True, v_align="TOP")
    border_range("Settings", 0, 10, 0, 2)

    # Dashboard sheet, including title and KPI cards.
    sid = sheet_ids.get("Dashboard")
    if sid is not None:
        format_range("Dashboard", 0, 2, 3, 7, bg=navy, fg=white, bold=True, font_size=18, wrap=True, h_align="CENTER", v_align="MIDDLE")
        format_range("Dashboard", 2, 3, 3, 7, bg=navy, fg=white, bold=False, font_size=10, wrap=True, h_align="CENTER", v_align="MIDDLE")
        for c0, c1 in [(3,4),(4,5),(5,6),(6,7)]:
            format_range("Dashboard", 3, 5, c0, c1, bg=light_blue, fg=dark, bold=True, font_size=11, wrap=True, h_align="CENTER", v_align="MIDDLE")
        format_range("Dashboard", 4, 5, 3, 7, bg=light_blue, fg=dark, bold=True, font_size=14, wrap=True, h_align="CENTER", v_align="MIDDLE")
        format_range("Dashboard", 6, 8, 3, 7, bg=light_blue, fg=dark, bold=True, font_size=11, wrap=True, h_align="CENTER", v_align="MIDDLE")
        format_range("Dashboard", 4, 5, 0, 2, bg=navy, fg=white, bold=True, font_size=10, wrap=True, h_align="CENTER", v_align="MIDDLE")
        format_range("Dashboard", 5, 16, 0, 2, bg=very_light, fg=dark, font_size=10, wrap=True, v_align="MIDDLE")
        border_range("Dashboard", 4, 16, 0, 2)
        border_range("Dashboard", 0, 8, 3, 7)

    # Column widths for readability.
    width_map = {
        "Jobs": {0:150, 1:145, 2:145, 3:230, 4:180, 5:140, 6:100, 7:115, 8:360, 9:230, 10:230, 11:300, 12:85, 13:150, 14:110, 15:135, 16:110, 17:135, 18:110, 19:135, 20:115, 21:250},
        "Applications": {0:150, 1:230, 2:180, 3:300, 4:155, 5:110, 6:135, 7:135, 8:135, 9:115, 10:260},
        "Settings": {0:230, 1:560},
        "Dashboard": {0:220, 1:150, 2:25, 3:150, 4:150, 5:150, 6:150, 7:30},
    }
    for title, cols in width_map.items():
        sid = sheet_ids.get(title)
        if sid is None:
            continue
        for col, width in cols.items():
            requests_body.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            })

    # Helpful data-entry dropdowns in the authoritative Jobs sheet.
    jobs_sid = sheet_ids.get("Jobs")
    if jobs_sid is not None:
        dropdowns = [
            (13, ["Not Applied", "Applied", "Application Submitted", "Follow-Up Needed", "Interview Scheduled", "Interview Completed", "Offer Received", "Rejected", "Withdrawn", "Closed"]),
            (15, ["No Response", "Received Response", "Rejected", "Interview Request", "Offer", "Other"]),
            (17, ["Not Scheduled", "Scheduled", "Completed", "Rescheduled", "Cancelled"]),
            (19, ["Pending", "Rejected", "Accepted", "Withdrawn", "Position Closed"]),
        ]
        for col, values in dropdowns:
            requests_body.append({
                "setDataValidation": {
                    "range": {"sheetId": jobs_sid, "startRowIndex": 1, "endRowIndex": 5000,
                              "startColumnIndex": col, "endColumnIndex": col + 1},
                    "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in values]},
                             "showCustomUi": True, "strict": False},
                }
            })

        # Reset existing conditional-format rules we own, then apply clean status highlighting.
        existing_cf = sheet_props.get("Jobs", {}).get("conditionalFormats", [])
        for idx in range(len(existing_cf) - 1, -1, -1):
            requests_body.append({"deleteConditionalFormatRule": {"sheetId": jobs_sid, "index": idx}})

        def cf_text(col_letter: str, text_value: str, fill: dict) -> None:
            requests_body.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{"sheetId": jobs_sid, "startRowIndex": 1, "endRowIndex": 5000,
                                    "startColumnIndex": 0, "endColumnIndex": 22}],
                        "booleanRule": {
                            "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": f'=${col_letter}2="{text_value}"'}]},
                            "format": {"backgroundColor": fill},
                        },
                    },
                    "index": 0,
                }
            })
        cf_text("N", "Applied", green)
        cf_text("N", "Application Submitted", green)
        cf_text("N", "Interview Scheduled", yellow)
        cf_text("N", "Rejected", red)
        cf_text("T", "Accepted", green)
        cf_text("T", "Rejected", red)
        requests_body.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": jobs_sid, "startRowIndex": 1, "endRowIndex": 5000,
                                "startColumnIndex": 20, "endColumnIndex": 21}],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=AND($U2<>"",$U2<=TODAY(),$N2<>"Rejected",$N2<>"Withdrawn")'}]},
                        "format": {"backgroundColor": yellow},
                    },
                },
                "index": 0,
            }
        })

    # Clickable/filterable job tables.
    if jobs_sid is not None:
        requests_body.append({
            "setBasicFilter": {
                "filter": {"range": {"sheetId": jobs_sid, "startRowIndex": 0, "endRowIndex": 5000, "startColumnIndex": 0, "endColumnIndex": 22}}
            }
        })
    apps_sid = sheet_ids.get("Applications")
    if apps_sid is not None:
        requests_body.append({
            "setBasicFilter": {
                "filter": {"range": {"sheetId": apps_sid, "startRowIndex": 0, "endRowIndex": 5000, "startColumnIndex": 0, "endColumnIndex": 11}}
            }
        })

    if requests_body:
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests_body}).execute()


def run_once(use_google: bool = True) -> None:
    logging.info("Starting job search")
    raw = fetch_all_sources()
    df = process_jobs(raw)
    print(f"Fetched {len(raw)} raw records; {len(df)} matched the configured criteria.")
    if df.empty:
        print("No matching jobs were found in the configured sources on this run.")
        return

    if not use_google:
        out = APP_DIR / "entry_level_non_voice_va_jobs.csv"
        df.to_csv(out, index=False)
        print(f"Offline result saved to: {out}")
        return

    service = get_google_service()
    sid = create_or_get_spreadsheet(service, os.getenv("GOOGLE_SHEET_TITLE", DEFAULT_SHEET_TITLE))
    ensure_tabs_and_headers(service, sid)
    added, updated = sync_to_google_sheet(service, sid, df)
    print(f"Google Sheet sync complete: {added} new, {updated} updated.")
    print(f"Spreadsheet ID: {sid}")
    print("Open the Google Sheet and use the Application Status / Date Applied / Response / Interview / Follow-Up fields to track applications.")


def continuous_loop() -> None:
    interval = max(5, int(os.getenv("SEARCH_INTERVAL_MINUTES", str(DEFAULT_INTERVAL_MINUTES))))
    # Keep the default conservative because some public sources impose low polling limits.
    if interval < 360:
        print("Configured interval is below 360 minutes. To respect public-source rate guidance, using 360 minutes (6 hours).")
        interval = 360
    print(f"Continuous mode enabled. Searching every {interval} minutes. Press Ctrl+C to stop.")
    while True:
        started = time.time()
        try:
            run_once(use_google=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            logging.exception("Scheduled run failed: %s", exc)
            print(f"Run failed: {exc}. See {LOG_FILE.name}; the scheduler will continue.")
        elapsed = time.time() - started
        sleep_seconds = max(5, interval * 60 - int(elapsed))
        print(f"Next search in approximately {sleep_seconds // 60} minute(s).")
        time.sleep(sleep_seconds)


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Entry-level non-voice VA job finder and Google Sheets tracker")
    parser.add_argument("--once", action="store_true", help="Run one search and exit")
    parser.add_argument("--offline-test", action="store_true", help="Fetch sources and save matched jobs to CSV without Google Sheets")
    parser.add_argument("--open-sheet", action="store_true", help="Open the configured Google Sheet in the browser")
    args = parser.parse_args()

    try:
        if args.open_sheet:
            sid = spreadsheet_id_from_env()
            if not sid:
                print("GOOGLE_SHEET_ID is not configured yet. Run the tracker once to create a sheet, then copy its ID into .env.")
                return 1
            webbrowser.open(f"https://docs.google.com/spreadsheets/d/{sid}/edit")
            return 0
        if args.offline_test:
            run_once(use_google=False)
            return 0
        if args.once:
            run_once(use_google=True)
            return 0
        continuous_loop()
    except KeyboardInterrupt:
        print("Stopped safely.")
        return 0
    except Exception as exc:
        logging.exception("Fatal error: %s", exc)
        print(f"ERROR: {exc}")
        print(f"See {LOG_FILE.name} for details.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
