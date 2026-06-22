from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse


class DeploymentError(RuntimeError):
    """部署输入或执行过程不满足安全约束。"""


@dataclass(frozen=True)
class ProjectInfo:
    package_manager: str
    install_args: list[str]
    available_scripts: list[str]
    detected_output_directory: str | None


@dataclass(frozen=True)
class DeploymentResult:
    site_name: str
    repository_url: str
    ref: str
    package_manager: str
    output_directory: str
    release_id: str
    release_path: str
    current_path: str
    deployed_at: str


SITE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SUPPORTED_GIT_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
OUTPUT_DIRECTORY_CANDIDATES = ("dist", "build", "out")


def validate_site_name(site_name: str) -> str:
    normalized = site_name.strip().lower()
    if not SITE_NAME_PATTERN.fullmatch(normalized):
        raise DeploymentError("站点名只能包含小写字母、数字和连字符，长度为 1-63 个字符")
    return normalized


def validate_repository_url(repository_url: str) -> str:
    parsed = urlparse(repository_url.strip())
    if parsed.scheme != "https" or parsed.hostname not in SUPPORTED_GIT_HOSTS:
        raise DeploymentError("仅支持 GitHub、GitLab 或 Bitbucket 的 HTTPS 公开仓库地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DeploymentError("仓库地址不能包含凭据、查询参数或片段")
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2:
        raise DeploymentError("仓库地址必须包含所有者和仓库名")
    return repository_url.strip()


def ensure_relative_path(relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise DeploymentError("输出目录必须是项目内的相对路径")
    return candidate


def detect_project(project_path: Path) -> ProjectInfo:
    package_json_path = project_path / "package.json"
    if not package_json_path.is_file():
        raise DeploymentError("仓库根目录缺少 package.json，目前仅支持 Node.js 前端项目")

    try:
        package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError(f"无法读取 package.json：{exc}") from exc

    scripts = package_json.get("scripts")
    available_scripts = sorted(scripts.keys()) if isinstance(scripts, dict) else []

    if (project_path / "pnpm-lock.yaml").is_file():
        package_manager = "pnpm"
        install_args = ["pnpm", "install", "--frozen-lockfile"]
    elif (project_path / "yarn.lock").is_file():
        package_manager = "yarn"
        install_args = ["yarn", "install", "--frozen-lockfile"]
    elif (project_path / "bun.lock").is_file() or (project_path / "bun.lockb").is_file():
        package_manager = "bun"
        install_args = ["bun", "install", "--frozen-lockfile"]
    elif (project_path / "package-lock.json").is_file():
        package_manager = "npm"
        install_args = ["npm", "ci"]
    else:
        package_manager = "npm"
        install_args = ["npm", "install"]

    detected_output = next(
        (directory for directory in OUTPUT_DIRECTORY_CANDIDATES if (project_path / directory).is_dir()),
        None,
    )
    return ProjectInfo(package_manager, install_args, available_scripts, detected_output)


def _run(command: list[str], cwd: Path, timeout_seconds: int) -> str:
    executable = shutil.which(command[0])
    if executable is None:
        raise DeploymentError(f"运行环境中未安装 {command[0]}")

    process = subprocess.run(
        [executable, *command[1:]],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        env={**os.environ, "CI": "true"},
    )
    output = "\n".join(part.strip() for part in (process.stdout, process.stderr) if part.strip())
    if process.returncode != 0:
        tail = output[-4000:] if output else "命令没有输出"
        raise DeploymentError(f"命令执行失败：{' '.join(command)}\n{tail}")
    return output[-4000:]


def _build_command(package_manager: str, build_script: str) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,64}", build_script):
        raise DeploymentError("构建脚本名称格式不合法")
    if package_manager in {"npm", "pnpm", "yarn", "bun"}:
        return [package_manager, "run", build_script]
    raise DeploymentError(f"不支持的包管理器：{package_manager}")


def _publish_build(
    build_path: Path,
    deployment_root: Path,
    site_name: str,
    metadata: dict[str, object],
) -> tuple[str, Path, Path]:
    if not build_path.is_dir():
        raise DeploymentError(f"构建产物目录不存在：{build_path.name}")
    if not any(build_path.iterdir()):
        raise DeploymentError("构建产物目录为空")

    release_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    site_root = deployment_root.resolve() / "sites" / site_name
    releases_root = site_root / "releases"
    release_path = releases_root / release_id
    current_path = site_root / "current"
    staging_path = site_root / f".current-{release_id}"

    releases_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(build_path, release_path)
    (release_path / ".agentx-deployment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    shutil.copytree(release_path, staging_path)

    previous_path = site_root / ".previous"
    if previous_path.exists():
        shutil.rmtree(previous_path)
    if current_path.exists():
        current_path.rename(previous_path)
    staging_path.rename(current_path)
    if previous_path.exists():
        shutil.rmtree(previous_path)

    return release_id, release_path, current_path


def deploy_frontend(
    repository_url: str,
    site_name: str,
    ref: str = "main",
    build_script: str = "build",
    output_directory: str | None = None,
    install_dependencies: bool = True,
    timeout_seconds: int = 900,
) -> DeploymentResult:
    repository_url = validate_repository_url(repository_url)
    site_name = validate_site_name(site_name)
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", ref) or ".." in ref:
        raise DeploymentError("Git 引用格式不合法")
    if timeout_seconds < 30 or timeout_seconds > 3600:
        raise DeploymentError("超时时间必须在 30-3600 秒之间")

    work_root = Path(os.getenv("FRONTEND_DEPLOY_WORK_ROOT", tempfile.gettempdir())).resolve()
    deployment_root = Path(
        os.getenv("FRONTEND_DEPLOY_TARGET_ROOT", str(work_root / "agentx-frontend-deployments"))
    ).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    deployment_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="agentx-frontend-", dir=work_root) as temp_directory:
        project_path = Path(temp_directory) / "source"
        _run(
            ["git", "clone", "--depth", "1", "--branch", ref, "--", repository_url, str(project_path)],
            Path(temp_directory),
            timeout_seconds,
        )
        project_info = detect_project(project_path)
        if build_script not in project_info.available_scripts:
            raise DeploymentError(
                f"package.json 中不存在脚本 {build_script}；可用脚本：{', '.join(project_info.available_scripts)}"
            )

        if install_dependencies:
            _run(project_info.install_args, project_path, timeout_seconds)
        _run(_build_command(project_info.package_manager, build_script), project_path, timeout_seconds)

        selected_output = (
            ensure_relative_path(output_directory)
            if output_directory
            else next(
                (
                    Path(directory)
                    for directory in OUTPUT_DIRECTORY_CANDIDATES
                    if (project_path / directory).is_dir()
                ),
                None,
            )
        )
        if selected_output is None:
            raise DeploymentError("未找到 dist、build 或 out，请显式指定静态构建产物目录")

        deployed_at = datetime.now(UTC).isoformat()
        metadata = {
            "siteName": site_name,
            "repositoryUrl": repository_url,
            "ref": ref,
            "packageManager": project_info.package_manager,
            "outputDirectory": selected_output.as_posix(),
            "deployedAt": deployed_at,
        }
        release_id, release_path, current_path = _publish_build(
            (project_path / selected_output).resolve(),
            deployment_root,
            site_name,
            metadata,
        )
        return DeploymentResult(
            site_name=site_name,
            repository_url=repository_url,
            ref=ref,
            package_manager=project_info.package_manager,
            output_directory=selected_output.as_posix(),
            release_id=release_id,
            release_path=str(release_path),
            current_path=str(current_path),
            deployed_at=deployed_at,
        )


def list_deployments() -> list[dict[str, object]]:
    work_root = Path(os.getenv("FRONTEND_DEPLOY_WORK_ROOT", tempfile.gettempdir())).resolve()
    deployment_root = Path(
        os.getenv("FRONTEND_DEPLOY_TARGET_ROOT", str(work_root / "agentx-frontend-deployments"))
    ).resolve()
    sites_root = deployment_root / "sites"
    if not sites_root.is_dir():
        return []

    deployments: list[dict[str, object]] = []
    for site_root in sorted(path for path in sites_root.iterdir() if path.is_dir()):
        current_manifest = site_root / "current" / ".agentx-deployment.json"
        if not current_manifest.is_file():
            continue
        try:
            metadata = json.loads(current_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {"siteName": site_root.name, "status": "manifest_invalid"}
        releases_root = site_root / "releases"
        metadata["releaseCount"] = (
            sum(1 for path in releases_root.iterdir() if path.is_dir()) if releases_root.is_dir() else 0
        )
        metadata["currentPath"] = str(site_root / "current")
        deployments.append(metadata)
    return deployments


def result_to_dict(result: DeploymentResult) -> dict[str, object]:
    return asdict(result)

