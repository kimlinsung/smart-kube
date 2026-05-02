# Smart-Kube — 自然语言驱动的管理平台

通过 **LangGraph + Kubernetes 原生 API** 让用户用一句话完成 Pod / SSH 容器 / Python 代码执行 / 节点管理等所有操作；自带 Web Shell、文件上传、操作审计；前后端一体，单机即可部署。

```
浏览器  ──HTTP/WS──▶  Flask + Flask-Sock  ──Python K8s SDK──▶  K8s control-plane
                       └─ LangGraph Agent (LLM 工具调用)
```

## 项目结构

```
smart-kube/
├── config.yaml              全局配置（LLM、管理员、kubeconfig、SSH 端口段、资源默认值）
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

编辑 `config.yaml`：

```yaml
llm:
  api_base: "https://api.openai.com/v1"     # 必填：LLM 网关
  api_key: "sk-xxxx"                        # 必填
  model: "gpt-4o-mini"                      # 兼容工具调用的模型

admin:
  username: "admin"
  password: "admin123"

kubernetes:
  kubeconfig_path: "~/.kube/config"
  namespace: "smart-kube"

ssh:
  port_range_start: 30000
  port_range_end: 32000
  default_root_password: "smartkube"
```

> 若 `llm.api_key` 未填写或仍为占位符，系统会自动退化为内置规则解析以保证创建/删除/列表/Python 执行等核心动作仍可使用，但失去多轮对话与复杂指令理解能力。

## 启动

```bash
./run.sh
```

- 首次会自动创建 `.venv` 并安装依赖
- 启动后访问 `http://<本机 IP>:5000`
- 默认登录 `admin / admin123`

或手动方式：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m backend.app
```

## 自然语言示例

进入页面后点击右下角 💬 弹出对话框，可直接说：

| 指令 | Agent 行为 |
|---|---|
| `创建一个riscv架构机器上的Ubuntu SSH可用系统` | 自动选 riscv 架构节点，创建 Pod + NodePort Service，分配 SSH 端口，返回 `ssh -p <port> root@<节点IP>` |
| `批量创建3个Ubuntu SSH容器` | 一次性 ×3 |
| `在hostname为arm202的节点上创建2个arm64容器` | 自动绑定 `nodeName=arm202` |
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
| GET  | `/api/logs` | 操作日志（普通用户仅自己的） |
| GET  | `/api/admin/nodes` | [admin] 节点列表 |
| DELETE | `/api/admin/nodes/<n>` | [admin] 删除节点 |
| GET  | `/api/admin/pods` | [admin] 全量 Pod |
| GET/POST | `/api/admin/users` | [admin] 用户管理 |
| DELETE | `/api/admin/users/<id>` | [admin] 删除用户 |
| WS   | `/ws/shell/<pod>` | Web Shell |

## 常见问题

**Q：sshd 容器跑不起来？**
A：默认启动脚本会在 ubuntu/debian/alpine/centos 系镜像上自动安装 openssh。如果使用了非常精简的镜像（如 distroless / scratch / busybox），请在创建时指定 `image=` 为已经预装 sshd 的镜像。

**Q：riscv 节点没有 ubuntu 镜像？**
A：`config.yaml` 的 `arch_images` 段可改成你节点上能拉到的镜像（私有仓亦可）。

**Q：要把 Web Shell 替换成 xterm.js 完整终端？**
A：把 `shell.html` 的 textarea 替换为 xterm.js 即可，后端 WebSocket 协议无需改动。

**Q：多副本 / 高可用？**
A：本系统设计目标是 **单机一体化运行**，会话保存在内存 + SQLite。若要多副本，把 SQLite 换成 Postgres / Redis 即可，所有 K8s 操作均通过 control-plane API 不依赖本机状态。
