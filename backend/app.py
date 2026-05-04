"""Flask 主应用。

- 提供 /api/* REST 接口
- 提供 /ws/shell/<pod> WebSocket（Web Shell）
- 提供静态前端页面
"""
from __future__ import annotations

import logging
import os

from flask import Flask, redirect, send_from_directory, session
from flask_cors import CORS
from flask_sock import Sock

from . import auth, db, k8s_client, routes_api, routes_shell
from .config import FLASK_CONF, FRONTEND_DIR


def create_app() -> Flask:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    app = Flask(__name__, static_folder=None)
    app.secret_key = FLASK_CONF.get("secret_key", "smart-kube-secret")
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64MB 上传上限
    CORS(app, supports_credentials=True)

    # 初始化 DB 与默认管理员、ns
    db.init_db()
    auth.ensure_admin()
    try:
        k8s_client.ensure_namespace()
    except Exception as e:
        app.logger.warning("ensure_namespace 失败（启动时可忽略，请检查 kubeconfig）：%s", e)

    # 老 Pod 关联到 owner 的默认实验
    try:
        n = k8s_client.migrate_unlabeled_pods_to(db.ensure_default_experiment)
        if n:
            app.logger.info("已将 %d 个旧 Pod 关联到各自的默认实验", n)
    except Exception as e:
        app.logger.warning("旧 Pod 实验迁移失败（可忽略）：%s", e)

    # 注册 REST 路由
    app.register_blueprint(routes_api.bp)

    # 注册 WebSocket
    sock = Sock(app)
    routes_shell.register(sock)

    # ---- 静态前端 ----
    @app.route("/")
    def index():
        if not session.get("user_id"):
            return redirect("/login.html")
        return redirect("/dashboard.html")

    @app.route("/<path:filename>")
    def serve_static(filename):
        return send_from_directory(FRONTEND_DIR, filename)

    return app


def main():
    app = create_app()
    app.run(
        host=FLASK_CONF.get("host", "0.0.0.0"),
        port=int(FLASK_CONF.get("port", 5000)),
        debug=bool(FLASK_CONF.get("debug", False)),
        threaded=True,
    )


if __name__ == "__main__":
    main()
