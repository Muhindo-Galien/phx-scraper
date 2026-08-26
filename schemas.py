from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field


class _Lenient(StrEnum):
    @classmethod
    def _missing_(cls, value: object) -> "_Lenient":
        return cls.UNKNOWN


class WorkMode(_Lenient):
    ON_SITE = "on_site"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class Seniority(_Lenient):
    INTERNSHIP = "internship"
    ENTRY = "entry"
    ASSOCIATE = "associate"
    MID_SENIOR = "mid_senior"
    DIRECTOR = "director"
    EXECUTIVE = "executive"
    UNKNOWN = "unknown"


_WORK_MODE_LABELS = {
    WorkMode.ON_SITE: "On-site",
    WorkMode.HYBRID: "Hybrid",
    WorkMode.REMOTE: "Remote",
    WorkMode.UNKNOWN: "Not specified",
}

_SENIORITY_LABELS = {
    Seniority.INTERNSHIP: "Internship",
    Seniority.ENTRY: "Entry level",
    Seniority.ASSOCIATE: "Associate",
    Seniority.MID_SENIOR: "Mid-Senior level",
    Seniority.DIRECTOR: "Director",
    Seniority.EXECUTIVE: "Executive",
    Seniority.UNKNOWN: "Not specified",
}

_PERIOD_LABELS = {"year": "yr", "month": "mo", "week": "wk", "day": "day", "hour": "hr"}


class Company(BaseModel):
    id: int | None = None
    name: str
    slug: str | None = None
    logo_url: str | None = None
    stage: str | None = Field(None, examples=["series_b"])
    head_count: int | None = None
    industries: list[str] = []


class Location(BaseModel):
    name: str
    area_type: str | None = Field(None, examples=["locality"])
    latitude: float | None = None
    longitude: float | None = None


class Compensation(BaseModel):
    min_amount: float | None = None
    max_amount: float | None = None
    currency: str = "USD"
    period: str | None = Field(None, examples=["year"])
    offers_equity: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def text(self) -> str | None:
        lo, hi = self.min_amount, self.max_amount
        if lo is None and hi is None:
            return None
        symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(self.currency, f"{self.currency} ")

        def money(v: float) -> str:
            return f"{symbol}{v:,.0f}"

        if lo is not None and hi is not None and lo != hi:
            body = f"{money(lo)} - {money(hi)}"
        else:
            body = money(lo if lo is not None else hi)  # type: ignore[arg-type]
        if self.period:
            body += f"/{_PERIOD_LABELS.get(self.period, self.period)}"
        if self.offers_equity:
            body += " + equity"
        return body


class Job(BaseModel):
    id: int
    slug: str | None = None
    title: str
    url: str | None = None
    company: Company
    locations: list[Location] = []
    work_mode: WorkMode = WorkMode.UNKNOWN
    seniority: Seniority = Seniority.UNKNOWN
    skills: list[str] = []
    compensation: Compensation | None = None
    posted_at: datetime | None = None
    source: str | None = Field(None, examples=["career_page"])
    featured: bool = False
    has_description: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def location_text(self) -> str:
        if not self.locations:
            return "Remote" if self.work_mode is WorkMode.REMOTE else "Not specified"
        primary = self.locations[0].name
        extra = len(self.locations) - 1
        return f"{primary} +{extra} more" if extra else primary

    @computed_field  # type: ignore[prop-decorator]
    @property
    def work_mode_label(self) -> str:
        return _WORK_MODE_LABELS[self.work_mode]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def seniority_label(self) -> str:
        return _SENIORITY_LABELS[self.seniority]


class JobPage(BaseModel):
    items: list[Job]
    count: int = Field(description="Jobs in this response.")
    total: int = Field(description="Jobs matching the query upstream.")
    page: int = 1
    per_page: int = 20

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_more(self) -> bool:
        return self.page * self.per_page < self.total

    @classmethod
    def of(cls, items: list[Job], total: int | None = None, page: int = 1, per_page: int = 20) -> "JobPage":
        return cls(
            items=items,
            count=len(items),
            total=total if total is not None else len(items),
            page=page,
            per_page=per_page,
        )


def epoch_to_datetime(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)
