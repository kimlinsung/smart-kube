"""飞书 OAuth2.0 网页授权登录路由。

对外暴露 3 个接口：
  GET  /api/feishu/enabled  —— 前端用来决定是否显示「飞书登录」按钮
  GET  /api/feishu/login    —— 302 跳转到飞书授权页（state 写入 session 防 CSRF）
  GET  /api/feishu/callback —— 飞书带 ?code=&state= 回调；换 token、拉用户信息、写 session
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlparse, urlunparse

from flask import Blueprint, jsonify, redirect, request, session, url_for

from . import auth, db, feishu
from .config import FEISHU_CONF

log = logging.getLogger(__name__)

bp = Blueprint("feishu", __name__, url_prefix="/api/feishu")


# ------------------------------------------------------------------
# 计算 redirect_uri：
#   - 配置里写死了就用配置（推荐生产环境固定）
#   - 没写则按当前请求的 host 自动拼一个，方便内网多 IP 访问
#     例如开发机访问 http://192.168.1.10:5001/login.html，
#     回调就是  http://192.168.1.10:5001/api/feishu/callback
# ------------------------------------------------------------------
def _build_redirect_uri() -> str:
    cfg = (FEISHU_CONF.get("redirect_uri") or "").strip()
    if cfg:
        return cfg
    # 优先用反向代理转发的 Host / Proto，其次用当前请求的
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host   = request.headers.get("X-Forwarded-Host", request.host)
    return f"{scheme}://{host}/api/feishu/callback"


# ------------------------------------------------------------------
# 给登录页探测：是否启用飞书登录
# ------------------------------------------------------------------
@bp.get("/enabled")
def enabled():
    return jsonify({"enabled": feishu.is_enabled()})


# ------------------------------------------------------------------
# 步骤 1：跳转飞书授权页
#   前端 <a href="/api/feishu/login">飞书登录</a>
#   可带 ?next=/dashboard.html 指定登录后跳哪
# ------------------------------------------------------------------
@bp.get("/login")
def login():
    if not feishu.is_enabled():
        return jsonify({"error": "未启用飞书登录"}), 400

    # 防 CSRF：随机 state，放进 session，回调时核对
    state = secrets.token_urlsafe(24)
    session["feishu_oauth_state"] = state
    # 记下登录前用户想去的页面，回调成功后跳过去
    next_url = request.args.get("next") or "/dashboard.html"
    session["feishu_oauth_next"] = next_url

    redirect_uri = _build_redirect_uri()
    url = feishu.build_authorize_url(redirect_uri, state)
    log.info("跳转飞书授权页：redirect_uri=%s", redirect_uri)
    return redirect(url)


# ------------------------------------------------------------------
# 步骤 2-4：飞书回调 —— 校验 state、换 token、拉用户信息、建会话
# ------------------------------------------------------------------
@bp.get("/callback")
def callback():
    if not feishu.is_enabled():
        return _fail("未启用飞书登录")

    code  = request.args.get("code", "")
    state = request.args.get("state", "")
    err   = request.args.get("error") or request.args.get("error_description")
    if err:
        return _fail(f"飞书返回错误：{err}")
    if not code:
        return _fail("缺少授权 code")

    expected_state = session.pop("feishu_oauth_state", None)
    if not expected_state or state != expected_state:
        return _fail("state 校验失败，可能为伪造请求")

    try:
        token_data = feishu.exchange_user_access_token(code)
        user_access_token = token_data.get("access_token")
        if not user_access_token:
            return _fail(f"飞书未返回 access_token：{token_data}")
        user_info = feishu.fetch_user_info(user_access_token)
    except Exception as e:
        log.exception("飞书 OAuth 失败")
        return _fail(f"飞书授权失败：{e}")

    # 在本地 users 表建立 / 更新对应账号
    user = auth.upsert_feishu_user(user_info)

    # 复用现有 session 机制：set user_id 即视为已登录
    session.clear()
    session["user_id"] = user["id"]
    session["login_via"] = "feishu"
    session["current_experiment_id"] = db.ensure_default_experiment(user["id"])

    db.log_audit(
        user["id"], user["username"], "login_feishu",
        f"open_id={user.get('feishu_open_id','')} name={user.get('name','')}",
    )

    next_url = session.pop("feishu_oauth_next", "/dashboard.html") or "/dashboard.html"
    # 防止 open redirect：只允许同站相对路径
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/dashboard.html"
    return redirect(next_url)


def _fail(msg: str):
    """统一失败处理：跳回登录页并把错误信息带过去。"""
    log.warning("飞书登录失败：%s", msg)
    from urllib.parse import quote
    return redirect(f"/login.html?feishu_err={quote(msg)}")
