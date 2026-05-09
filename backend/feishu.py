"""飞书（Lark/Feishu）网页授权（OAuth2.0）封装。

严格按官方文档实现：
1. 引导用户跳转 https://open.feishu.cn/open-apis/authen/v1/index?app_id=&redirect_uri=&state=
   飞书登录后会带上 ?code=&state= 回调到 redirect_uri。
2. 服务端用 app_id + app_secret 取 app_access_token。
   POST https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal
3. 用 app_access_token + code 换 user_access_token。
   POST https://open.feishu.cn/open-apis/authen/v1/oidc/access_token
4. 用 user_access_token 拉用户信息（open_id / union_id / name / email / avatar）。
   GET  https://open.feishu.cn/open-apis/authen/v1/user_info

文档：https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/authentication-management/access-token/
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Tuple
from urllib.parse import urlencode

import requests

from .config import FEISHU_CONF

log = logging.getLogger(__name__)

# 飞书开放平台接口 base
_FEISHU_BASE = "https://open.feishu.cn"
URL_AUTHORIZE          = f"{_FEISHU_BASE}/open-apis/authen/v1/index"
URL_APP_ACCESS_TOKEN   = f"{_FEISHU_BASE}/open-apis/auth/v3/app_access_token/internal"
URL_USER_ACCESS_TOKEN  = f"{_FEISHU_BASE}/open-apis/authen/v1/oidc/access_token"
URL_USER_INFO          = f"{_FEISHU_BASE}/open-apis/authen/v1/user_info"


def is_enabled() -> bool:
    """是否启用了飞书登录（配置缺失/关闭时主路由仍然可用账号密码登录）。"""
    return bool(
        FEISHU_CONF.get("enabled", True)
        and FEISHU_CONF.get("app_id")
        and FEISHU_CONF.get("app_secret")
    )


def _app_id() -> str:
    return FEISHU_CONF.get("app_id", "")


def _app_secret() -> str:
    return FEISHU_CONF.get("app_secret", "")


# ------------------------------------------------------------------
# app_access_token 简单内存缓存（飞书返回 expire 秒，提前 5 分钟过期重取）
# ------------------------------------------------------------------
_token_lock = threading.Lock()
_app_token_cache: dict = {"token": None, "expire_at": 0}


def get_app_access_token() -> str:
    """取 app_access_token（线程安全 + 自动刷新）。"""
    now = int(time.time())
    with _token_lock:
        if _app_token_cache["token"] and _app_token_cache["expire_at"] - 300 > now:
            return _app_token_cache["token"]

        resp = requests.post(
            URL_APP_ACCESS_TOKEN,
            json={"app_id": _app_id(), "app_secret": _app_secret()},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"取 app_access_token 失败：{data}")

        _app_token_cache["token"]     = data["app_access_token"]
        _app_token_cache["expire_at"] = now + int(data.get("expire", 7200))
        return _app_token_cache["token"]


# ------------------------------------------------------------------
# 步骤 1：构造跳转飞书授权页 URL
# ------------------------------------------------------------------
def build_authorize_url(redirect_uri: str, state: str) -> str:
    """生成飞书授权页 URL。
    - redirect_uri 必须与开放平台后台「重定向URL」白名单完全一致（含端口、含协议）
    - state 用于防 CSRF：调用方在 session 里存一份，回调时核对
    """
    params = {
        "app_id": _app_id(),
        "redirect_uri": redirect_uri,
        "state": state,
        # response_type 飞书 v1 接口默认就是 code，可不传；写上更直观
        "response_type": "code",
    }
    return f"{URL_AUTHORIZE}?{urlencode(params)}"


# ------------------------------------------------------------------
# 步骤 2：用授权 code 换 user_access_token
# ------------------------------------------------------------------
def exchange_user_access_token(code: str) -> dict:
    """code -> user_access_token + refresh_token。
    返回原始 data 字段（含 access_token / refresh_token / expires_in / open_id 等）。
    """
    app_token = get_app_access_token()
    resp = requests.post(
        URL_USER_ACCESS_TOKEN,
        headers={
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"grant_type": "authorization_code", "code": code},
        timeout=10,
    )
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"换 user_access_token 失败：{body}")
    return body["data"]


# ------------------------------------------------------------------
# 步骤 3：用 user_access_token 取登录用户信息
# ------------------------------------------------------------------
def fetch_user_info(user_access_token: str) -> dict:
    """返回飞书用户基本信息：name / en_name / avatar_url / open_id / union_id / email / mobile / user_id …"""
    resp = requests.get(
        URL_USER_INFO,
        headers={"Authorization": f"Bearer {user_access_token}"},
        timeout=10,
    )
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"取飞书用户信息失败：{body}")
    return body["data"]
