import json
import tempfile
import unittest
from pathlib import Path

from frontend_deployer_mcp.deployment import (
    DeploymentError,
    _publish_build,
    detect_project,
    validate_repository_url,
    validate_site_name,
)


class DeploymentTest(unittest.TestCase):
    def test_validate_repository_url(self) -> None:
        self.assertEqual(
            validate_repository_url("https://github.com/example/frontend"),
            "https://github.com/example/frontend",
        )
        with self.assertRaises(DeploymentError):
            validate_repository_url("https://user:token@github.com/example/frontend")
        with self.assertRaises(DeploymentError):
            validate_repository_url("file:///tmp/frontend")

    def test_validate_site_name(self) -> None:
        self.assertEqual(validate_site_name("demo-site"), "demo-site")
        with self.assertRaises(DeploymentError):
            validate_site_name("../demo")

    def test_detect_npm_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "package.json").write_text(
                json.dumps({"scripts": {"build": "vite build"}}),
                encoding="utf-8",
            )
            (project / "package-lock.json").write_text("{}", encoding="utf-8")

            info = detect_project(project)

            self.assertEqual(info.package_manager, "npm")
            self.assertEqual(info.install_args, ["npm", "ci"])
            self.assertEqual(info.available_scripts, ["build"])

    def test_publish_build_creates_release_and_current(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "dist"
            build.mkdir()
            (build / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")

            release_id, release_path, current_path = _publish_build(
                build,
                root / "deployments",
                "demo-site",
                {"siteName": "demo-site"},
            )

            self.assertTrue(release_id)
            self.assertTrue((release_path / "index.html").is_file())
            self.assertTrue((current_path / "index.html").is_file())
            self.assertTrue((current_path / ".agentx-deployment.json").is_file())


if __name__ == "__main__":
    unittest.main()

