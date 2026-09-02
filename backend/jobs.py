"""Background chat and uploaded-script execution jobs."""
from __future__ import annotations

import os
import json
import threading
import time

from . import agent, audit, db, k8s_client, task_events


def _clip(value, limit=100_000):
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "\n\n[输出已截断]"


def _update(task_id, *, event_type=None, event_content=None, **changes):
    task = db.update_execution_task(task_id, **changes)
    if event_type:
        db.add_task_event(task_id, event_type, event_content or changes.get("detail", ""))
        task = db.get_execution_task(task_id)
    task_events.publish_task(task_id)
    return task


def _run_in_thread(app, target, *args):
    def wrapped():
        with app.app_context():
            target(*args)

    thread = threading.Thread(target=wrapped, daemon=True)
    thread.start()


def start_chat_task(app, user, message, uploaded_file, experiment_id, source_ip):
    task = db.create_execution_task(
        user["id"],
        experiment_id,
        "chat",
        message[:80],
        "等待 AI 助手处理",
        {"message": message},
    )
    task_events.publish_task(task["id"])
    _run_in_thread(
        app,
        _execute_chat,
        task["id"],
        user,
        message,
        uploaded_file,
        experiment_id,
        source_ip,
    )
    return task


def _execute_chat(task_id, user, message, uploaded_file, experiment_id, source_ip):
    now = int(time.time())
    _update(
        task_id,
        status="running",
        progress=10,
        detail="AI 正在分析请求",
        started_at=now,
        event_type="started",
        event_content="AI 正在分析请求",
    )
    output = []
    last_flush = 0.0

    def tool_progress(detail, progress=None):
        _update(
            task_id,
            progress=progress if progress is not None else 55,
            detail=detail,
            event_type="progress",
            event_content=detail,
        )

    try:
        for event in agent.chat_stream(
            user,
            message,
            uploaded_file=uploaded_file,
            experiment_id=experiment_id,
            source_ip=source_ip,
            progress_callback=tool_progress,
        ):
            if event.get("error"):
                raise RuntimeError(event["error"])
            if event.get("status"):
                tool_progress(event["status"], 45)
            delta = event.get("delta")
            if not delta:
                continue
            output.append(delta)
            monotonic = time.monotonic()
            if monotonic - last_flush >= .25:
                _update(
                    task_id,
                    progress=80,
                    detail="正在生成回复",
                    result=_clip("".join(output)),
                )
                last_flush = monotonic

        result = _clip("".join(output))
        _update(
            task_id,
            status="succeeded",
            progress=100,
            detail="处理完成",
            result=result,
            finished_at=int(time.time()),
            event_type="succeeded",
            event_content="处理完成",
        )
    except Exception as exc:
        message = _clip(exc, 4000)
        _update(
            task_id,
            status="failed",
            detail="处理失败",
            error=message,
            finished_at=int(time.time()),
            event_type="failed",
            event_content=message,
        )


def start_script_task(app, user, script_file, experiment_id, options, source_ip):
    target = options.get("hostname") or options.get("arch") or "自动选择节点"
    task = db.create_execution_task(
        user["id"],
        experiment_id,
        "script",
        f"运行 {script_file['original_name']}",
        f"目标：{target}",
        {
            "file_id": script_file["id"],
            "filename": script_file["original_name"],
            "arch": options.get("arch"),
            "hostname": options.get("hostname"),
            "timeout": options.get("timeout"),
        },
    )
    task_events.publish_task(task["id"])
    _run_in_thread(
        app,
        _execute_script,
        task["id"],
        user,
        script_file,
        experiment_id,
        options,
        source_ip,
    )
    return task


def _execute_script(task_id, user, script_file, experiment_id, options, source_ip):
    _update(
        task_id,
        status="running",
        progress=5,
        detail="正在准备执行环境",
        started_at=int(time.time()),
        event_type="started",
        event_content="正在准备执行环境",
    )
    try:
        if not os.path.isfile(script_file["stored_path"]):
            raise FileNotFoundError("上传文件已不存在，请重新上传")

        def progress(detail, value):
            _update(
                task_id,
                progress=value,
                detail=detail,
                event_type="progress",
                event_content=detail,
            )

        result = k8s_client.run_python_oneshot(
            user,
            script_file["stored_path"],
            hostname=options.get("hostname"),
            arch=options.get("arch"),
            timeout=options.get("timeout", 120),
            experiment_id=experiment_id,
            progress_callback=progress,
        )
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        text = (
            f"执行完成\n\n节点：`{result.get('node')}`  \n"
            f"临时 Pod：`{result.get('pod_name')}`\n\n"
            f"```text\n{stdout or '（无标准输出）'}\n```"
        )
        if stderr:
            text += f"\n\n标准错误：\n```text\n{stderr}\n```"
        audit.log(
            user["id"],
            user["username"],
            "run_python",
            json.dumps(
                {
                    "node": result.get("node"),
                    "pod": result.get("pod_name"),
                    "file": script_file["original_name"],
                },
                ensure_ascii=False,
            ),
            source_ip=source_ip,
        )
        _update(
            task_id,
            status="succeeded",
            progress=100,
            detail="脚本执行完成",
            result=_clip(text),
            finished_at=int(time.time()),
            event_type="succeeded",
            event_content="脚本执行完成",
        )
    except Exception as exc:
        message = _clip(exc, 4000)
        _update(
            task_id,
            status="failed",
            detail="脚本执行失败",
            error=message,
            finished_at=int(time.time()),
            event_type="failed",
            event_content=message,
        )
