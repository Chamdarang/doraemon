from app.schemas import ImplementationPlan, PlanDecision, PlanDraft, ProjectPlan, ProjectStructureItem
from app.services.planning import PlanningService


def confirmed_technical_decisions():
    return [
        PlanDecision(category=category, choice="사용자가 확정한 선택", rationale="직접 선택", confirmed=True)
        for category in (
            "architecture",
            "components",
            "frontend_stack",
            "backend_stack",
            "persistence",
            "repository_layout",
            "runtime_infrastructure",
            "testing",
        )
    ]


def test_plan_can_be_approved_when_ready(client):
    client.post("/api/projects", json={
        "name": "Ready", "description": "모든 요구사항이 정해진 테스트 서비스"
    })
    store = client.app.state.container.store
    store.save_plan("ready", ProjectPlan(draft=PlanDraft(
        reply="명세가 준비되었습니다.",
        stage="review",
        decisions=confirmed_technical_decisions(),
        ready_to_generate=True,
        specification="사용자가 승인한 독립 실행형 서비스 명세",
        service_specification="완성된 서비스 명세",
        technical_specification="완성된 기술 명세",
        implementation_plan=ImplementationPlan(
            architecture="단일 로컬 애플리케이션",
            technology_choices=[],
            components=["application"],
            directories=[ProjectStructureItem(path="app/", purpose="애플리케이션 코드")],
            data_and_state="메모리 상태",
            api_and_integrations="외부 연동 없음",
            runtime_and_configuration="로컬 프로세스",
            testing_strategy="단위 테스트",
        ),
    )))
    response = client.post("/api/projects/ready/plan/approve")
    assert response.status_code == 200
    assert response.json()["approved"] is True


def test_plan_without_specification_cannot_be_approved(client):
    client.post("/api/projects", json={
        "name": "Draft", "description": "아직 질문이 남아 있는 테스트 서비스"
    })
    store = client.app.state.container.store
    store.save_plan("draft", ProjectPlan(draft=PlanDraft(
        reply="질문이 있습니다.", stage="discovery", open_questions=["누가 사용하나요?"]
    )))
    assert client.post("/api/projects/draft/plan/approve").status_code == 409


def test_approval_click_is_authoritative_when_all_spec_sections_exist(client):
    client.post("/api/projects", json={
        "name": "Explicit approval", "description": "버튼 승인을 확정 신호로 검증하는 서비스"
    })
    store = client.app.state.container.store
    store.save_plan("explicit-approval", ProjectPlan(draft=PlanDraft(
        reply="질문이 남아 있습니다.",
        stage="technical",
        decisions=confirmed_technical_decisions(),
        open_questions=["다시 확인할까요?"],
        ready_to_generate=False,
        service_specification="완성된 서비스 명세",
        technical_specification="완성된 기술 명세",
        implementation_plan=ImplementationPlan(
            architecture="단일 서비스",
            technology_choices=[],
            components=["application"],
            directories=[ProjectStructureItem(path="back/app", purpose="서비스")],
            data_and_state="로컬 저장",
            api_and_integrations="HTTP API",
            runtime_and_configuration="로컬 실행",
            testing_strategy="빌드 검사",
        ),
    )))
    response = client.post("/api/projects/explicit-approval/plan/approve")
    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is True
    assert body["draft"]["ready_to_generate"] is True
    assert body["draft"]["open_questions"] == []


def test_chat_messages_use_windows_safe_filenames(client):
    client.post("/api/projects", json={
        "name": "Messages", "description": "대화 파일 이름을 검증하는 테스트 서비스"
    })
    store = client.app.state.container.store
    message = store.add_message("messages", "user", "첫 번째 기획 메시지")
    message_files = list((store.project_dir("messages") / ".pocket" / "messages").glob("*.json"))
    assert len(message_files) == 1
    assert message_files[0].name == f"{message.id}.json"
    assert ":" not in message_files[0].name


def test_unresolved_questions_are_always_visible_in_chat(client):
    service = client.app.state.container.planning
    draft = PlanDraft(
        reply="선택사항을 정리하겠습니다.",
        stage="design",
        open_questions=[
            "주 사용 환경은 PC 웹과 모바일 웹 중 어디인가요? (추천: 반응형 웹)",
            "로그인이 필요한가요? (추천: 개인용이면 초기에는 제외)",
        ],
    )
    reply = service._actionable_reply(draft)
    assert "1. 주 사용 환경" in reply
    assert "2. 로그인이" in reply


def test_rephrased_numbered_questions_are_not_appended_twice(client):
    service = client.app.state.container.planning
    draft = PlanDraft(
        reply=(
            "핵심 사용자와 학습 범위를 먼저 정하겠습니다.\n\n"
            "1. 주 타깃은 누구인가요? 추천은 주니어 개발자입니다.\n"
            "2. 사용자가 갖춰야 할 핵심 역량 3가지는 무엇인가요?\n"
            "3. 서비스 형태는 무엇이 적절한가요? 추천은 웹 기반 개인 학습 서비스입니다."
        ),
        stage="discovery",
        open_questions=[
            "주 타깃 사용자와 초기 세그먼트는 누구인가요?",
            "학습 결과로 사용자가 갖춰야 할 핵심 역량 3가지는 무엇인가요?",
            "첫 버전의 서비스 형태는 무엇으로 할까요?",
        ],
    )

    reply = service._actionable_reply(draft)

    assert reply == draft.reply
    assert reply.count("1.") == 1
    assert reply.count("2.") == 1
    assert reply.count("3.") == 1


def test_only_questions_missing_from_numbered_reply_are_appended(client):
    service = client.app.state.container.planning
    draft = PlanDraft(
        reply="우선 한 가지를 확인하겠습니다.\n\n1. 주 사용 환경은 어디인가요?",
        stage="design",
        open_questions=[
            "주 사용 환경은 PC 웹과 모바일 웹 중 어디인가요?",
            "로그인이 필요한가요?",
            "데이터는 어디에 저장할까요?",
        ],
    )

    reply = service._actionable_reply(draft)

    assert reply.count("1.") == 1
    assert "2. 로그인이 필요한가요?" in reply
    assert "3. 데이터는 어디에 저장할까요?" in reply


def test_later_turn_cannot_forget_confirmed_decisions_or_regress_stage():
    previous = PlanDraft(
        reply="기술 선택을 진행합니다.",
        stage="technical",
        decisions=[
            PlanDecision(category="target", choice="모바일 웹", rationale="사용자 선택"),
            PlanDecision(category="login", choice="로그인 없음", rationale="개인용"),
        ],
        service_specification="확정된 서비스 명세",
    )
    current = PlanDraft(
        reply="다음 질문입니다.",
        stage="design",
        decisions=[
            PlanDecision(category="target", choice="반응형 웹", rationale="사용자 변경"),
        ],
    )
    merged = PlanningService._merge_cumulative(previous, current)
    assert merged.stage == "technical"
    assert {item.category: item.choice for item in merged.decisions} == {
        "target": "반응형 웹",
        "login": "로그인 없음",
    }
    assert merged.service_specification == "확정된 서비스 명세"


def test_explicit_approval_finishes_complete_plan_without_more_questions():
    draft = PlanDraft(
        reply="마지막 질문입니다.",
        stage="technical",
        decisions=confirmed_technical_decisions(),
        open_questions=["배포 방식을 다시 선택할까요?"],
        service_specification="완성된 서비스 명세",
        technical_specification="완성된 기술 명세",
        implementation_plan=ImplementationPlan(
            architecture="단일 서비스",
            technology_choices=[],
            components=["application"],
            directories=[ProjectStructureItem(path="back/app", purpose="서비스")],
            data_and_state="로컬 저장",
            api_and_integrations="HTTP API",
            runtime_and_configuration="로컬 실행",
            testing_strategy="빌드와 스모크 테스트",
        ),
    )
    assert PlanningService._can_finalize(draft) is True
    PlanningService._finalize(draft)
    assert draft.ready_to_generate is True
    assert draft.open_questions == []
    assert draft.stage == "review"
    assert draft.specification.startswith("# 서비스 명세")


def test_technical_spec_cannot_be_finalized_without_user_confirmed_stack_and_architecture():
    draft = PlanDraft(
        reply="기술 명세를 임의로 작성했습니다.",
        stage="review",
        decisions=[
            PlanDecision(
                category="backend_stack",
                choice="FastAPI + Python",
                rationale="LLM 추천",
                confirmed=False,
            )
        ],
        service_specification="완성된 서비스 명세",
        technical_specification="사용자 확인 없이 작성된 기술 명세",
        implementation_plan=ImplementationPlan(
            architecture="단일 서비스",
            technology_choices=[],
            components=["application"],
            directories=[ProjectStructureItem(path="back/app", purpose="서비스")],
            data_and_state="로컬 저장",
            api_and_integrations="HTTP API",
            runtime_and_configuration="로컬 실행",
            testing_strategy="빌드 검사",
        ),
    )

    assert PlanningService._can_finalize(draft) is False
    assert "architecture" in PlanningService._missing_technical_decisions(draft)
    assert "backend_stack" in PlanningService._missing_technical_decisions(draft)
