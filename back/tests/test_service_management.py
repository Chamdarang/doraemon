from app.core.config import Settings
from app.services.maintenance import MaintenanceService
from app.repositories.store import ProjectStore
from app.schemas import GlobalSettings
from app.services.versioning import VersioningService


def test_clone_copies_source_without_runtime_dependencies(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    source = store.create("Original", "서비스 복제 동작을 검증하는 원본 서비스")
    root = store.project_dir(source.id)
    (root / "front" / "app.tsx").write_text("source", "utf-8")
    (root / "front" / "node_modules").mkdir()
    (root / "front" / "node_modules" / "dependency.js").write_text("large", "utf-8")
    clone = store.clone(source.id, "Cloned")
    clone_root = store.project_dir(clone.id)
    assert (clone_root / "front" / "app.tsx").read_text("utf-8") == "source"
    assert not (clone_root / "front" / "node_modules").exists()


def test_archive_hides_project_from_default_list(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Archive", "서비스 보관 상태를 검증하는 테스트 서비스")
    store.set_archived(project.id, True)
    assert store.list() == []
    assert store.list(include_archived=True)[0].id == project.id


def test_trash_can_be_listed_restored_and_permanently_deleted(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Restorable", "휴지통 복구와 영구 삭제를 검증하는 테스트 서비스")
    store.move_to_trash(project.id)
    item = store.list_trash()[0]
    assert item.project_id == project.id
    restored = store.restore_trash(item.id)
    assert restored.id == project.id
    assert store.get(project.id).name == "Restorable"

    store.move_to_trash(project.id)
    item = store.list_trash()[0]
    store.delete_trash(item.id)
    assert store.list_trash() == []


def test_maintenance_keeps_only_requested_versions(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Cleanup", "오래된 버전 정리를 검증하는 테스트 서비스")
    source = store.project_dir(project.id) / "back" / "main.py"
    versions = VersioningService(store)
    for index in range(3):
        source.write_text(str(index), "utf-8")
        versions.save_version(project.id, f"v{index}", str(index))
    result = MaintenanceService(store).cleanup(project.id, False, False, 1)
    assert result.version_count == 1


def test_global_version_limit_is_applied_when_versions_are_created(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    store.save_global_settings(GlobalSettings(keep_versions=2))
    project = store.create("Version limit", "전역 버전 보관 수 적용 테스트")
    source = store.project_dir(project.id) / "back" / "main.py"
    versions = VersioningService(store)
    for index in range(3):
        source.write_text(str(index), "utf-8")
        versions.save_version(project.id, f"v{index}", str(index))
    assert len(store.list_versions(project.id)) == 2


def test_saved_version_can_be_deleted_without_touching_current_source(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Delete version", "복원 버전만 삭제하는 동작을 검증하는 테스트 서비스")
    source = store.project_dir(project.id) / "back" / "main.py"
    source.write_text("current", "utf-8")
    service = VersioningService(store)
    version = service.save_version(project.id, "snapshot", "job")
    service.delete_version(project.id, version.id)
    assert source.read_text("utf-8") == "current"
    assert store.list_versions(project.id) == []


def test_version_can_restore_previous_files(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Versions", "이전 버전 복원 테스트")
    source = store.project_dir(project.id) / "front" / "app.tsx"
    source.write_text("version one", "utf-8")
    service = VersioningService(store)
    version = service.save_version(project.id, "first", "job")
    source.write_text("version two", "utf-8")
    service.restore_version(project.id, version.id)
    assert source.read_text("utf-8") == "version one"


def test_version_diff_reports_file_and_runtime_changes(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Version diff", "저장 버전과 현재 파일의 차이를 검증합니다")
    root = store.project_dir(project.id)
    backend = root / "back" / "main.py"
    frontend = root / "front" / "app.tsx"
    backend.write_text("print('before')\n", "utf-8")
    frontend.write_text("export const App = () => null\n", "utf-8")
    service = VersioningService(store)
    version = service.save_version(project.id, "before changes", "job")

    backend.write_text("print('after')\nprint('new')\n", "utf-8")
    frontend.unlink()
    added = root / "front" / "new.ts"
    added.write_text("export const value = 1\n", "utf-8")
    ignored = root / "front" / "node_modules" / "ignored.js"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("ignored", "utf-8")
    project.runtime.backend_port += 1
    store.save(project)

    result = service.diff_version(project.id, version.id)
    files = {item.path: item for item in result.files}

    assert (result.added, result.modified, result.deleted) == (1, 1, 1)
    assert result.runtime_changed is True
    assert set(files) == {"back/main.py", "front/app.tsx", "front/new.ts"}
    assert files["back/main.py"].additions == 2
    assert files["back/main.py"].deletions == 1
    assert "node_modules" not in " ".join(files)


def test_runtime_environment_normalizes_mysql_driver_without_changing_saved_value(tmp_path):
    store = ProjectStore(Settings(root=tmp_path))
    project = store.create("Runtime DB URL", "MySQL 드라이버 URL 정규화 테스트")
    store.write_env(project.id, {"DATABASE_URL": "mysql://user:pass@localhost/app"})
    assert store.runtime_env(project.id)["DATABASE_URL"] == "mysql+pymysql://user:pass@localhost/app"
    assert store.read_env(project.id)["DATABASE_URL"] == "mysql://user:pass@localhost/app"
