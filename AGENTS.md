# Smart-Kube Architecture and Operations Guide

This file is the project-level operating context for people and coding agents.
Read it before changing deployment, networking, Kubernetes integration, state,
authentication, or scheduling behavior.

## Scope and Safety Rules

- Smart-Kube is a single-instance Flask application with Flask-Sock WebSockets,
  SQLite state, local uploads, a LangGraph workflow, and the Kubernetes Python
  SDK. It is not currently horizontally scalable.
- Treat `config.yaml`, `data/`, `uploads/`, kubeconfigs, WireGuard private keys,
  passwords, tokens, and backup archives as secrets or production state. Never
  commit, print, paste into issues, or replace them with example values.
- The active production instance is on `node104`, not on Tencent Cloud. Do not
  start a second instance against a copied production SQLite database.
- Before changing live networking, inspect the active interface, routes,
  WireGuard peer state, service status, and the actual request path. Do not
  infer reachability from a single successful TCP connection.
- Preserve unrelated worktree changes. This repository commonly contains
  uncommitted feature work in addition to the last commit.

## Runtime Topology

```text
Browser
  |
  | HTTP / WebSocket
  v
Tencent Cloud (public ingress, 10.222.0.1)
  Nginx: cloudedgeiot.top
  proxy_pass http://10.222.0.22:18080
  |
  | existing WireGuard transport (wg4)
  v
node104 / ict-e01-amd64-01
  LAN: 10.156.186.4
  WG ingress: 10.222.0.22
  Smart-Kube: systemd service, 10.222.0.22:18080
  |
  | dedicated wg-smartkube tunnel, 10.223.207.1/30
  | UDP 51821 is NAT-forwarded by 10.128.185.125
  v
arm207 / Kubernetes control-plane
  LAN: 192.168.1.117
  wg-smartkube: 10.223.207.2/30
  kube-apiserver: 10.223.207.2:6443
```

The public web path and the Kubernetes API path are deliberately separate:

1. Tencent Cloud remains only the public reverse proxy.
2. node104 hosts the application and owns the only live SQLite writer.
3. node104 reaches the Kubernetes API over its dedicated encrypted tunnel to
   arm207. It must not depend on Tencent Cloud, arm205, or general access to
   `192.168.1.0/24` for cluster operations.

## Production Hosts and Services

### node104: active application host

- Host: `ict-e01-amd64-01`, LAN address `10.156.186.4`.
- SSH: `ssh -J ubuntu@tencent -p 60092 jinlinsong@10.222.0.22`.
  The default SSH port 22 is not the management endpoint. Use the developer's
  local SSH key through ProxyJump; do not copy private keys to Tencent Cloud.
- Application directory: `/opt/smart-kube`.
- Systemd unit: `smart-kube.service`; source template:
  `deploy/smart-kube.service`.
- Python environment: `/opt/smart-kube/.venv`.
- Application bind address: `10.222.0.22:18080`. Do not change this to
  `0.0.0.0` or the LAN address without an explicit firewall review.
- Root kubeconfig: `/root/.kube/config`.
- Cluster CA used by the kubeconfig: `/root/.kube/cluster-ca.crt`.
- Runtime data: `/opt/smart-kube/data/` and `/opt/smart-kube/uploads/`.
- Configuration: `/opt/smart-kube/config.yaml`, mode `0600`.

Useful checks on node104:

```bash
sudo systemctl status smart-kube.service
sudo journalctl -u smart-kube.service -n 100 --no-pager
sudo ss -ltnp '( sport = :18080 )'
sudo kubectl --kubeconfig=/root/.kube/config get --raw=/readyz
sudo wg show wg-smartkube
```

### Tencent Cloud: ingress only

- Nginx serves `cloudedgeiot.top` and proxies to `10.222.0.22:18080`.
- The relevant configuration is `/etc/nginx/conf.d/mail-routing.conf`.
- Preserve WebSocket settings, `proxy_http_version 1.1`, forwarded headers,
  request-size limit, and proxy timeouts when editing the upstream.
- `smart-kube.service` on Tencent Cloud is intentionally **disabled and
  inactive**. Keep its files and backups for rollback, but never start it while
  node104 is live.

Useful checks on Tencent Cloud:

```bash
sudo nginx -t
sudo systemctl status nginx
curl -fsSI -H 'Host: cloudedgeiot.top' http://127.0.0.1/
curl -fsSI http://10.222.0.22:18080/
```

## WireGuard and Routing Boundaries

### `wg-smartkube`: required API tunnel

- node104 address: `10.223.207.1/30`.
- arm207 address: `10.223.207.2/30`.
- arm207 listens on UDP `51821`.
- Router `10.128.185.125` must retain exactly the required permanent mapping:
  `UDP 51821 -> 192.168.1.117:51821`.
- node104 initiates the connection to `10.128.185.125:51821` with persistent
  keepalive. This makes arm207 reachable despite its NAT.
- Each peer permits only the other tunnel `/32`. Do not add `192.168.1.0/24`,
  `10.156.186.0/24`, or broad `10.0.0.0/8` AllowedIPs to this tunnel.
- The kubeconfig server must be `https://10.223.207.2:6443`, with
  `tls-server-name: kubernetes` and the cluster CA embedded. Do not set
  `insecure-skip-tls-verify: true`.

The direct API test is:

```bash
sudo kubectl --kubeconfig=/root/.kube/config get --raw=/readyz
sudo kubectl --kubeconfig=/root/.kube/config get nodes
```

### Existing `wg4`: public ingress transport

- node104 has `wg4` address `10.222.0.22` and peers with Tencent Cloud.
- Tencent Cloud is `10.222.0.1`.
- This tunnel carries Nginx-to-application traffic. It is not the Kubernetes
  control-plane route.
- Do not repurpose `wg4` to carry `192.168.1.0/24` or modify its broad peer
  AllowedIPs as a quick fix for cluster access.

### Retired or temporary forwarding

- Do not use `10.128.185.125:6443` as the kube-apiserver endpoint. Its TCP
  forwarding was intermittent and caused cluster pages to return HTTP 500.
- The temporary `TCP 60022 -> 192.168.1.117:22` router mapping used to install
  `wg-smartkube` should be removed once maintenance access is no longer needed.
- The old TCP 6443 router forwarding should also be removed. The only required
  permanent mapping for Smart-Kube is UDP 51821.

## Application Configuration and Request Trust

`backend/config.py` reads `config.yaml` at import time. Restart the service
after changing it; changing the file alone does not reload the process.

Relevant production settings, without secret values:

```yaml
flask:
  host: 10.222.0.22
  port: 18080
  trusted_proxy_ips: [10.222.0.1]
kubernetes:
  kubeconfig_path: ~/.kube/config
  namespace: smart-kube
```

`backend/request_meta.py` trusts forwarded client-IP headers only from loopback
or the explicitly configured reverse proxy addresses. Keep the production list
restricted to Tencent Cloud `10.222.0.1`; otherwise direct clients could forge
audit IPs through `X-Forwarded-For`.

## State, Deployment, and Rollback

### Single-writer rule

SQLite does not support two active independently hosted writers. The live
application owns all of these together:

- `data/` including the SQLite database and any WAL files.
- `uploads/`.
- `config.yaml` because it contains the Flask session key and integration
  settings.

For a migration or host replacement:

1. Prepare code, virtual environment, kubeconfig, systemd unit, and networking
   on the target, but leave its application stopped.
2. Back up the source application, data, uploads, configuration, and ingress
   configuration.
3. Stop and disable the old Smart-Kube service.
4. Copy the final data, uploads, and configuration snapshot.
5. Start the target, validate the Kubernetes API and its local HTTP response.
6. Change the Tencent Nginx upstream, run `nginx -t`, then reload Nginx.
7. Verify public HTTP, WebSockets, `/api/cluster/info`, and
   `/api/admin/nodes`.

Do not reverse steps 3 through 6 or both hosts may accept requests and diverge.

### Updating node104

`config.yaml`, `data/`, and `uploads/` are intentionally not Git-tracked.
Code updates must preserve all three. A normal update is:

```bash
cd /opt/smart-kube
# fetch or copy only reviewed code; preserve config.yaml, data/, uploads/
sudo /opt/smart-kube/.venv/bin/pip install -r requirements.txt
sudo systemctl restart smart-kube.service
sudo systemctl status smart-kube.service
```

Before and after an update, verify:

```bash
sudo kubectl --kubeconfig=/root/.kube/config get --raw=/readyz
curl -fsSI http://10.222.0.22:18080/
curl -fsSI http://cloudedgeiot.top/
```

## Code Ownership Map

### Project Lifecycle and Conversation

- `backend/project_lifecycle.py` is the shared deletion service for REST and
  Agent tools. Preserve owner/admin checks; collaborators cannot delete.
- Single and batch deletion remove compute, uploaded inputs, generated files,
  workspace archives and experiment records. Reclaim remains separate and
  retains archives. Do not treat failed Kubernetes cleanup as successful.
- Batch routes: `POST /api/experiments/batch-delete` and
  `POST /api/paper/workspaces/batch-delete`, body `{ "ids": [...] }`, up to 50.
  Inspect every item's `ok` and `error`; HTTP 200 can contain partial failures.
- Queued/running tasks block deletion. Admission of background jobs and project
  deletion share `db.project_lifecycle_lock`; keep the app single-instance.
- `list_projects`, `create_project`, `delete_projects` enforce conversational
  project permissions. Uploaded inputs must belong to the user and be copied
  into the new workspace, never moved or accepted as arbitrary model paths.
- A running conversation cannot delete its own experiment. Switch conversation
  context first or delete from the list after completion. Never silently delete
  active task records or report a queued workspace as completed.
- Public Three.js visualizes the Agent process and scheduling retry, not a
  hardware topology or live task telemetry. Keep the previous public-page theme.
- Browser regression checks: with `playwright` and `pngjs` available, serve
  `frontend/` locally, then run `node tests/browser_ui.cjs`. Set `PREVIEW_URL`
  and `CHROMIUM_PATH` as needed. CRUD requests are mocked to avoid deleting data.
- Python regression suite: `python -m unittest discover -s tests -p 'test_*.py'`.

### Workspace Studio and File Previews

- `backend/paper_suite.py` owns bounded multi-experiment orchestration. The
  document Agent must identify 1-3 experiments with verified source quotations;
  do not silently collapse a missing/invalid experiment array into one run.
- Plan all experiments first. `peak_pool` takes CPU/memory/GPU/count maxima per
  compatible tier/architecture/image slot. Different architectures must not
  share a slot. Never drop a case to satisfy the eight-Unit pool limit.
- Allocate and wait for the whole pool to become Ready before generating code.
  Experiments run sequentially with separate filenames and working directories;
  Units inside one experiment may run concurrently. Persist per-case outputs.
- Any execution failure is fail-fast: reclaim compute immediately, keep files
  and evidence, and explicitly mark remaining cases unexecuted. Cleanup failure
  must remain visible/retryable, never reported as successful reclamation.
- Reports are separate: `report_md` is the process report;
  `comparison_report_md` is the research comparison. Download via `/report`
  with `kind=process|comparison`. Both require the same workspace authorization.
  Missing or non-comparable paper metrics must not become fabricated speedups.
  Model synthesis failure still leaves bounded evidence-based reports.
- `backend/archive_paths.py` only remaps the documented old upload root
  `/home/ubuntu/smart-kube/uploads` to the active upload root. Validate ownership,
  traversal and realpath containment, including symlinks. Never delete outside
  the current upload directory or widen the accepted legacy roots casually.
- Public branding describes the research testbed, not its orchestration backend.
  `frontend/assets/boards/` contains owner-supplied model photographs; provenance
  is in `SOURCES.md`. Do not imply that photographs indicate live availability.
- Additional checks: `tests/test_paper_suite.py` and `node tests/testbed_ui.cjs`.

- `frontend/js/workspace_flow.js` uses the vendored Cytoscape engine for the
  operational canvas. It renders actual events and recorded scheduling
  fallbacks. Replaying the event cursor is read-only; it must never rerun jobs.
- Preserve event history when merging lightweight status updates. The status
  endpoint returns only allowlisted `transition` fields, not arbitrary event
  data or model traces. Five-second recovery polling runs only for the visible
  active workspace; keep expensive code/report reads on demand.
- `workspace_studio.css` is scoped to the paper workbench. Do not apply its
  compact navigation or canvas layout to public pages or unrelated views.
- `backend/file_preview.py` handles bounded content extraction; media is served
  by the authenticated workspace `/files/<id>/preview` endpoint. Both it and
  `/content` retain the same experiment ownership/collaboration checks.
- PDF.js 6.3.289 is vendored under `frontend/vendor/pdfjs/`, including its worker,
  character maps, fonts and licenses. It is loaded only when a PDF is opened.
  Do not send private files to remote Office or PDF preview services.
- Word/PPTX previews are extracted content views, not exact original layouts.
  XLSX uses read-only, cached-value loading; it does not evaluate formulas.
  HTML/SVG/code are displayed as inert source, never active same-origin pages.
- Keep size, archive expansion, row/column, text and PDF canvas-pixel limits.
  Markdown is sanitized and remote images removed. Do not enable document
  scripting, macros, XFA forms, or automatic notebook execution.
- Regression commands: `node tests/browser_ui.cjs` and
  `node tests/workspace_studio.cjs`. An optional `PDF_PREVIEW_PATH` points to a
  synthetic test PDF. Fixtures are mocked and must not mutate live projects.

| Area | Primary files | Notes |
| --- | --- | --- |
| App bootstrap/static pages | `backend/app.py` | Flask app, startup migration hooks, static file and page handling. |
| Configuration | `backend/config.py`, `config.yaml.example` | Never add real credentials to tracked files. |
| Authentication/auditing | `backend/auth.py`, `backend/audit.py`, `backend/request_meta.py` | Preserve ownership checks and proxy trust boundary. |
| Kubernetes access | `backend/k8s_client.py`, `backend/scheduling.py` | All cluster changes go through the Python SDK; retain API timeout/error behavior. |
| REST APIs | `backend/routes_api.py`, `backend/routes_feishu.py` | Maintain role checks on admin and destructive endpoints. |
| Agent/LLM | `backend/agent.py`, `backend/tools.py`, `backend/paper_agents.py` | LLM output is not trusted authorization; tools enforce permissions. |
| Persistent jobs/workspaces | `backend/db.py`, `backend/jobs.py`, `backend/paper_jobs.py` | Schema and lifecycle updates require migration and restart safety review. |
| WebSockets | `backend/routes_shell.py`, `backend/presence.py`, `backend/task_events.py` | Validate both app behavior and Nginx upgrade forwarding. |
| Browser UI | `frontend/`, especially `frontend/js/api.js` | API changes must update UI callers and preserve auth/session behavior. |

## Kubernetes and Scheduling Constraints

- The target namespace is `smart-kube` unless configuration deliberately
  changes it.
- Preserve ownership labels and authorization checks for Pods, Services,
  WebShell, exec, uploads, and deletion. Never accept a Pod name from a normal
  user without validating ownership.
- `node-type`, architecture, GPU, readiness, taints, quotas, image failures,
  CPU, memory, and Pod capacity are scheduling inputs. Review
  `backend/scheduling.py` before changing fallback behavior.
- A user-provided hard constraint must not be silently dropped. Any scheduling
  fallback must be deliberate, visible to the caller, and tested.
- Do not make Pod egress to physical LAN ranges (`10.0.0.0/8`,
  `192.168.0.0/16`) broader as part of an application change. That is a
  network-policy decision with a separate security review.

## Validation Expectations

For code changes, at minimum run focused tests for the touched behavior plus:

```bash
git diff --check
pytest -q
```

For production-impacting changes, additionally verify:

```bash
sudo systemctl is-active smart-kube.service
sudo wg show wg-smartkube
sudo kubectl --kubeconfig=/root/.kube/config get --raw=/readyz
curl -fsSI http://10.222.0.22:18080/
curl -fsSI http://cloudedgeiot.top/
```

If `/api/cluster/info`, `/api/resources`, or `/api/admin/nodes` fails, inspect
`journalctl -u smart-kube.service` first. A Kubernetes API timeout is an
infrastructure failure; do not hide it with an empty successful response.
