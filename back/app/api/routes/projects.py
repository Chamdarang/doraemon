import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import projects
from app.schemas import (
    CloneRequest,
    ProjectCreate,
    ProjectManifest,
    ProjectOverview,
    ProjectUpdate,
    ProjectWorkspace,
    SearchResult,
    TrashItem,
)
from app.services.errors import ApplicationConflictError, ResourceNotFoundError
from app.services.projects import ProjectService

router = APIRouter()


def _raise_project_error(exc: Exception) -> None:
    status_code = 404 if isinstance(exc, ResourceNotFoundError) else 409
    raise HTTPException(status_code, str(exc)) from exc


@router.get("/search", response_model=list[SearchResult])
def search_projects_and_jobs(
    q: str, limit: int = 30, service: ProjectService = Depends(projects)
):
    return service.search(q, limit)


@router.get("/projects", response_model=list[ProjectManifest])
def list_projects(archived: bool = False, service: ProjectService = Depends(projects)):
    return service.list(archived)


@router.get("/projects/overviews", response_model=list[ProjectOverview])
async def list_project_overviews(
    archived: bool = False, service: ProjectService = Depends(projects)
):
    return await service.overviews(archived)


@router.post("/projects", response_model=ProjectManifest, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, service: ProjectService = Depends(projects)):
    return service.create(payload)


@router.post(
    "/projects/import", response_model=ProjectManifest, status_code=status.HTTP_201_CREATED
)
async def import_project(
    name: str = Form(min_length=1, max_length=80),
    description: str = Form(min_length=10, max_length=10_000),
    file: UploadFile = File(),
    service: ProjectService = Depends(projects),
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(422, "ZIP 파일만 가져올 수 있습니다")
    archive_path = service.new_import_path()
    size = 0
    try:
        with archive_path.open("wb") as output:
            while chunk := await file.read(1_048_576):
                size += len(chunk)
                if size > 100_000_000:
                    raise HTTPException(413, "ZIP 파일은 100MB까지 업로드할 수 있습니다")
                output.write(chunk)
        return service.import_archive(name, description, archive_path)
    except HTTPException:
        raise
    except (ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise HTTPException(422, str(exc) or "ZIP을 가져오지 못했습니다") from exc
    finally:
        await file.close()
        archive_path.unlink(missing_ok=True)


@router.get("/projects/{project_id}", response_model=ProjectManifest)
def get_project(project_id: str, service: ProjectService = Depends(projects)):
    try:
        return service.get(project_id)
    except ResourceNotFoundError as exc:
        _raise_project_error(exc)


@router.get("/projects/{project_id}/overview", response_model=ProjectOverview)
async def get_project_overview(
    project_id: str, probe: bool = True, service: ProjectService = Depends(projects)
):
    try:
        return await service.overview(project_id, probe)
    except ResourceNotFoundError as exc:
        _raise_project_error(exc)


@router.get("/projects/{project_id}/workspace", response_model=ProjectWorkspace)
async def get_project_workspace(
    project_id: str, service: ProjectService = Depends(projects)
):
    try:
        return await service.workspace(project_id)
    except ResourceNotFoundError as exc:
        _raise_project_error(exc)


@router.post(
    "/projects/{project_id}/clone",
    response_model=ProjectManifest,
    status_code=status.HTTP_201_CREATED,
)
def clone_project(
    project_id: str, payload: CloneRequest, service: ProjectService = Depends(projects)
):
    try:
        return service.clone(project_id, payload)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_project_error(exc)


@router.post("/projects/{project_id}/archive", response_model=ProjectManifest)
def archive_project(project_id: str, service: ProjectService = Depends(projects)):
    try:
        return service.archive(project_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_project_error(exc)


@router.post("/projects/{project_id}/unarchive", response_model=ProjectManifest)
def unarchive_project(project_id: str, service: ProjectService = Depends(projects)):
    try:
        return service.unarchive(project_id)
    except ResourceNotFoundError as exc:
        _raise_project_error(exc)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def trash_project(project_id: str, service: ProjectService = Depends(projects)):
    try:
        service.trash(project_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_project_error(exc)


@router.get("/trash", response_model=list[TrashItem])
def list_trash(service: ProjectService = Depends(projects)):
    return service.list_trash()


@router.post("/trash/{trash_id}/restore", response_model=ProjectManifest)
def restore_trash(trash_id: str, service: ProjectService = Depends(projects)):
    try:
        return service.restore_trash(trash_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_project_error(exc)


@router.delete("/trash/{trash_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trash(trash_id: str, service: ProjectService = Depends(projects)):
    try:
        service.delete_trash(trash_id)
    except ResourceNotFoundError as exc:
        _raise_project_error(exc)


@router.post("/projects/{project_id}/open-folder", status_code=status.HTTP_204_NO_CONTENT)
def open_project_folder(project_id: str, service: ProjectService = Depends(projects)):
    try:
        service.open_folder(project_id)
    except (ResourceNotFoundError, ApplicationConflictError) as exc:
        _raise_project_error(exc)


@router.patch("/projects/{project_id}", response_model=ProjectManifest)
def update_project(
    project_id: str, payload: ProjectUpdate, service: ProjectService = Depends(projects)
):
    try:
        return service.update(project_id, payload)
    except ResourceNotFoundError as exc:
        _raise_project_error(exc)
