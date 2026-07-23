"use client";

import { useState } from "react";
import { EnvironmentView } from "./features/environment-view";
import { ImprovementView } from "./features/improvement-view";
import { PlanningView } from "./features/planning-view";
import { RepairView } from "./features/repair-view";
import { RuntimeView } from "./features/runtime-view";
import { SettingsView } from "./features/settings-view";
import { CreateServiceDialog, ImportServiceDialog, TrashDialog } from "./features/studio-dialogs";
import { StudioHeader, StudioSidebar } from "./features/studio-shell";
import { EmptyState } from "./features/studio-shared";
import { ToolsView } from "./features/tools-view";
import { useImprovementActions } from "./hooks/use-improvement-actions";
import { useLlmActivity } from "./hooks/use-llm-activity";
import { usePlanningActions } from "./hooks/use-planning-actions";
import { useProjectActions } from "./hooks/use-project-actions";
import { useProjectWorkspace } from "./hooks/use-project-workspace";
import { useRuntimeActions } from "./hooks/use-runtime-actions";
import type { StudioTab, TrashItem } from "./studio-types";

export function DoraemonStudio() {
  const [error, setError] = useState("");
  const workspace = useProjectWorkspace(setError);
  const [tab, setTab] = useState<StudioTab>("plan");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);
  const [trashItems, setTrashItems] = useState<TrashItem[]>([]);
  const [repairDraft, setRepairDraft] = useState("");
  const { activity: llmActivity, connection } = useLlmActivity();
  const llmBusy = thinking || llmActivity.busy;

  const planning = usePlanningActions({
    selectedId: workspace.selectedId, setMessages: workspace.setMessages, setPlan: workspace.setPlan,
    setThinking, setError, setTab, refreshProject: workspace.refreshProject, refreshProjects: workspace.refreshProjects,
  });
  const improvement = useImprovementActions({
    selectedId: workspace.selectedId, setMessages: workspace.setImprovementMessages,
    setPlan: workspace.setImprovementPlan, setThinking, setError, refreshProject: workspace.refreshProject,
  });
  const runtime = useRuntimeActions({
    selectedId: workspace.selectedId, setProjects: workspace.setProjects, setProcesses: workspace.setProcesses,
    setVersions: workspace.setVersions, setThinking, setError, setRepairDraft, setTab,
    refreshProject: workspace.refreshProject, refreshProjects: workspace.refreshProjects,
  });
  const projects = useProjectActions({
    selected: workspace.selected, selectedId: workspace.selectedId, setProjects: workspace.setProjects,
    setSelectedId: workspace.setSelectedId, setNotifications: workspace.setNotifications, setTrashItems,
    setNewOpen, setTrashOpen, setTab, setError, refreshProjects: workspace.refreshProjects,
  });

  return (
    <main className="studio-shell">
      <StudioSidebar
        projects={workspace.projects} selectedId={workspace.selectedId} settingsOpen={settingsOpen}
        loading={workspace.loading} connection={connection} activity={llmActivity} overviews={workspace.overviewById}
        onSelect={(id, target) => { workspace.setSelectedId(id); setSettingsOpen(false); if (target) setTab(target); }}
        onCreate={() => setNewOpen(true)} onImport={() => setImportOpen(true)} onSettings={() => setSettingsOpen(true)}
        onTrash={() => void projects.openTrash()}
      />

      <section className="workspace">
        {settingsOpen ? <SettingsView onError={setError} /> : workspace.selected ? (
          <>
            <StudioHeader
              key={workspace.selected.id}
              project={workspace.selected} notifications={workspace.notifications} busyAction={projects.busyAction}
              onRead={() => void projects.markNotificationsRead()} onFolder={() => void projects.openFolder()}
              onRename={() => void projects.renameProject()} onClone={() => void projects.cloneProject()}
              onTrash={() => void projects.trashProject()} onRefresh={() => void workspace.refreshProject(workspace.selected!.id)}
            />
            <div className="tabs" role="tablist">
              <button role="tab" aria-selected={tab === "plan"} className={tab === "plan" ? "active" : ""} onClick={() => setTab("plan")}>기획</button>
              <button role="tab" aria-selected={tab === "improve"} className={tab === "improve" ? "active" : ""} onClick={() => setTab("improve")}>개선</button>
              <button role="tab" aria-selected={tab === "repair"} className={tab === "repair" ? "active" : ""} onClick={() => setTab("repair")}>오류 수정</button>
              <button role="tab" aria-selected={tab === "runtime"} className={tab === "runtime" ? "active" : ""} onClick={() => setTab("runtime")}>실행</button>
              <button role="tab" aria-selected={tab === "environment"} className={tab === "environment" ? "active" : ""} onClick={() => setTab("environment")}>환경변수</button>
              <button role="tab" aria-selected={tab === "tools"} className={tab === "tools" ? "active" : ""} onClick={() => setTab("tools")}>도구</button>
            </div>
            {error && <div className="error-banner" role="alert"><span>!</span>{error}<button aria-label="오류 메시지 닫기" onClick={() => setError("")}>×</button></div>}
            {tab === "plan" && <PlanningView messages={workspace.messages} plan={workspace.plan} thinking={llmBusy} jobs={workspace.jobs} onSend={planning.sendMessage} onGenerate={planning.approveAndGenerate} onOpenRepair={() => setTab("repair")} onSaveSpecification={planning.saveSpecification} />}
            {tab === "improve" && <ImprovementView messages={workspace.improvementMessages} plan={workspace.improvementPlan} thinking={llmBusy} jobs={workspace.jobs} onSend={improvement.sendImprovement} onApply={improvement.applyImprovement} />}
            {tab === "repair" && <RepairView key={repairDraft || "manual-repair"} initialText={repairDraft} messages={workspace.repairMessages} jobs={workspace.jobs} busy={llmBusy} onRepair={runtime.startRepair} onCancel={runtime.cancelJob} />}
            {tab === "runtime" && <RuntimeView key={workspace.selected.id} projectId={workspace.selected.id} states={workspace.processes} jobs={workspace.jobs} usage={workspace.usage} versions={workspace.versions} overview={workspace.selectedOverview} costMode={workspace.selected.llm_policy.mode} busyAction={runtime.busyAction} onStates={workspace.setProcesses} onToggle={runtime.toggleProcess} onToggleAll={runtime.toggleAll} onPorts={runtime.savePorts} onCancel={runtime.cancelJob} onResume={runtime.resumeJob} onClearCache={runtime.clearCache} onRestore={runtime.restoreVersion} onDeleteVersion={runtime.deleteVersion} onCostMode={runtime.setCostMode} onOpenRepair={runtime.openRepairFromRuntime} />}
            {tab === "environment" && <EnvironmentView projectId={workspace.selected.id} onError={setError} />}
            {tab === "tools" && <ToolsView projectId={workspace.selected.id} onError={setError} />}
          </>
        ) : <EmptyState loading={workspace.loading} onCreate={() => setNewOpen(true)} />}
      </section>
      {newOpen && <CreateServiceDialog onClose={() => setNewOpen(false)} onCreate={projects.createProject} />}
      {importOpen && <ImportServiceDialog onClose={() => setImportOpen(false)} onImport={projects.importProject} />}
      {trashOpen && <TrashDialog items={trashItems} busyAction={projects.busyAction} onClose={() => setTrashOpen(false)} onRestore={(item) => void projects.restoreTrash(item)} onDelete={(item) => void projects.deleteTrash(item)} />}
    </main>
  );
}
