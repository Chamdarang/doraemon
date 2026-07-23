import re

from app.core.config import Settings
from app.schemas import ChatMessageCreate, PlanDraft, PlanningExchange, ProjectPlan
from app.repositories.store import ProjectStore
from app.integrations.llm.client import parse_structured

PLANNING_PROMPT = """You are exclusively a specification facilitator for a software project.
Your job is to ask questions, record decisions, resolve ambiguities, and produce one approved-ready
product and implementation specification. You do not write code or create separate artifacts during
this conversation. Never offer to create a UX document, DB draft, API draft, wireframe, checklist,
sample code, or any other deliverable next. Never ask the user to choose which artifact you should
make. Those are parts of the single specification and must be incorporated into it directly.

Every reply must advance the plan now. Never respond only with acknowledgement or future-tense
promises such as "I will organize it", "I will reflect it", "I will finalize it", or "let's decide it".
When the user corrects you, apply the correction to the current structured plan immediately. When the
user delegates a choice, make a concrete choice now with a short rationale instead of asking for
permission to choose later.

Guide the user from a rough service idea to an implementation-ready specification through a concise
conversation. Do not assume a language, framework, database, cloud, or infrastructure. Decide those
with the user only when the requirements justify them. If material information is unresolved, every
reply MUST contain 1-3 numbered, direct questions. Include concise options and a recommended default
when useful. Ask at most three high-impact questions per turn and never repeat answered questions.
Each open_questions item must be a complete, standalone question that the user can answer without
reading the chat reply. Include all choices, the recommended choice, and a short reason in that same
item. Never store a heading, fragment, teaser, or text shortened with "..." or an ellipsis as an open
question. Do not cut a question midway to satisfy the normal reply length guideline.
If the user delegates to your recommendations or defaults, resolve EVERY currently open question
that has a recommendation in the same turn, record a concrete decision for each one, and remove all
of those resolved questions. Do not interpret that delegation as applying to only the first question.
If there are no material questions left, summarize the
finished specification and ask only whether the user wants to revise it or approve it for generation.

The conversation has four explicit stages and must not skip the technical stage:
1. discovery: define users, problem, scope, core flows, data, UI expectations, and constraints;
2. design: complete the product/service specification and resolve product behavior;
3. technical: create a technical specification through user-visible decisions about architecture,
   frontend/backend technologies, persistence, integrations, repository layout, runtime,
   configuration, and tests that actually apply;
4. review: review the combined product and technical specification before generation.
Once the service specification is sufficiently clear, say so briefly and move to technical questions.
Do not silently choose a technical stack merely because it is conventional. Present concise options,
tradeoffs, and one recommendation, then let the user decide. You may make the decision only when the
user explicitly delegates it (for example, "choose for me"), and must record the concrete choice and
rationale. A recommendation is not a confirmed decision. Set stage to technical while any material
technology or project-structure choice remains unconfirmed.

Record the following technical decisions in decisions using these exact category identifiers:
architecture, components, frontend_stack, backend_stack, persistence, repository_layout,
runtime_infrastructure, and testing. For a component that does not apply, record an explicit
"not applicable" choice instead of omitting it. Set a decision's confirmed field to true only after
the user directly selected it or explicitly delegated that choice to your recommendation. Merely
writing a recommendation, implementation_plan, or technical_specification does not confirm it. Do
not ask for final specification approval until all eight technical decisions are confirmed. In
particular, frontend_stack and backend_stack must name the actual language and framework when they
apply (for example React + TypeScript, Spring Boot + Java, Node.js + TypeScript, Go, or FastAPI +
Python); never silently select them inside the side-panel specification.

The service specification must also establish a visual direction appropriate to the product: target
device, information hierarchy, primary navigation, key screen composition, interaction density,
brand mood, and accessibility/responsiveness expectations. Do not make the user choose every color,
font size, radius, or spacing value. Ask only about meaningful visual direction when it is ambiguous,
then choose a coherent professional design system for the detailed values. Unless the user explicitly
requests a prototype or intentionally minimal/raw appearance, the expected result is a polished,
usable application interface rather than unstyled HTML or a developer demo.

Keep decisions as a cumulative list and unresolved material decisions in open_questions. In addition
to product behavior, you MUST define implementation_plan before the plan can be ready. It must cover:
- overall architecture and component boundaries;
- justified technology choices;
- backend/frontend/worker or other components that actually apply;
- intended project directories and the purpose of each;
- data ownership, persistence, and state flow;
- APIs and external integrations;
- local runtime, commands, configuration, environment variables, and infrastructure;
- testing strategy.
The standalone specification must include the agreed visual direction and the UI quality bar for
loading, empty, error, disabled, hover/focus, and responsive states when a browser client applies.
Every project directory path must begin with back/ for server/runtime concerns or front/ for browser
client concerns. Shared code and documentation must be placed under one of those two roots according
to its primary owner. Never propose root-level apps/, packages/, docs/, or tests/ directories.

Set ready_to_generate true only when product scope, users, core flows, UI expectations, data,
integrations, operational constraints, and implementation_plan are all sufficiently clear, and the
user has confirmed or explicitly delegated all material technical choices. When ready,
service_specification must be the standalone product/service source of truth and
technical_specification must be the standalone implementation source of truth. specification must
combine both without losing detail for backward compatibility. The reply is chat UI copy, not the specification: keep it concise but
substantive, normally 80-180 Korean words,
never paste or enumerate the full specification, decisions, project structure, API, tables, or folder
tree in reply. Ask only the remaining questions or briefly state that the side-panel specification was
updated and is ready for review. The reply must be written in the user's language.

The supplied Current plan is authoritative cumulative memory. Preserve every existing confirmed
decision unless the latest user message explicitly changes it. Recent conversation is supplied only
to resolve references such as option numbers and short answers. Before asking anything, compare it
against both Current plan.decisions and the recent conversation. Never ask a semantically equivalent
question that the user has already answered, even if its wording could be improved.
"""


class PlanNotApprovedError(ValueError):
    pass


REQUIRED_TECHNICAL_DECISIONS = {
    "architecture",
    "components",
    "frontend_stack",
    "backend_stack",
    "persistence",
    "repository_layout",
    "runtime_infrastructure",
    "testing",
}


class PlanningService:
    def __init__(self, config: Settings, store: ProjectStore):
        self.config = config
        self.store = store

    async def chat(self, project_id: str, payload: ChatMessageCreate) -> PlanningExchange:
        project = self.store.get(project_id)
        fingerprint = self.store.request_fingerprint(payload.content, payload.apply_recommendations)
        if payload.request_id:
            cached = self.store.load_idempotent_exchange(
                project_id, "planning", payload.request_id, fingerprint, PlanningExchange
            )
            if cached:
                return cached
        if not self.config.llm_configured:
            raise RuntimeError("선택한 LLM 공급자의 API 키 또는 주소가 설정되지 않았습니다")
        user_message = self.store.add_message(project_id, "user", payload.content)
        previous = self.store.get_plan(project_id)
        recent_messages = self.store.list_messages(project_id)[-8:-1]
        recent_context = "\n".join(
            f"{message.role}: {message.content}" for message in recent_messages
        )[-8_000:]
        context = [
            {
                "role": "user",
                "content": (
                    f"Project name: {project.name}\nInitial idea: {project.description}\n"
                    f"Current plan: {previous.model_dump_json() if previous else 'none'}\n"
                    f"Recent conversation for reference resolution only:\n{recent_context or 'none'}"
                ),
            }
        ]
        if payload.apply_recommendations:
            unresolved = "\n".join(
                f"{index}. {question}"
                for index, question in enumerate(
                    previous.draft.open_questions if previous else [], 1
                )
            )
            context.append(
                {
                    "role": "user",
                    "content": (
                        "Structured UI action: apply the recommended/default choice to ALL of the "
                        "currently unresolved questions below in this single turn. Record every "
                        "choice as a confirmed decision and remove every resolved question. Do not "
                        "ask them again.\n"
                        f"{unresolved or 'There are no previously stored open questions.'}"
                    ),
                }
            )
        # ProjectPlan is cumulative, so replaying the full transcript only spends tokens and can
        # reintroduce superseded decisions. The current user answer is interpreted against it.
        context.append({"role": "user", "content": user_message.content})
        response = await parse_structured(
            self.config,
            instructions=PLANNING_PROMPT,
            input=context,
            text_format=PlanDraft,
            project_id=project_id,
            operation="planning",
        )
        draft = response.output_parsed
        if response.usage:
            self.store.record_usage(project_id, "planning", self.config.openai_model, response.usage, self.config.llm_provider)
        if draft is None:
            raise RuntimeError("LLM이 유효한 기획 응답을 반환하지 않았습니다")
        if previous:
            draft = self._merge_cumulative(previous.draft, draft)
        missing_technical = self._missing_technical_decisions(draft)
        if draft.ready_to_generate and (
            draft.implementation_plan is None
            or not draft.service_specification
            or not draft.technical_specification
            or missing_technical
        ):
            draft.ready_to_generate = False
        if missing_technical and (
            draft.stage in {"technical", "review"}
            or draft.implementation_plan is not None
            or draft.technical_specification
        ):
            draft.stage = "technical"
            fallback = (
                "아키텍처와 기술 스택이 아직 확정되지 않았습니다. 전체 구조, 구성요소, "
                "프론트엔드·백엔드 언어와 프레임워크, 저장 방식, 저장소 구조, 실행·인프라, "
                "테스트 전략을 구체적인 선택지와 추천 근거를 보고 정할까요, 아니면 추천안을 "
                "모두 위임할까요?"
            )
            if fallback not in draft.open_questions:
                draft.open_questions.append(fallback)
        if draft.service_specification and draft.technical_specification:
            draft.specification = (
                f"# 서비스 명세\n{draft.service_specification}\n\n"
                f"# 기술 명세\n{draft.technical_specification}"
            )
        draft.reply = self._actionable_reply(draft)
        assistant = self.store.add_message(project_id, "assistant", draft.reply)
        plan = ProjectPlan(draft=draft, approved=False)
        self.store.save_plan(project_id, plan)
        exchange = PlanningExchange(user_message=user_message, assistant_message=assistant, plan=plan)
        if payload.request_id:
            self.store.save_idempotent_exchange(project_id, "planning", payload.request_id, fingerprint, exchange)
        return exchange

    @staticmethod
    def _can_finalize(draft: PlanDraft) -> bool:
        return bool(
            draft.implementation_plan
            and draft.service_specification
            and draft.technical_specification
            and not PlanningService._missing_technical_decisions(draft)
        )

    @staticmethod
    def _missing_technical_decisions(draft: PlanDraft) -> set[str]:
        confirmed = {
            decision.category.strip().lower()
            for decision in draft.decisions
            if decision.confirmed
        }
        return REQUIRED_TECHNICAL_DECISIONS - confirmed

    @staticmethod
    def _finalize(draft: PlanDraft) -> None:
        draft.stage = "review"
        draft.open_questions = []
        draft.ready_to_generate = True
        draft.specification = (
            f"# 서비스 명세\n{draft.service_specification}\n\n"
            f"# 기술 명세\n{draft.technical_specification}"
        )
        draft.reply = (
            "기존 서비스·기술 명세를 변경 없이 최종 확정했습니다. "
            "오른쪽의 ‘명세 승인하고 생성’을 누르면 바로 생성이 시작됩니다."
        )

    @staticmethod
    def _merge_cumulative(previous: PlanDraft, current: PlanDraft) -> PlanDraft:
        """Prevent a later LLM turn from silently forgetting already confirmed plan state."""
        merged = {item.category: item for item in previous.decisions}
        for item in current.decisions:
            earlier = merged.get(item.category)
            if earlier and earlier.confirmed and not item.confirmed:
                continue
            merged[item.category] = item
        current.decisions = list(merged.values())

        stage_order = {"discovery": 0, "design": 1, "technical": 2, "review": 3}
        if stage_order[current.stage] < stage_order[previous.stage]:
            current.stage = previous.stage
        if current.implementation_plan is None:
            current.implementation_plan = previous.implementation_plan
        if not current.service_specification:
            current.service_specification = previous.service_specification
        if not current.technical_specification:
            current.technical_specification = previous.technical_specification
        if not current.specification:
            current.specification = previous.specification
        return current

    @staticmethod
    def _actionable_reply(draft: PlanDraft) -> str:
        if draft.ready_to_generate or not draft.open_questions:
            return draft.reply
        open_questions = draft.open_questions[:3]
        numbered_questions = re.findall(r"(?m)^\s*\d+[.)]\s+\S+", draft.reply)
        visible_count = min(len(numbered_questions), len(open_questions))
        if visible_count == len(open_questions):
            return draft.reply

        indexed_questions = list(enumerate(open_questions, 1))
        if visible_count:
            missing = indexed_questions[visible_count:]
        else:
            missing = [
                (index, question)
                for index, question in indexed_questions
                if question not in draft.reply
            ]
        if not missing:
            return draft.reply
        prefix = draft.reply.strip()
        questions = "\n".join(
            f"{index}. {question}" for index, question in missing
        )
        return f"{prefix}\n\n{questions}" if prefix else questions

    def approve(self, project_id: str) -> ProjectPlan:
        plan = self.store.get_plan(project_id)
        if plan and self._can_finalize(plan.draft):
            self._finalize(plan.draft)
        if (
            not plan
            or not plan.draft.ready_to_generate
            or not plan.draft.specification
            or not plan.draft.implementation_plan
            or not self._can_finalize(plan.draft)
        ):
            raise PlanNotApprovedError("아직 생성 가능한 확정 명세가 없습니다")
        if plan.approved:
            return plan
        plan.approved = True
        self.store.save_plan(project_id, plan)
        return plan
