from app.services.generation.context import (
    changed_context_paths,
    load_context_manifest,
    save_context_manifest,
    select_context_paths,
)


def test_selection_includes_imported_and_importing_neighbors(tmp_path):
    root = tmp_path / "service"
    source = root / "front" / "src"
    components = source / "components"
    components.mkdir(parents=True)
    (source / "App.tsx").write_text("import Card from './components/Card'\nexport default Card", "utf-8")
    (components / "Card.tsx").write_text("export default function Card() { return null }", "utf-8")
    (source / "unrelated.ts").write_text("export const unrelated = true", "utf-8")

    selected = select_context_paths(root, "front/src/App.tsx를 수정해줘")

    assert "front/src/App.tsx" in selected
    assert "front/src/components/Card.tsx" in selected
    assert "front/src/unrelated.ts" not in selected


def test_manifest_detects_only_files_changed_after_snapshot(tmp_path):
    root = tmp_path / "service"
    source = root / "back" / "app"
    source.mkdir(parents=True)
    main = source / "main.py"
    other = source / "other.py"
    main.write_text("from .other import value", "utf-8")
    other.write_text("value = 1", "utf-8")

    save_context_manifest(root, "repair", ["back/app/main.py"])
    manifest = load_context_manifest(root, "repair")
    other.write_text("value = 2", "utf-8")

    assert manifest["selected_paths"] == ["back/app/main.py"]
    assert changed_context_paths(root, manifest) == ["back/app/other.py"]


def test_python_relative_import_adds_dependency(tmp_path):
    root = tmp_path / "service"
    source = root / "back" / "app"
    source.mkdir(parents=True)
    (source / "main.py").write_text("from app.schemas import Item", "utf-8")
    (source / "models.py").write_text("class Item: ...", "utf-8")

    selected = select_context_paths(root, "back/app/main.py 오류 수정")

    assert "back/app/models.py" in selected
