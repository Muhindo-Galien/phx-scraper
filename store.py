from collections.abc import Iterable

from schemas import Job, JobPage


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}

    def __len__(self) -> int:
        return len(self._jobs)

    def upsert_many(self, jobs: Iterable[Job]) -> int:
        before = len(self._jobs)
        for job in jobs:
            self._jobs[job.id] = job
        return len(self._jobs) - before

    def get(self, job_id: int) -> Job | None:
        return self._jobs.get(job_id)

    def delete(self, job_id: int) -> bool:
        return self._jobs.pop(job_id, None) is not None

    def search(
        self,
        q: str | None = None,
        company: str | None = None,
        work_mode: str | None = None,
        seniority: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> JobPage:
        items = sorted(
            self._jobs.values(),
            key=lambda job: (job.posted_at is None, job.posted_at),
            reverse=True,
        )

        if q:
            items = [job for job in items if _matches_text(job, q.lower())]
        if company:
            needle = company.lower()
            items = [job for job in items if needle in {(job.company.slug or "").lower(), job.company.name.lower()}]
        if work_mode:
            items = [job for job in items if job.work_mode.value == work_mode]
        if seniority:
            items = [job for job in items if job.seniority.value == seniority]

        start = (page - 1) * per_page
        return JobPage.of(items[start : start + per_page], total=len(items), page=page, per_page=per_page)


def _matches_text(job: Job, needle: str) -> bool:
    return (
        needle in job.title.lower()
        or needle in job.company.name.lower()
        or any(needle in skill.lower() for skill in job.skills)
    )
