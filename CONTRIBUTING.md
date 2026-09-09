# Contributing · 参与贡献

[简体中文](#简体中文) · [English](#english)

## 简体中文

请先阅读 [AGENTS.md](AGENTS.md) 中的系统架构、代码归属和部署约束。

1. 描述具体问题、复现步骤和预期行为；日志中移除凭据与个人数据。
2. 将修改限制在相关模块；涉及接口或权限时，同步更新调用方与回归测试。
3. 在隔离测试数据库中验证，不连接生产集群执行单元测试。
4. 保持[中文 README](README.md) 与[英文 README](README.en.md) 的能力、限制和安装说明一致。
5. 变更说明应包含行为变化、验证方式，以及迁移或部署是否有额外要求。

```bash
python -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

公开页面使用本地托管的 Three.js。请验证 320px 手机与桌面尺寸、键盘控制、语言切换、减少动态效果偏好和 WebGL 加载失败。更新动图时使用真实页面录制，不混入账户信息或真实集群凭据。

配置、数据库、上传文件、kubeconfig 和私钥不属于提交内容。部署时保留单实例写入约束，并在运行任务结束后重启。

## English

Read [AGENTS.md](AGENTS.md) for architecture, code ownership and deployment constraints before making changes.

1. Describe a concrete problem, reproduction steps and expected behavior. Remove credentials and personal data from logs.
2. Keep changes focused; update consumers and regression coverage when changing interfaces or permissions.
3. Use an isolated test database. Unit tests must not mutate a production cluster.
4. Keep [Chinese](README.md) and [English](README.en.md) capabilities, limitations and setup instructions consistent.
5. Explain the behavior change, verification and any migration or deployment requirements.

Run the commands above. For public-page changes, verify 320px mobile and desktop layouts, keyboard controls, language switching, reduced motion and unavailable WebGL. Record actual UI interactions for documentation animations without exposing accounts or cluster credentials.

Never commit runtime configuration, databases, uploads, kubeconfigs or private keys. Preserve the single-writer constraint and wait for running jobs to finish before restarting.
