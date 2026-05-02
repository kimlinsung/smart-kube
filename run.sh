#!/usr/bin/env bash
# Smart-Kube 一键启动脚本：创建/复用 venv，安装依赖，启动 Flask + LangGraph 服务。
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PY=${PY:-python3}
VENV_DIR="$DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "[smart-kube] 创建虚拟环境 $VENV_DIR"
    "$PY" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "[smart-kube] 安装依赖（首次较慢）"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

if [ ! -f "$DIR/config.yaml" ]; then
    echo "[smart-kube] 缺少 config.yaml" >&2
    exit 1
fi

# 校验 kubeconfig
KCFG=$(python -c "from backend.config import KUBECONFIG; print(KUBECONFIG)")
if [ -n "$KCFG" ] && [ ! -f "$KCFG" ]; then
    echo "[smart-kube] 警告：kubeconfig 路径不存在：$KCFG"
    echo "             你可以在 config.yaml 修改 kubernetes.kubeconfig_path"
fi

echo "[smart-kube] 启动服务，浏览器打开 http://<本机IP>:$(python -c 'from backend.config import FLASK_CONF;print(FLASK_CONF.get("port",5000))')"
exec python -m backend.app
