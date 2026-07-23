import json
import zipfile

import pytest

from app.core.config import Settings
from app.services.importer import ProjectImportService
from app.repositories.store import ProjectStore


def write_zip(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_imported_pocket_layout_infers_commands_and_environment(tmp_path):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))
    service = ProjectImportService(store)
    archive = tmp_path / "service.zip"
    package = {
        "scripts": {"dev": "vite"},
        "dependencies": {"react": "latest"},
        "devDependencies": {"vite": "latest"},
    }
    write_zip(
        archive,
        {
            "wrapper/back/app/main.py": (
                "import os\nfrom fastapi import FastAPI\n"
                "app = FastAPI()\nTOKEN = os.getenv('API_TOKEN')\n"
            ),
            "wrapper/back/requirements.txt": "fastapi\nuvicorn\n",
            "wrapper/front/package.json": json.dumps(package),
            "wrapper/front/src/App.tsx": "export default function App() { return null }",
            "wrapper/.env": "API_TOKEN=must-not-be-imported\n",
            "wrapper/front/node_modules/ignored.js": "ignored",
        },
    )

    project = service.import_archive(
        "Imported Service",
        "기존 ZIP 프로젝트를 Doraemon으로 가져옵니다",
        archive,
    )
    root = store.project_dir(project.id)

    assert (root / "back" / "app" / "main.py").is_file()
    assert (root / "front" / "src" / "App.tsx").is_file()
    assert not (root / ".env").exists()
    assert not (root / "front" / "node_modules").exists()
    assert project.runtime.backend_command[-2:] == ["--port", "8001"]
    assert project.runtime.frontend_command[-4:] == ["--host", "0.0.0.0", "--port", "5174"]
    assert [item.key for item in project.runtime.environment] == ["API_TOKEN"]
    assert project.status == "ready"


def test_import_rejects_path_traversal_without_creating_project(tmp_path):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))
    service = ProjectImportService(store)
    archive = tmp_path / "unsafe.zip"
    write_zip(archive, {"../outside.py": "bad"})

    with pytest.raises(ValueError, match="안전하지 않은 ZIP"):
        service.import_archive("Unsafe", "안전하지 않은 프로젝트 가져오기 테스트", archive)

    assert store.list() == []
    assert not (tmp_path / "outside.py").exists()


@pytest.mark.parametrize("unsafe_name", ["back/NUL.txt", "front/component.tsx.", "back/trailing "])
def test_import_rejects_windows_aliased_and_reserved_paths(tmp_path, unsafe_name):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))
    service = ProjectImportService(store)
    archive = tmp_path / "unsafe-name.zip"
    write_zip(archive, {unsafe_name: "unsafe", "back/main.py": "print('ok')"})

    with pytest.raises(ValueError):
        service.import_archive("Unsafe name", "Windows 경로 충돌을 방지하는 가져오기 테스트입니다.", archive)

    assert store.list() == []


def test_import_rejects_extreme_compression_ratio_before_extracting(tmp_path):
    store = ProjectStore(Settings(root=tmp_path / "pocket"))
    service = ProjectImportService(store)
    archive = tmp_path / "compression-bomb.zip"
    write_zip(archive, {"back/huge.txt": "0" * 10_000_000})

    with pytest.raises(ValueError, match="압축 비율"):
        service.import_archive("Compressed", "비정상 압축률을 거부하는 가져오기 테스트입니다.", archive)

    assert store.list() == []
