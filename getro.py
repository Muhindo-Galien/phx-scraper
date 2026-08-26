import re
from typing import Any

from schemas import Company, Compensation, Job, Location, Seniority, WorkMode, epoch_to_datetime

_POINT_RE = re.compile(r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", re.IGNORECASE)
_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")
_UNDEFINED_PERIOD = "period_not_defined"


def _snake(key: str) -> str:
    return _CAMEL_RE.sub("_", key).lower()


def normalize_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {_snake(k): normalize_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_keys(item) for item in value]
    return value


def _cents_to_units(cents: Any) -> float | None:
    if cents is None:
        return None
    try:
        return round(int(cents) / 100, 2)
    except (TypeError, ValueError):
        return None


def _parse_point(point: str | None) -> tuple[float | None, float | None]:
    if not point:
        return None, None
    match = _POINT_RE.search(point)
    if match is None:
        return None, None
    return float(match.group(2)), float(match.group(1))


def _strings(values: Any) -> list[str]:
    return [item for item in values if isinstance(item, str)] if isinstance(values, list) else []


def _locations(raw: dict[str, Any]) -> list[Location]:
    details = raw.get("location_details")
    if isinstance(details, list):
        parsed = []
        for detail in details:
            if not isinstance(detail, dict) or not detail.get("name"):
                continue
            latitude, longitude = _parse_point(detail.get("point"))
            parsed.append(
                Location(
                    name=detail["name"],
                    area_type=detail.get("area_type"),
                    latitude=latitude,
                    longitude=longitude,
                )
            )
        if parsed:
            return parsed
    return [Location(name=name) for name in _strings(raw.get("locations"))]


def _company(raw: dict[str, Any]) -> Company:
    org = raw.get("organization")
    if not isinstance(org, dict):
        return Company(name="Unknown")
    return Company(
        id=org.get("id"),
        name=org.get("name") or "Unknown",
        slug=org.get("slug"),
        logo_url=org.get("logo_url"),
        stage=org.get("stage"),
        head_count=org.get("head_count"),
        industries=_strings(org.get("industry_tags")),
    )


def _compensation(raw: dict[str, Any]) -> Compensation | None:
    if not raw.get("compensation_public"):
        return None
    minimum = _cents_to_units(raw.get("compensation_amount_min_cents"))
    maximum = _cents_to_units(raw.get("compensation_amount_max_cents"))
    if minimum is None and maximum is None:
        return None
    period = raw.get("compensation_period")
    return Compensation(
        min_amount=minimum,
        max_amount=maximum,
        currency=raw.get("compensation_currency") or "USD",
        period=None if period == _UNDEFINED_PERIOD else period,
        offers_equity=bool(raw.get("compensation_offers_equity")),
    )


def parse_job(raw: dict[str, Any]) -> Job | None:
    if not isinstance(raw, dict):
        return None
    job = normalize_keys(raw)
    if job.get("id") is None or not isinstance(job.get("title"), str) or not job["title"].strip():
        return None
    try:
        job_id = int(job["id"])
    except (TypeError, ValueError):
        return None
    return Job(
        id=job_id,
        slug=job.get("slug"),
        title=job["title"].strip(),
        url=job.get("url"),
        company=_company(job),
        locations=_locations(job),
        work_mode=WorkMode(job.get("work_mode")),
        seniority=Seniority(job.get("seniority")),
        skills=_strings(job.get("skills")),
        compensation=_compensation(job),
        posted_at=epoch_to_datetime(job.get("created_at")),
        source=job.get("source"),
        featured=bool(job.get("featured")),
        has_description=bool(job.get("has_description")),
    )


def extract_jobs_state(payload: dict[str, Any]) -> dict[str, Any]:
    node: Any = payload
    for key in ("props", "page_props", "initial_state", "jobs"):
        if isinstance(node, dict) and isinstance(node.get(key), dict):
            node = node[key]
    return node if isinstance(node, dict) and "found" in node else {"found": [], "total": 0}


def parse_payload(payload: dict[str, Any]) -> tuple[list[Job], int]:
    normalized = normalize_keys(payload)
    results = normalized.get("results")
    if isinstance(results, dict) and isinstance(results.get("jobs"), list):
        raw_jobs, total = results["jobs"], results.get("count")
    else:
        state = extract_jobs_state(normalized)
        raw_jobs, total = state.get("found") or [], state.get("total")

    jobs = [job for raw in raw_jobs if (job := parse_job(raw)) is not None]
    return jobs, total if isinstance(total, int) else len(jobs)
