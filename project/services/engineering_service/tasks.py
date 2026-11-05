"""Bounded local background tasks with durable, factual stage events."""
from copy import deepcopy
import hashlib
import json
import queue
import threading
from types import SimpleNamespace
from uuid import uuid4

from services.retrieval_service.agent.thermal_agent import ThermalAgent
from services.retrieval_service.conversation_memory import ConversationMemory
from .store import RunConflict, now
from .task_contracts import EngineeringTaskRequest
from .task_store import TaskStore, TERMINAL
from .task_workflow import declared_steps, is_liquid_task, run_liquid_workflow
from .reference_workflow import reference_steps, run_reference_workflow
from .result_identity import ResultIdentityError, assert_task_result, task_identity


class TaskQueueFull(RunConflict):
    pass


class TaskCancelled(Exception):
    pass


class TaskContext:
    def __init__(self, service, task):
        self.service, self.task, self.request = service, task, task["request"]

    def save(self):
        self.service.store.save_task(self.task)

    def check_cancel(self):
        if self.service.store.read_task(self.task["task_id"])["cancel_requested"]:
            raise TaskCancelled()

    def transition(self, step_id, status, detail, **data):
        self.check_cancel()
        step = next(s for s in self.task["steps"] if s["step_id"] == step_id)
        if status == "running":
            step.setdefault("started_at", now())
        else:
            step["finished_at"] = now()
        changed = step["status"] != status
        step.update(data, status=status)
        if changed:
            self.task["events"].append({"sequence": len(self.task["events"]) + 1, "step_id": step_id,
                "title": step["title"], "status": status, "at": now(), "detail": detail})
        self.save()

    def add_variables(self, step_id, values, role, source, units):
        for key, value in values.items():
            if value is not None and key != "source":
                self.task["variables"].append({"name": key, "value": deepcopy(value), "unit": units.get(key),
                    "role": role, "source": source.get(key, "explicit_input") if isinstance(source, dict) else source, "step_id": step_id})

    def observe(self, step_id, status, detail, **data):
        self.transition(step_id, status, detail, **data)

    def calculation_observer(self, run, result=None, report=None):
        self.task["run_id"] = run["run_id"]
        self.task["input_fingerprint"] = run["input_fingerprint"]
        if run.get("calculation_fingerprint"):
            self.task["calculation_fingerprint"] = run["calculation_fingerprint"]
        for key in ("calculation", "validation"):
            child = next((s for s in run["steps"] if s["step_id"] == key), {})
            if child.get("status") in {"running", "completed", "failed", "blocked", "incomplete", "skipped"}:
                status = child["status"]
                self.transition(key, status, "已记录实际计算阶段状态。", inputs=run["input_snapshot"],
                    tool_name=run["tool_name"], tool_version=run["tool_version"], run_id=run["run_id"],
                    outputs=(result or {}).get("result") or {} if key == "calculation" else run.get("validation", {}))
        self.task["variables"] = deepcopy(run.get("variables") or [])
        self.task["validation"] = deepcopy(run.get("validation") or {})
        self.save()


class TaskService:
    """One daemon worker and at most eight queued/running jobs per API process.

    Every accepted job holds an OS lease, even while queued. Ordinary synchronous
    Agent calls retain their existing memory; each background task owns an isolated
    in-memory conversation and never mutates the shared Agent's session or solver.
    """
    def __init__(self, run_store, agent, *, capacity=8, autostart=True):
        self.run_store, self.agent = run_store, agent
        self.store = TaskStore(run_store.path)
        self.capacity = threading.BoundedSemaphore(capacity)
        self.queue = queue.Queue(maxsize=capacity)
        self.autostart = autostart
        self._thread = None
        self._thread_lock = threading.Lock()

    def _ensure_worker(self):
        if not self.autostart:
            return
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._worker, name="engineering-tasks", daemon=True)
                self._thread.start()

    def submit(self, request, *, parent_task_id=None, parent_revision=None, continuation=None):
        request = EngineeringTaskRequest.model_validate(request).model_dump(mode="json")
        if not self.capacity.acquire(blocking=False):
            raise TaskQueueFull("Task queue is full; wait for existing tasks to finish")
        lease = None
        try:
            self._ensure_worker()
            if not self.run_store.project_exists(request.get("engineering_project_id") or "local"):
                raise KeyError("Engineering project not found")
            task_id = "task_" + uuid4().hex
            lease = self.store.lock(task_id)
            liquid = is_liquid_task(request)
            reference = request.get("reference_solver") is not None
            steps = reference_steps() if reference else declared_steps(liquid)
            if request.get("design_criteria"):
                index = next(i for i, step in enumerate(steps) if step["step_id"] == "report")
                steps[index]["depends_on"].append("design_review")
                steps.insert(index, {"step_id": "design_review", "title": "检查显式工程设计指标", "depends_on": ["validation"],
                                    "dependency_policy": "after_terminal", "status": "pending", "inputs": {}, "outputs": {},
                                    "tool_name": "explicit_design_limits", "tool_version": "explicit-design-limits-v1"})
            planner_version = "bounded-engineering-v2" if reference or request.get("design_criteria") else "bounded-engineering-v1"
            task = {"schema_version": "1.0", "identity_version": 2, "session_id": request["session_id"], "planner_version": planner_version, "task_id": task_id, "revision": 0, "status": "queued",
                    "request_fingerprint": hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
                    "query": request["query"], "request": request, "created_at": now(), "updated_at": now(),
                    "parent_task_id": parent_task_id, "scope": "bounded_reference_conduction" if reference else "bounded_liquid_cooling" if liquid else "existing_agent",
                    "steps": steps,
                    "events": [], "variables": [], "evidence": [], "result": None, "error": None,
                    "limitations": ["本地有界任务队列；不自动执行外部求解器，不自动恢复中断任务。", "后台任务使用隔离会话，不读取或修改原同步聊天记忆。"]}
            if continuation is not None:
                task["continuation"] = deepcopy(continuation)
                task["parent_revision"] = parent_revision
                task["events"].append({"sequence": 1, "step_id": "context_binding", "title": "绑定同会话工程任务并冻结修改",
                    "status": "completed", "at": now(), "detail": "原任务及结果保留；继承未修改的参数，重新计算并验证本轮设计指标。",
                    "parent_task_id": parent_task_id, "parent_revision": parent_revision, "changes": deepcopy(continuation["changes"])})
            self.store.save_task(task, parent_revision=parent_revision)
            self.queue.put_nowait((task, lease))
            return {**task_identity(task), "query": task["query"], "status": "queued", "revision": task["revision"]}
        except Exception:
            if lease:
                lease.close()
            self.capacity.release()
            raise

    def retry(self, task_id, request, *, continuation=None):
        with self.store.lock(task_id):
            parent = self.store.read_task(task_id)
            allowed = TERMINAL if continuation is not None else TERMINAL - {"completed"}
            if parent["revision"] != request.expected_revision or parent["status"] not in allowed or (continuation is None and parent.get("retried_by")):
                raise RunConflict("Task changed, is active, completed, or already retried")
            if parent.get("planner_version") not in {"bounded-engineering-v1", "bounded-engineering-v2"}:
                raise RunConflict("Task planner version changed; create a new reviewed task")
            payload = deepcopy(parent["request"])
            if request.query is not None:
                payload["query"] = request.query
            if request.liquid_cooling is not None:
                payload["liquid_cooling"] = {**(payload.get("liquid_cooling") or {}), **request.liquid_cooling.model_dump(mode="json", exclude_none=True)}
            if request.design_criteria is not None:
                payload["design_criteria"] = {**(payload.get("design_criteria") or {}), **request.design_criteria.model_dump(mode="json", exclude_none=True)}
            if request.reference_solver is not None:
                payload["reference_solver"] = request.reference_solver.model_dump(mode="json")
            return self.submit(payload, parent_task_id=task_id, parent_revision=request.expected_revision, continuation=continuation)

    def _worker(self):
        while True:
            self.run_next(block=True)

    def run_next(self, *, block=False):
        task, lease = self.queue.get(block=block)
        ctx = TaskContext(self, task)
        try:
            ctx.check_cancel()
            task["status"] = "running"
            ctx.save()
            # No shared memory, configured LLM, shadow classifier or simulation
            # orchestrator can be reached from this local task execution lane.
            def task_retriever(*args):
                try:
                    return self.agent.retriever_func(*args)
                except Exception:
                    # Legacy Agent error metadata contains exception strings.
                    # The task boundary must not persist connection/path details.
                    raise RuntimeError("知识检索暂不可用，未获得来源证据。") from None
            agent = ThermalAgent(cfg=self.agent.cfg, retriever_func=task_retriever,
                memory=ConversationMemory(backend="memory"), enable_llm=False, engineering_store=self.run_store,
                simulation_orchestrator=SimpleNamespace(handle=lambda *_: SimpleNamespace(handled=False, metadata={})))
            if task["scope"] == "bounded_liquid_cooling":
                result = run_liquid_workflow(ctx, agent)
                status = task.pop("outcome", "incomplete")
            elif task["scope"] == "bounded_reference_conduction":
                result = run_reference_workflow(ctx, agent)
                status = task.pop("outcome", "incomplete")
            else:
                options = {**ctx.request, "task_model_assist_shadow": False,
                           "_engineering_task_identity": task_identity(task)}
                options["analysis_report_mode"] = bool(options.get("analysis_report_mode") or "report" in options.get("requested_outputs", []))
                result = agent.answer(ctx.request["query"], ctx.request["session_id"], ctx.request["top_k"], options,
                                      stage_observer=ctx.observe, calculation_observer=ctx.calculation_observer)
                metadata = result["metadata"]
                if (metadata.get("engineering_result_error") or {}).get("code") == "RESULT_IDENTITY_MISMATCH":
                    raise ResultIdentityError("Synchronous task answer rejected its execution identity")
                status = (metadata.get("engineering_run") or {}).get("status", "completed")
                if metadata.get("retrieval_error") or (result["task"].get("needs_retrieval") and not result["sources"]):
                    status = "incomplete" if status == "completed" else status
                if any(s["status"] == "failed" for s in task["steps"]):
                    status = "failed"
                task["evidence"] = result["sources"]
                report = metadata.get("report") or {}
                if report.get("generated") and report.get("content"):
                    task["report"] = {"generated": True, "content_sha256": hashlib.sha256(report["content"].encode()).hexdigest()}
            if status not in TERMINAL:
                status = "incomplete"
            result["metadata"]["engineering_task"] = {**task_identity(task), "query": task["query"], "scope": task["scope"], "status": status}
            if task.get("continuation"):
                result["metadata"]["engineering_task"].update(parent_task_id=task["parent_task_id"], continuation=deepcopy(task["continuation"]))
            ctx.check_cancel()
            task["result"], task["status"] = result, status
            assert_task_result(task)
            task["finished_at"] = now()
            ctx.save()
        except TaskCancelled:
            self._finish_error(ctx, "cancelled", "TASK_CANCELLED", "任务已在步骤边界取消；已完成的中间结果保留。")
        except ResultIdentityError:
            # Quarantine contradictory outputs, including progress projections.
            task["variables"] = [v for v in task["variables"] if v.get("role") != "output"]
            task.pop("report", None)
            task.pop("design_review", None)
            task["validation"] = {"status": "failed", "passed": False}
            for step in task["steps"]:
                if step["step_id"] != "structure_inputs":
                    step["outputs"] = {}
                    step.pop("calculation_result", None)
            self._finish_error(ctx, "failed", "ENGINEERING_RESULT_IDENTITY_MISMATCH",
                               "返回结果与本任务的输入、约束或执行身份不一致，已拒绝显示；请重新提交。")
        except Exception:
            self._finish_error(ctx, "failed", "TASK_EXECUTION_FAILED", "任务执行或持久化未完成；已保存的步骤可查看，未生成的结果不会补造。")
        finally:
            lease.close()
            self.capacity.release()
            self.queue.task_done()

    def _finish_error(self, ctx, status, code, message):
        ctx.task.update(status=status, error={"code": code, "message": message}, result=None, finished_at=now())
        for step in ctx.task["steps"]:
            if step["status"] in {"pending", "running"}:
                step["status"] = status if step["status"] == "running" else "skipped"
                step["finished_at"] = now()
                ctx.task["events"].append({"sequence": len(ctx.task["events"]) + 1, "step_id": step["step_id"],
                    "title": step["title"], "status": step["status"], "at": now(), "detail": message})
        try:
            ctx.save()
        except Exception:
            # A disk failure cannot be hidden by an in-memory success response.
            # The last persisted active snapshot becomes interrupted once its
            # OS lease is released and the store can be read again.
            pass

    def get(self, task_id):
        task = self.store.get_task(task_id)
        assert_task_result(task)
        task.pop("request", None)
        return {**task, **self.store.summary(task)}
