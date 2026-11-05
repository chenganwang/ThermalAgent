"""Same host API authentication as /engineering/runs; no external execution."""
import threading
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from services.physics_service.api import _PhysicsRoute
from .execution import configured_store
from .store import RunConflict
from .task_contracts import EngineeringTaskRequest, TaskContinuationRequest, TaskRevision, TaskRetry
from .tasks import TaskQueueFull, TaskService
from .result_identity import ResultIdentityError

router = APIRouter(prefix="/tasks", route_class=_PhysicsRoute)
_service_lock = threading.Lock()
TaskId = Annotated[str, Path(pattern=r"^task_[a-f0-9]{32}$")]


def get_task_service(request: Request):
    with _service_lock:
        service = getattr(request.app.state, "engineering_tasks", None)
        if service is None:
            agent = getattr(request.app.state, "agent", None)
            if agent is None:
                raise HTTPException(503, detail={"code": "AGENT_NOT_READY", "message": "工程助手尚未就绪。"})
            store = getattr(agent, "engineering_store", None) or configured_store(agent.cfg.paths.project_root)
            if store is None:
                raise HTTPException(503, detail={"code": "ENGINEERING_STORE_UNAVAILABLE", "message": "任务持久化未启用。"})
            service = request.app.state.engineering_tasks = TaskService(store, agent)
        return service


def call(action):
    try:
        return action()
    except ResultIdentityError:
        raise HTTPException(409, detail={"code": "ENGINEERING_RESULT_IDENTITY_MISMATCH", "message": "记录的结果与当前输入或任务身份不一致，已拒绝返回。"}) from None
    except TaskQueueFull:
        raise HTTPException(429, detail={"code": "TASK_QUEUE_FULL", "message": "任务队列已满，请等待现有任务完成。"}) from None
    except KeyError:
        raise HTTPException(404, detail={"code": "ENGINEERING_RECORD_NOT_FOUND", "message": "工程记录不存在。"}) from None
    except RunConflict:
        raise HTTPException(409, detail={"code": "TASK_STATE_CONFLICT", "message": "任务状态已变化，请刷新后操作。"}) from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, detail={"code": "ENGINEERING_TASK_UNAVAILABLE", "message": "任务服务或本地存储暂不可用。"}) from None


@router.post("", status_code=202)
def submit(payload: EngineeringTaskRequest, service=Depends(get_task_service)):
    return call(lambda: service.submit(payload.model_dump(mode="json")))


@router.get("")
def history(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0), service=Depends(get_task_service)):
    return call(lambda: service.store.list_tasks(limit, offset))


@router.post("/continue")
def continue_conversation(payload: TaskContinuationRequest, service=Depends(get_task_service)):
    from .task_continuation import continue_task
    return call(lambda: continue_task(service, payload))


@router.get("/{task_id}")
def detail(task_id: TaskId, service=Depends(get_task_service)):
    return call(lambda: service.get(task_id))


@router.post("/{task_id}/retry", status_code=202)
def retry(task_id: TaskId, payload: TaskRetry, service=Depends(get_task_service)):
    return call(lambda: service.retry(task_id, payload))


@router.post("/{task_id}/cancel")
def cancel(task_id: TaskId, payload: TaskRevision, service=Depends(get_task_service)):
    def action():
        service.store.request_cancel(task_id, payload.expected_revision)
        return service.get(task_id)
    return call(action)
