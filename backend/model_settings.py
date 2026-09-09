"""Server-owned model profiles and isolated per-task model context."""
from contextvars import ContextVar
from functools import wraps
from inspect import signature

from .config import LLM_CONF, LLM_PROVIDERS

_active = ContextVar("model_profile", default="default")


def profiles():
    result = {"default": dict(LLM_CONF)}
    for provider, config in LLM_PROVIDERS.items():
        for model in config.get("models", []):
            base = LLM_CONF if config.get("inherit_default") else {}
            result[f"{provider}:{model}"] = {**base, **config, "model": model}
    return result


def resolve(profile_id):
    profile_id = profile_id or "default"
    if not isinstance(profile_id, str) or profile_id not in profiles():
        raise ValueError("所选模型不存在或未配置")
    return profile_id


def config_for(user=None):
    profile_id = resolve(user.get("llm_profile") if user is not None else _active.get())
    return profiles()[profile_id]


def public_profiles():
    return [{"id": key, "model": config.get("model", "未配置"),
             "label": config.get("model", "未配置"),
             "available": bool(config.get("api_key"))}
            for key, config in profiles().items()]


def task_model(function):
    parameters = signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        user = parameters.bind(*args, **kwargs).arguments["user"]
        token = _active.set(resolve(user.get("llm_profile")))
        try:
            return function(*args, **kwargs)
        finally:
            _active.reset(token)
    return wrapped
