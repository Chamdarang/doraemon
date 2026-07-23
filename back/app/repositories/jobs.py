from app.schemas import Job, now_iso
from app.repositories.errors import ProjectNotFoundError


class JobRepositoryMixin:
    def save_job(self, job: Job) -> None:
        job.updated_at = now_iso()
        path = self.project_dir(job.project_id) / ".pocket" / "jobs" / f"{job.id}.json"
        self._write_text_atomic(path, job.model_dump_json(indent=2), backup=True)

    def get_job(self, project_id: str, job_id: str) -> Job:
        path = self.project_dir(project_id) / ".pocket" / "jobs" / f"{job_id}.json"
        if not path.is_file() and not self._backup_path(path).is_file():
            raise ProjectNotFoundError(job_id)
        return self._read_model_with_backup(path, Job)

    def list_jobs(self, project_id: str) -> list[Job]:
        jobs_dir = self.project_dir(project_id) / ".pocket" / "jobs"
        jobs = []
        for path in jobs_dir.glob("*.json"):
            try:
                jobs.append(self._read_model_with_backup(path, Job))
            except (OSError, ValueError):
                continue
        return sorted(jobs, key=lambda item: item.created_at, reverse=True)
