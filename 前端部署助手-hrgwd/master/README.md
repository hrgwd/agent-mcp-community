# AgentX 前端部署 MCP

一个面向 AgentX 工具市场的 stdio MCP 服务，用于从公开 Git 仓库构建并部署静态前端站点。

## 能力

- 支持 GitHub、GitLab、Bitbucket 的公开 HTTPS 仓库。
- 自动识别 npm、pnpm、yarn、bun。
- 只运行 `package.json` 中已声明的构建脚本，不接受任意 Shell 命令。
- 自动识别 `dist`、`build`、`out`，也可显式指定项目内相对目录。
- 每次部署保留独立 release，并更新站点的 `current` 目录。
- `output_directory` 留空时自动识别构建产物目录。

Next.js 服务端渲染项目不能直接作为静态目录部署；请先配置静态导出，使构建结果生成 `out`。

## AgentX 安装命令

```json
{
  "mcpServers": {
    "frontend-deployer": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/hrgwd/AgentXBuilder.git@frontend-deployer-mcp#subdirectory=tools/frontend-deployer-mcp",
        "frontend-deployer-mcp"
      ],
      "env": {
        "FRONTEND_DEPLOY_WORK_ROOT": "/tmp/agentx-frontend-work",
        "FRONTEND_DEPLOY_TARGET_ROOT": "/data/frontend-deployments"
      }
    }
  }
}
```

运行环境需要提供 Python 3.11+、`uvx`、Git，以及目标项目对应的 Node.js 包管理器。

## 工具

### `deploy_frontend_site`

克隆公开仓库、安装依赖、执行构建并发布静态产物。

### `list_frontend_deployments`

列出当前部署的站点、来源仓库、版本和产物路径。

## 本地开发

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests
frontend-deployer-mcp
```
