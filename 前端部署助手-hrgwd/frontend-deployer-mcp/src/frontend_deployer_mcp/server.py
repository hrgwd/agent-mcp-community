from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .deployment import DeploymentError, deploy_frontend, list_deployments, result_to_dict


mcp = FastMCP("agentx-frontend-deployer")


@mcp.tool()
def deploy_frontend_site(
    repository_url: str,
    site_name: str,
    ref: str = "main",
    build_script: str = "build",
    output_directory: str = "",
    install_dependencies: bool = True,
    timeout_seconds: int = 900,
) -> str:
    """从公开 Git 仓库构建并部署一个静态前端站点。

    支持 npm、pnpm、yarn 和 bun。工具只会执行 package.json 中指定的构建脚本，
    不接受任意 Shell 命令。构建产物默认从 dist、build、out 中自动识别。
    """
    try:
        result = deploy_frontend(
            repository_url=repository_url,
            site_name=site_name,
            ref=ref,
            build_script=build_script,
            output_directory=output_directory,
            install_dependencies=install_dependencies,
            timeout_seconds=timeout_seconds,
        )
        return json.dumps(result_to_dict(result), ensure_ascii=False, indent=2)
    except DeploymentError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


@mcp.tool()
def list_frontend_deployments() -> str:
    """列出当前部署根目录中的前端站点及其当前版本信息。"""
    return json.dumps(list_deployments(), ensure_ascii=False, indent=2)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
