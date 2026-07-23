import json
import shutil
from pathlib import PurePosixPath
from uuid import uuid4

from app.schemas import (
    BackendGenerationSegment,
    FrontendGenerationSegment,
    GenerationBundle,
    ImprovementBundle,
)
from app.integrations.llm.structured import parse_structured_output


class GenerationArtifactsMixin:
    """Cache, validate and transactionally write generated source artifacts."""

    def _load_cached_repair(self, project_id: str, job_id: str) -> ImprovementBundle | None:
        path = self.store.project_dir(project_id) / ".pocket" / "repair-bundles" / f"{job_id}.json"
        if not path.is_file():
            return None
        try:
            return ImprovementBundle.model_validate_json(path.read_text("utf-8"))
        except (ValueError, OSError):
            return None

    def _validate_repair_bundle(self, project_id: str, bundle: ImprovementBundle) -> None:
        self._validate_bundle(project_id, GenerationBundle(
            summary=bundle.summary,
            files=[item.model_dump() for item in bundle.files],
            runtime=bundle.runtime or self.store.get(project_id).runtime,
        ))
        for path in bundle.deleted_files:
            rel = PurePosixPath(path)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] not in {"back", "front"}:
                raise ValueError(f"허용되지 않은 삭제 경로: {path}")

    def _validate_improvement(self, project_id, bundle, plan) -> None:
        root = self.store.project_dir(project_id)
        allowed = list(plan.draft.changes)
        for change in allowed:
            rel = PurePosixPath(change.path)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] not in {"back", "front"}:
                raise ValueError(f"허용되지 않은 개선 경로: {change.path}")
        for item in bundle.files:
            action = "modify" if root.joinpath(*PurePosixPath(item.path).parts).exists() else "add"
            if not any(
                change.action == action and self._approved_path_matches(change.path, item.path)
                for change in allowed
            ):
                raise ValueError(f"승인되지 않은 파일 변경: {item.path}")
        for path in bundle.deleted_files:
            rel = PurePosixPath(path)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] not in {"back", "front"}:
                raise ValueError(f"허용되지 않은 삭제 경로: {path}")
            if not any(
                change.action == "delete" and self._approved_path_matches(change.path, path)
                for change in allowed
            ):
                raise ValueError(f"승인되지 않은 파일 삭제: {path}")
        self._validate_bundle(
            project_id,
            GenerationBundle(
                summary=bundle.summary,
                files=[item.model_dump() for item in bundle.files],
                runtime=bundle.runtime or self.store.get(project_id).runtime,
            ),
        )

    @staticmethod
    def _approved_path_matches(approved_path: str, candidate_path: str) -> bool:
        if not any(marker in approved_path for marker in ("*", "?", "[")):
            return approved_path == candidate_path
        return PurePosixPath(candidate_path).match(approved_path)

    @staticmethod
    def _parse_improvement_bundle(text: str) -> ImprovementBundle:
        return parse_structured_output(text, ImprovementBundle)

    def _improvement_cache_path(self, project_id: str):
        return self.store.project_dir(project_id) / ".pocket" / "improvement-bundle.json"

    def _load_cached_improvement(self, project_id: str, plan_updated_at: str) -> ImprovementBundle | None:
        path = self._improvement_cache_path(project_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text("utf-8"))
            if payload.get("plan_updated_at") != plan_updated_at:
                return None
            return ImprovementBundle.model_validate(payload["bundle"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def _save_cached_improvement(self, project_id: str, plan_updated_at: str, bundle: ImprovementBundle) -> None:
        self.store._write_text_atomic(
            self._improvement_cache_path(project_id),
            json.dumps({"plan_updated_at": plan_updated_at, "bundle": bundle.model_dump(mode="json")}, ensure_ascii=False, indent=2),
        )

    def _write_improvement(self, project_id: str, bundle: ImprovementBundle, job_id: str) -> None:
        root = self.store.project_dir(project_id)
        backup = root / ".pocket" / "backup" / f"improvement-{job_id}"
        paths = [item.path for item in bundle.files] + bundle.deleted_files
        for rel in paths:
            source = root.joinpath(*PurePosixPath(rel).parts)
            if source.is_file():
                destination = backup.joinpath(*PurePosixPath(rel).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        try:
            for item in bundle.files:
                target = root.joinpath(*PurePosixPath(item.path).parts)
                self.store._write_text_atomic(target, item.content)
            for rel in bundle.deleted_files:
                target = root.joinpath(*PurePosixPath(rel).parts)
                if target.is_file():
                    target.unlink()
        except Exception:
            for rel in paths:
                target = root.joinpath(*PurePosixPath(rel).parts)
                previous = backup.joinpath(*PurePosixPath(rel).parts)
                if previous.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(previous, target)
                elif target.is_file():
                    target.unlink()
            shutil.rmtree(backup, ignore_errors=True)
            raise
        else:
            shutil.rmtree(backup, ignore_errors=True)

    def _generation_cache_path(self, project_id: str):
        return self.store.project_dir(project_id) / ".pocket" / "generation-bundle.json"

    def _generation_segment_cache_path(self, project_id: str, target: str):
        return self.store.project_dir(project_id) / ".pocket" / f"generation-{target}-segment.json"

    def _load_cached_generation_segment(
        self,
        project_id: str,
        plan_updated_at: str,
        generation_mode: str,
        target: str,
    ) -> BackendGenerationSegment | FrontendGenerationSegment | None:
        path = self._generation_segment_cache_path(project_id, target)
        if not path.is_file():
            return None
        model = BackendGenerationSegment if target == "backend" else FrontendGenerationSegment
        try:
            payload = json.loads(path.read_text("utf-8"))
            if payload.get("plan_updated_at") != plan_updated_at:
                return None
            if payload.get("generation_mode") != generation_mode:
                return None
            return model.model_validate(payload["segment"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def _save_cached_generation_segment(
        self,
        project_id: str,
        plan_updated_at: str,
        generation_mode: str,
        target: str,
        segment: BackendGenerationSegment | FrontendGenerationSegment,
    ) -> None:
        self.store._write_text_atomic(
            self._generation_segment_cache_path(project_id, target),
            json.dumps(
                {
                    "plan_updated_at": plan_updated_at,
                    "generation_mode": generation_mode,
                    "segment": segment.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    def _load_cached_generation(
        self,
        project_id: str,
        plan_updated_at: str,
        generation_mode: str = "balanced",
    ) -> GenerationBundle | None:
        path = self._generation_cache_path(project_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text("utf-8"))
            if payload.get("plan_updated_at") != plan_updated_at:
                return None
            if payload.get("generation_mode", "balanced") != generation_mode:
                return None
            return GenerationBundle.model_validate(payload["bundle"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def _save_cached_generation(
        self,
        project_id: str,
        plan_updated_at: str,
        bundle: GenerationBundle,
        generation_mode: str = "balanced",
    ) -> None:
        self.store._write_text_atomic(
            self._generation_cache_path(project_id),
            json.dumps(
                {
                    "plan_updated_at": plan_updated_at,
                    "generation_mode": generation_mode,
                    "bundle": bundle.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    @staticmethod
    def _parse_bundle(text: str) -> GenerationBundle:
        return parse_structured_output(text, GenerationBundle)

    def _write_bundle(self, project_id: str, bundle: GenerationBundle, job_id: str | None = None) -> None:
        self._validate_bundle(project_id, bundle)
        project_root = self.store.project_dir(project_id)
        run_id = job_id or uuid4().hex
        staging = project_root / ".pocket" / "staging" / run_id
        backup = project_root / ".pocket" / "backup" / run_id
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for item in bundle.files:
            target = staging.joinpath(*PurePosixPath(item.path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item.content, encoding="utf-8")
        for required in ("back", "front"):
            (staging / required).mkdir(exist_ok=True)

        backup.mkdir(parents=True, exist_ok=True)
        moved_existing: list[str] = []
        try:
            for area in ("back", "front"):
                current = project_root / area
                if current.exists():
                    shutil.move(str(current), str(backup / area))
                    moved_existing.append(area)
                shutil.move(str(staging / area), str(current))
        except Exception:
            for area in ("back", "front"):
                current = project_root / area
                previous = backup / area
                if current.exists():
                    shutil.rmtree(current)
                if area in moved_existing and previous.exists():
                    shutil.move(str(previous), str(current))
            shutil.rmtree(backup, ignore_errors=True)
            raise
        else:
            shutil.rmtree(backup, ignore_errors=True)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def _validate_bundle(self, project_id: str, bundle: GenerationBundle):
        if len(bundle.files) > self.config.max_generated_files:
            raise ValueError("생성 파일 수 제한을 초과했습니다")
        root = self.store.project_dir(project_id)
        seen: set[str] = set()
        targets = []
        for item in bundle.files:
            rel = PurePosixPath(item.path)
            if rel.is_absolute() or ".." in rel.parts or rel.parts[0] not in {"back", "front"}:
                raise ValueError(f"허용되지 않은 파일 경로: {item.path}")
            if item.path in seen or len(item.content.encode()) > self.config.max_file_size:
                raise ValueError(f"중복되었거나 너무 큰 파일: {item.path}")
            seen.add(item.path)
            target = root.joinpath(*rel.parts).resolve()
            if root not in target.parents:
                raise ValueError(f"프로젝트 밖의 파일 경로: {item.path}")
            targets.append((target, item.content))
        return targets
