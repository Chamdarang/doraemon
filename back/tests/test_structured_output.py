import pytest

from app.services.generation.service import GenerationService
from app.integrations.llm.providers.common import parse_json
from app.schemas import GenerationBundle, ImprovementBundle
from app.integrations.llm.structured import parse_structured_output


def test_provider_and_generation_entrypoints_share_the_same_normalizer():
    raw = """```json
    {"summary":"updated","files":{"front/App.tsx":{"content":"export {}"}},
     "deleted_files":"back/old.py","runtime":"not run"}
    ```"""

    direct = parse_structured_output(raw, ImprovementBundle)
    provider = parse_json(raw, ImprovementBundle, "fixture")
    artifact = GenerationService._parse_improvement_bundle(raw)

    assert direct == provider == artifact
    assert direct.files[0].content == "export {}"
    assert direct.deleted_files == ["back/old.py"]
    assert direct.runtime is None


def test_generation_bundle_accepts_files_object_but_requires_real_runtime():
    valid = (
        '{"summary":"generated","files":{"back/main.py":"print(1)"},'
        '"runtime":{"backend_port":8101,"frontend_port":5101}}'
    )
    bundle = GenerationService._parse_bundle(valid)
    assert isinstance(bundle, GenerationBundle)
    assert bundle.files[0].path == "back/main.py"

    with pytest.raises(ValueError):
        GenerationService._parse_bundle(
            '{"summary":"generated","files":{"back/main.py":"print(1)"},"runtime":"not run"}'
        )


def test_malformed_json_is_rejected_instead_of_guessed():
    with pytest.raises(ValueError):
        parse_structured_output('{"summary":"broken" "files":[]}', ImprovementBundle)
