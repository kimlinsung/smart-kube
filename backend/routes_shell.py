"""Web Shell：通过 Flask-Sock 提供 WebSocket，连入 Pod 的交互 exec 流。

前端通过 ws 收发文本：
- 浏览器 → 后端 → Pod stdin
- Pod stdout/stderr → 后端 → 浏览器
"""
from __future__ import annotations

import logging
import threading

from flask import session

from . import auth, db, k8s_client

log = logging.getLogger(__name__)


def register(sock):
    @sock.route("/ws/shell/<pod_name>")
    def shell(ws, pod_name):
        # 鉴权：依赖 cookie session（同源 ws 自动携带）
        uid = session.get("user_id")
        if not uid:
            ws.send("ERROR: 未登录\n")
            return
        # 重新查 user
        with db.cursor() as cur:
            cur.execute("SELECT id, username, role FROM users WHERE id=?", (uid,))
            row = cur.fetchone()
        if not row:
            ws.send("ERROR: 用户不存在\n")
            return
        user = dict(row)

        try:
            k8s_client.assert_pod_owned(pod_name, user)
        except PermissionError as e:
            ws.send(f"ERROR: {e}\n")
            return
        except Exception as e:
            ws.send(f"ERROR: {e}\n")
            return

        try:
            stream = k8s_client.open_exec_stream(pod_name)
        except Exception as e:
            ws.send(f"ERROR: 无法进入容器 - {e}\n")
            return

        ws.send(f"\r\n=== Smart-Kube Web Shell @ {pod_name} ===\r\n")

        stop = threading.Event()

        def pump_pod_to_ws():
            """从 Pod 拉数据 → 推 WebSocket。"""
            try:
                while not stop.is_set() and stream.is_open():
                    stream.update(timeout=0.5)
                    if stream.peek_stdout():
                        data = stream.read_stdout()
                        if data:
                            ws.send(data)
                    if stream.peek_stderr():
                        data = stream.read_stderr()
                        if data:
                            ws.send(data)
            except Exception as e:
                log.warning("shell pump exit: %s", e)
            finally:
                stop.set()
                try:
                    ws.close()
                except Exception:
                    pass

        t = threading.Thread(target=pump_pod_to_ws, daemon=True)
        t.start()

        # WebSocket 主循环：浏览器输入 → Pod stdin
        try:
            while not stop.is_set():
                msg = ws.receive(timeout=1)
                if msg is None:
                    continue
                if isinstance(msg, bytes):
                    msg = msg.decode("utf-8", "replace")
                stream.write_stdin(msg)
        except Exception as e:
            log.info("shell ws closed: %s", e)
        finally:
            stop.set()
            try: stream.close()
            except Exception: pass
