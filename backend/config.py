"""全局配置加载模块：读取 config.yaml，提供给其余模块复用。"""
import os
import yaml

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.environ.get("SMARTKUBE_CONFIG", os.path.join(_BASE_DIR, "config.yaml"))


def _load():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


CONFIG = _load()

# 常用项预解析
LLM_CONF = CONFIG.get("llm", {})
FLASK_CONF = CONFIG.get("flask", {})
ADMIN_CONF = CONFIG.get("admin", {})
K8S_CONF = CONFIG.get("kubernetes", {})
SSH_CONF = CONFIG.get("ssh", {})
RES_CONF = CONFIG.get("resources", {})
ARCH_IMAGES = CONFIG.get("arch_images", {})
FEISHU_CONF = CONFIG.get("feishu", {})
PROXY_CONF = CONFIG.get("proxy", {})

NAMESPACE = K8S_CONF.get("namespace", "smart-kube")
KUBECONFIG = os.path.expanduser(K8S_CONF.get("kubeconfig_path", "") or "")
DATA_DIR = os.path.join(_BASE_DIR, "data")
UPLOAD_DIR = os.path.join(_BASE_DIR, "uploads")
FRONTEND_DIR = os.path.join(_BASE_DIR, "frontend")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
