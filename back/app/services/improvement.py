from app.core.config import Settings
from app.schemas import ChatMessageCreate, ImprovementDraft, ImprovementExchange, ImprovementPlan
from app.services.planning import PlanNotApprovedError
from app.repositories.store import ProjectStore
from app.integrations.llm.client import parse_structured
from app.services.generation.context import (
    changed_context_paths,
    load_context_manifest,
    project_snapshot,
    save_context_manifest,
    select_context_paths,
)

IMPROVEMENT_PROMPT = """You are an iterative enhancement partner for an existing software service.
Inspect the supplied current source tree and code, identify meaningful improvements, and refine them
with the user before producing a patch plan. Preserve the existing architecture and every unrelated
file and behavior. Do not propose a full regeneration. Every change path must start with back/ or
front/.

Every reply must advance the improvement discussion. Apply the user's latest answer immediately to
the cumulative goal, analysis, change list, and acceptance criteria. Then ask 1-3 concrete,
high-impact questions about what should be improved next or how the requested improvement should
behave. Questions should be grounded in the current implementation: point out specific UX gaps,
missing states, visual hierarchy, workflows, validation, responsiveness, accessibility, reliability,
or tests that are actually relevant. Include concise options and a recommended default when useful.
Never respond only with acknowledgement or a promise to update later, and never repeat an answered
question.

Questions have a strict materiality threshold. Ask only when different answers would materially
change the user workflow, data contract, architecture, security, destructive behavior, or acceptance
criteria. Do not ask about microcopy, whether to show a label or number, read-only treatment of an
obvious display value, tiny spacing/color choices, or other low-risk presentation details. Choose a
sensible accessible default for those details and record it in the plan without asking. Do not split
one visual choice into a sequence of increasingly smaller questions. Ask at most two questions per
turn.

When the user reports an error, broken screen, failed request, or a state that cannot currently be
verified, restoring a working baseline is the first improvement. Analyze the supplied implementation,
define the likely affected files and a concrete verification criterion, and avoid unrelated design
questions. Never ask how an error state should look while the underlying service is still broken,
unless error-state design is the user's explicit request. If evidence is insufficient, ask only for
the single missing diagnostic fact that cannot be obtained from the supplied source; otherwise make
the repair plan directly.

Keep open_questions cumulative only for material unanswered decisions. Ask questions when their
answers would materially change behavior or implementation; do not invent questions merely to keep
the conversation going. When the change list and acceptance criteria are concrete and there are no
material open questions, set ready_to_apply true immediately. The user must never need to spend an
extra model call saying only "apply" or "proceed". When no material question remains, Doraemon can
apply the concrete change plan with a checkpoint and file-write rollback. The reply is
concise Korean chat copy; detailed analysis and file lists belong in structured fields rather than
being pasted into chat.
"""


class ImprovementService:
    def __init__(self, config: Settings, store: ProjectStore):
        self.config = config
        self.store = store

    async def chat(self, project_id: str, payload: ChatMessageCreate) -> ImprovementExchange:
        project = self.store.get(project_id)
        fingerprint = self.store.request_fingerprint(payload.content, payload.apply_recommendations)
        if payload.request_id:
            cached = self.store.load_idempotent_exchange(
                project_id, "improvement", payload.request_id, fingerprint, ImprovementExchange
            )
            if cached:
                return cached
        if project.status not in {"ready", "error"}:
            raise PlanNotApprovedError("먼저 명세 기반 초기 생성을 완료해주세요")
        if not self.config.llm_configured:
            raise RuntimeError("선택한 LLM 공급자의 API 키 또는 주소가 설정되지 않았습니다")
        user = self.store.add_improvement_message(project_id, "user", payload.content)
        previous = self.store.get_improvement(project_id)
        if previous and previous.applied_at:
            previous = None

        focus_paths = (
            [
                change.path
                for change in previous.draft.changes
                if change.action != "add"
            ]
            if previous
            else []
        )

        root = self.store.project_dir(project_id)
        context_manifest = load_context_manifest(root, "improvement-planning")
        cached_paths = context_manifest.get("selected_paths", [])
        changed_paths = changed_context_paths(root, context_manifest)
        cached_set = set(cached_paths) if isinstance(cached_paths, list) else set()
        previous_paths = [*focus_paths, *(path for path in changed_paths if path in cached_set)]
        selected_paths = select_context_paths(
            root,
            payload.content,
            previous_paths,
            changed_paths,
        )
        snapshot = project_snapshot(
            root,
            limit=project.llm_policy.planning_source_limit,
            per_file_limit=10_000,
            focus_paths=selected_paths,
            focused_only=True,
        )
        save_context_manifest(root, "improvement-planning", selected_paths)

        context = [
            {
                "role": "user",
                "content": (
                    f"Service: {project.name}\n"
                    f"Current source:\n{snapshot}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "The current improvement plan is the cumulative source of truth. "
                    "Older chat messages may have been omitted.\n"
                    f"Current improvement plan: "
                    f"{previous.model_dump_json() if previous else 'none'}"
                ),
            },
        ]

        # The structured plan already contains every unresolved decision. Keep the visible chat
        # locally, but send only this turn. After an applied improvement, even the old plan is reset.
        context.append({"role": "user", "content": user.content})
        response = await parse_structured(
            self.config,
            instructions=IMPROVEMENT_PROMPT,
            input=context,
            text_format=ImprovementDraft,
            project_id=project_id,
            operation="improvement_planning",
        )
        draft = response.output_parsed
        if response.usage:
            self.store.record_usage(project_id, "improvement_planning", self.config.openai_model, response.usage, self.config.llm_provider)
        if not draft:
            raise RuntimeError("LLM이 유효한 개선안을 반환하지 않았습니다")
        if any(not change.path.startswith(("back/", "front/")) for change in draft.changes):
            draft.ready_to_apply = False
            draft.open_questions.append("변경 파일 경로를 back/ 또는 front/ 아래로 확정해야 합니다.")
        # Applicability is deterministic. Approval is a free local API action, not another LLM turn.
        draft.ready_to_apply = bool(
            draft.changes
            and draft.acceptance_criteria
            and not draft.open_questions
        )
        missing = [q for q in draft.open_questions[:3] if q not in draft.reply]
        if missing:
            draft.reply = draft.reply.rstrip() + "\n\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(missing, 1))
        assistant = self.store.add_improvement_message(project_id, "assistant", draft.reply)
        plan = ImprovementPlan(draft=draft)
        self.store.save_improvement(project_id, plan)
        exchange = ImprovementExchange(user_message=user, assistant_message=assistant, plan=plan)
        if payload.request_id:
            self.store.save_idempotent_exchange(project_id, "improvement", payload.request_id, fingerprint, exchange)
        return exchange

    def approve(self, project_id: str) -> ImprovementPlan:
        plan = self.store.get_improvement(project_id)
        if (
            not plan
            or not plan.draft.changes
            or not plan.draft.acceptance_criteria
            or plan.draft.open_questions
        ):
            raise PlanNotApprovedError("아직 적용 가능한 개선안이 없습니다")
        plan.draft.ready_to_apply = True
        if plan.approved:
            return plan
        plan.approved = True
        self.store.save_improvement(project_id, plan)
        return plan
