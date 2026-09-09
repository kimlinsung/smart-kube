# 部署与使用指南

[返回中文首页](../README.md) · [English overview](../README.en.md)

本文保留安装、配置、接口与运维参考；公开展示见 README，生产架构见 [AGENTS.md](../AGENTS.md)。

通过 **LangGraph + Kubernetes 原生 API** 让用户用一句话完成 Pod / SSH 容器 / Python 代码执行 / 节点管理等所有操作；自带 Web Shell、文件上传、操作审计；前后端一体，单机即可部署。

```
浏览器  ──HTTP/WS──▶  Flask + Flask-Sock  ──Python K8s SDK──▶  K8s control-plane
                       └─ LangGraph Agent (LLM 工具调用)
```

## 项目结构

```
smart-kube/
├── config.yaml              全局配置（含密钥，已 .gitignore，不进 git；每台机器本地维护）
├── config.yaml.example      配置模板（占位符，进 git；`cp config.yaml.example config.yaml` 后填真实值）
├── requirements.txt
├── run.sh                   一键启动脚本（建 venv → 装依赖 → 起服务）
├── backend/
│   ├── app.py               Flask 主入口，注册 REST + WebSocket
│   ├── config.py            读取 config.yaml
│   ├── db.py                SQLite：用户、审计日志、SSH 端口分配、对话历史
│   ├── auth.py              登录 / 会话 / 装饰器（login_required / admin_required）
│   ├── k8s_client.py        K8s 封装：节点、Pod、Service、SSH 端口、exec、文件传输、临时 Python 容器
│   ├── tools.py             LangGraph 工具集（普通用户 + 管理员两套）
│   ├── agent.py             LangGraph 状态图：agent → tools → agent，带历史上下文
│   ├── routes_api.py        REST API（登录/资源/对话/上传/管理员）
│   └── routes_shell.py      WebSocket Web Shell
├── frontend/
│   ├── login.html           登录/注册
│   ├── dashboard.html       我的资源 + 集群概览 + 全局对话弹窗
│   ├── admin.html           管理员：节点/全部 Pod/用户管理
│   ├── logs.html            操作日志
│   ├── shell.html           网页 Web Shell
│   ├── css/style.css
│   └── js/{api,app,chat}.js
├── data/                    SQLite 数据库存放目录（自动创建）
└── uploads/                 用户上传文件目录（自动创建）
```

## 部署前置条件

1. **Python 3.10+**（自带 `venv`）
2. **kubeconfig**：单机能 `kubectl get nodes` 即可
3. **LLM API**：兼容 OpenAI 协议（OpenAI 官方 / vLLM / OneAPI / Azure OpenAI 网关均可）
4. （可选）若计划创建多架构容器，请保证集群节点已 join 进来并打好 `kubernetes.io/arch` label

## 配置

首次准备配置（`config.yaml` 已被 `.gitignore` 忽略，只留本地、不进 git）：

```bash
cp config.yaml.example config.yaml   # 然后填入真实值
```

编辑 `config.yaml`：

```yaml
llm:
  api_base: "https://api.openai.com/v1"     # 必填：LLM 网关
  api_key: "sk-xxxx"                        # 必填
  model: "gpt-4o-mini"                      # 兼容工具调用的模型

admin:
  username: "admin"
  password: "change-me"

kubernetes:
  kubeconfig_path: "~/.kube/config"
  namespace: "smart-kube"

ssh:
  port_range_start: 30000
  port_range_end: 32000
  default_root_password: "change-me"
```

论文 Agent 工作流需要有效的大模型配置。对话中的简单规则路径不能替代论文理解、代码生成与分析。

## 启动

```bash
./run.sh
```

- 首次会自动创建 `.venv` 并安装依赖
- 启动后访问 `http://<本机 IP>:<port>`（端口取 `config.yaml` 的 `flask.port`）
- 默认登录 `admin / <config.yaml 的 admin.password>`

或手动方式：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m backend.app
```

## 部署与更新（git pull 工作流）

设计原则：**代码进 git，配置和数据出 git**。以下三类文件已被 `.gitignore` 忽略且不被跟踪，`git pull` 不会覆盖它们：

| 路径 | 内容 | 说明 |
|---|---|---|
| `config.yaml` | 配置 + 密钥 | 每台机器本地维护；变更时手动复制覆盖 |
| `data/` | SQLite 数据库（用户/实验/聊天/日志） | 运行时自动创建，随机器保留 |
| `uploads/` | 用户上传文件 | 运行时自动创建，随机器保留 |

**日常更新**：开发机 `commit + push`；部署机只需 `git pull`，配置、数据库、上传文件全部原地不动。
配置有变时把新的 `config.yaml` 直接复制/`scp` 覆盖到部署机即可（git 不参与）。

更新前备份代码与 SQLite 数据库。存在运行中后台任务时，先等任务完成再重启；重启会将未完成任务标记为中断。不要用工作区覆盖生产配置。

## 密钥与安全

- **切勿把 `config.yaml` 提交进 git**：它含 LLM key、飞书 `app_secret`、管理员密码、SSH 默认密码。仓库只保留 `config.yaml.example` 模板。
- **切勿在 git remote URL 内嵌 GitHub Token**（如 `https://ghp_xxx@github.com/...`）：该 token 会明文留存于 `.git/config`。请改用 SSH remote 或 git 凭据助手（系统钥匙串等安全凭据助手）。
- 若上述任一密钥曾提交或推送到远端（尤其是公开仓库），请视为已泄露并**立即到对应平台轮换**（GitHub Token、飞书 app_secret、管理员密码、LLM key）。仅从最新代码删除**不能**消除历史中的密钥。

## 自然语言示例

进入页面后点击右下角 💬 弹出对话框，可直接说：

| 指令 | Agent 行为 |
|---|---|
| `创建一个riscv架构机器上的Ubuntu SSH可用系统` | 自动选 riscv 架构节点，创建 Pod + NodePort Service，分配 SSH 端口，返回 `ssh -p <port> root@<节点IP>` |
| `批量创建3个Ubuntu SSH容器` | 一次性 ×3 |
| `在hostname为arm202的节点上创建2个arm64容器` | 使用节点亲和性选择 `arm202`，仍由 Kubernetes 调度器准入 |
| `列出我的资源` | 调 `list_my_resources` |
| `删除 ssh-jin-12345-abcd` | 调 `delete_my_pod` |
| `在arm202节点上执行这份Python代码并返回输出结果` | 先在前端 📎 上传 .py，Agent 拉起一个 `python:3.11-slim` 临时 Pod、cp 进代码、执行、销毁、回传 stdout |
| `查看集群节点`（管理员） | 调 `admin_list_nodes` |
| `删除节点 worker-3`（管理员） | 调 `admin_delete_node` |

对话框右上角 **清空** 按钮可清空多轮记忆，开启新会话。

## 关键能力说明

### 权限隔离

- 所有用户创建的 Pod / Service 都打上 `smartkube/owner=<user_id>` label
- 普通用户接口（`/api/resources`、Web Shell、`delete_pod`、`exec_in_pod`）通过 `assert_pod_owned` 双重校验：DB session + label
- 管理员可调用 `/api/admin/nodes`、`/api/admin/pods`、`/api/admin/users` 与节点删除

### LangGraph Agent

- 状态图：`START → agent → (tools? → agent ↺) → END`
- 通过 SQLite `chat_history` 表注入近 20 轮上下文，实现多轮对话
- 不同角色绑定不同 `bind_tools()` 集，管理员多 3 个工具
- 工具内部通过 thread-local 拿到当前用户，避免越权

### Web Shell

- `flask-sock` 提供 WebSocket，浏览器页面 `shell.html` ↔ 后端 ↔ Pod `exec` 交互流
- 同源 cookie session 鉴权，校验 `assert_pod_owned`
- 输出区直接渲染文本，输入区按行发送命令；支持 ctrl+c / ctrl+d 单字符

### Python 代码执行

1. 用户在对话框 📎 上传 `.py` → 后端落到 `uploads/<uid>/`，session 记录最近文件
2. 用户说"执行这份 Python"
3. Agent 调 `run_uploaded_python` → `k8s_client.run_python_oneshot`：
   - 选节点（可指定 hostname/arch）
   - 创建 `python:3.11-slim` 临时 Pod（restart=Never，sleep 等待）
   - 等 Running → `tar` 流 cp 入 `/tmp/main.py` → `exec python /tmp/main.py`
   - 捕获 stdout/stderr → **删除临时 Pod**
   - 返回结果给前端

### 资源生命周期

- 列表页 15s 自动刷新 phase（Running/Pending/Failed/CrashLoopBackOff…）
- SSH NodePort 端口在 SQLite 内分配/回收，避免碰撞
- 删除 Pod 同时删除其 Service 与端口分配记录
- 论文工作区支持“回收资源”（仅删除 Units，保留输入、生成代码、报告和过程记录）和“删除工作区”（同时删除资源、文件、生成内容、任务记录和关联实验）

### 集群资源预检

- 配置 Agent 同时读取上传正文和实时集群快照；工作区在生成代码前及整批创建前检查可行性。
- 配置字段校验失败时自动修复一次；资源预检失败时携带失败候选和最新快照重新规划，最多三轮。每轮失败原因与候选配置均保留，集群 API 不可用时停止，不以降配绕过错误。
- 论文提供多种实验路径时，可选择有原文依据的可行模拟或子集方案；配置、代码、分析和报告传递实验范围，模拟报告不标记为完整复现或 GPU 实测。用户明确的硬件约束不能静默放宽。
- GPU 以 device-plugin 注册的 `allocatable` 扣除所有命名空间现有 Pod 申请量为准，NVIDIA 标签不能作为可用 GPU 的依据。
- 检查节点 Ready、禁止调度、污点、资源压力、CPU/内存/GPU/Pod 容量、ResourceQuota、LimitRange 和已有镜像拉取故障；批量 Unit 累计占用。
- GPU、架构和指定主机不会静默降级。节点类型可回退，回退必须记录。CUDA 镜像必须有 GPU 申请，通用 CUDA 镜像不能直接当作 Jetson 运行环境。生成的标准库程序统一使用 Python 3.11 运行镜像。
- Pod 通过节点亲和性交给 Kubernetes 调度器，创建时再执行服务端 dry-run 校验。集群快照不是资源预留，并发变化仍以 Kubernetes 最终调度结果为准。
- 镜像检查利用已缓存镜像和已观测故障，不保证未知镜像的架构、驱动或网络兼容性；新出现的拉取与运行错误会返回具体原因。

### 批量删除与模型选择

- 我的资源、实验详情、全部 Units 支持勾选、全选和批量删除。逐项校验所有权；管理员可处理所有用户的资源。部分失败时返回明细并保留失败项选中状态。
- 顶栏、AI 助手和论文工作区创建窗口可选择模型；偏好按用户保存，聊天、工作区所有 Agent 和重新分析任务均使用提交时选定的模型。
- `llm` 保留默认配置，`llm_providers` 配置其他服务的 `api_base`、`api_key` 和 `models`。密钥仅在服务端保存，API 只返回模型名称和配置 ID；配置模板见 `config.yaml.example`。

## API 速查

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/login` | 登录 |
| POST | `/api/logout` | 注销 |
| POST | `/api/register` | 注册普通用户 |
| GET  | `/api/me` | 当前用户 |
| GET  | `/api/resources` | 我的 Pod 列表 |
| DELETE | `/api/resources/<pod>` | 删除我的 Pod |
| GET  | `/api/cluster/info` | 集群概览 |
| POST | `/api/chat` | 与 Agent 对话 |
| GET/DELETE | `/api/chat/history` | 对话历史 |
| POST | `/api/upload` | 上传文件至 server（最近一次给 Agent 用） |
| POST | `/api/upload/to_pod` | 上传文件直送 Pod |
| POST/DELETE | `/api/paper/workspaces/<id>/reclaim` / `/api/paper/workspaces/<id>` | 仅回收工作区计算资源 / 彻底删除工作区 |
| GET  | `/api/logs` | 操作日志（普通用户仅自己的） |
| GET  | `/api/admin/nodes` | [admin] 节点列表 |
| DELETE | `/api/admin/nodes/<n>` | [admin] 删除节点 |
| GET  | `/api/admin/pods` | [admin] 全量 Pod |
| GET/POST | `/api/admin/users` | [admin] 用户管理 |
| DELETE | `/api/admin/users/<id>` | [admin] 删除用户 |
| WS   | `/ws/shell/<pod>` | Web Shell |

## 常见问题

**Q：sshd 容器跑不起来？**
A：当前默认 SSH 初始化面向 Debian/Ubuntu 系工具链，并依赖软件源可达。不要假定 Alpine、CentOS 或其他精简镜像可以直接使用。如果使用了非常精简的镜像（如 distroless / scratch / busybox），请在创建时指定 `image=` 为已经预装 sshd 的镜像。

**Q：riscv 节点没有 ubuntu 镜像？**
A：`config.yaml` 的 `arch_images` 段可改成你节点上能拉到的镜像（私有仓亦可）。

**Q：要把 Web Shell 替换成 xterm.js 完整终端？**
A：把 `shell.html` 的 textarea 替换为 xterm.js 即可，后端 WebSocket 协议无需改动。

**Q：多副本 / 高可用？**
A：当前是单实例 Flask 应用，使用 SQLite、本地文件和进程内后台任务。多副本需要同时改造数据库、共享产物存储、任务队列与 WebSocket 状态协调，不能仅替换数据库后直接扩容。

## 轻量状态接口

`GET /api/paper/workspaces/<id>/status` 返回工作区可变状态与最近事件，不返回完整代码、报告和事件数据。工作区列表只查询摘要，实验列表批量聚合 Pod 数量。集群不可达应按基础设施故障排查。

## 公开页面与依赖

`frontend/welcome.html` 使用本地托管的 Three.js 展示端、边、云概念架构。交互演示不读取真实集群数据，也不创建资源。可通过语言切换、节点点选、视角旋转及七阶段工作流查看介绍。低动态模式暂停场景自动动画，WebGL 不可用时保留内容与工作区入口。
