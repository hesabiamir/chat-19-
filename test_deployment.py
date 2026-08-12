import json
import re
import shlex
from pathlib import Path

import pytest

from railway_start import configure_runtime, uvicorn_command
from install_builtin_sources import EXPECTED_SHA256, PART_SHA256, install_from_parts


ROOT = Path(__file__).resolve().parent


def _docker_instructions() -> list[str]:
    physical = (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    logical: list[str] = []
    pending = ""
    for raw in physical:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pending = f"{pending} {line}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical.append(pending)
        pending = ""
    assert not pending
    return logical


def test_every_docker_copy_source_exists_in_the_build_context():
    sources: list[str] = []
    for instruction in _docker_instructions():
        if not instruction.upper().startswith("COPY "):
            continue
        arguments = shlex.split(instruction[5:], posix=True)
        assert len(arguments) >= 2
        sources.extend(arguments[:-1])
    assert sources
    for source in sources:
        candidate = ROOT / source.removeprefix("./").rstrip("/")
        assert candidate.exists(), f"Docker COPY source is missing: {source}"


def test_docker_never_depends_on_pyproject_or_an_ignored_source():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert (ROOT / "pyproject.toml").is_file()
    assert "COPY pyproject.toml" not in docker
    assert "COPY ./pyproject.toml" not in docker
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    required = {
        "requirements.lock.txt", "main.py", "ui_templates.py", "rag_engine.py",
        "deep_rag.py", "release_info.py", "source_quality.py", "provider_runtime.py",
        "runtime_guards.py", "ops_runtime.py", "ui_components.py", "barsan_cargo.py",
        "barsan_location.py", "railway_start.py", "install_builtin_sources.py",
        "FAQ_TEMPLATE.csv", "thinking_loader.mp4", "builtin_sources.bundle.part01",
        "builtin_sources.bundle.part02", "builtin_sources.bundle.part03",
        "builtin_sources.bundle.part04", "builtin_sources.bundle.part05",
        "builtin_sources.bundle.part06", "builtin_sources.bundle.part07",
        "builtin_sources.bundle.part08", "builtin_sources.bundle.part09",
    }
    normalized = {line.strip().rstrip("/") for line in ignored}
    assert required.isdisjoint(normalized)
    assert "COPY ./builtin_sources/" not in docker


def test_dependency_lock_is_single_source_and_fully_pinned():
    assert (ROOT / "requirements.txt").read_text(encoding="utf-8").strip() == "-r requirements.lock.txt"
    lines = [line.strip() for line in (ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 30
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+", line) for line in lines)
    names = [line.split("==", 1)[0].lower().replace("_", "-") for line in lines]
    assert len(names) == len(set(names))


def test_railway_uses_one_explicit_docker_build_and_start_path():
    config = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    assert config["build"] == {"builder": "DOCKERFILE", "dockerfilePath": "Dockerfile"}
    assert config["deploy"]["preDeployCommand"] is None
    assert config["deploy"]["healthcheckPath"] == "/healthz"
    assert config["deploy"]["healthcheckTimeout"] == 600
    assert "startCommand" not in config["deploy"]
    assert not (ROOT / "Procfile").exists()
    assert not (ROOT / "nixpacks.toml").exists()


def test_runtime_contract_validates_network_storage_and_privileges():
    launcher = (ROOT / "railway_start.py").read_text(encoding="utf-8")
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "PORT must be an integer between 1 and 65535" in launcher
    assert '"0.0.0.0"' in launcher
    assert 'env["PORT"]' in launcher
    assert 'env.setdefault("TRUSTED_PROXY_IPS", "127.0.0.1")' in launcher
    assert 'env.get("RAILWAY_VOLUME_MOUNT_PATH")' in launcher
    assert "os.execvpe" in launcher
    assert "os.setgroups([])" in launcher and "os.setuid(uid)" in launcher
    assert 'ENTRYPOINT ["python", "/app/railway_start.py"]' in docker


def test_health_endpoint_is_liveness_only_and_readiness_remains_available():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    health = source[source.index("@app.get('/healthz')"):source.index("@app.get('/readyz')")]
    assert "get_db" not in health
    assert "httpx" not in health
    assert "'status': 'ok'" in health
    assert "@app.get('/readyz')" in source


def test_sensitive_and_generated_files_are_excluded_from_context_and_git():
    for ignore_name in (".dockerignore", ".gitignore"):
        content = (ROOT / ignore_name).read_text(encoding="utf-8")
        rules = {line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")}
        assert ".env" in content and ".env.*" in content and "!.env.example" in content
        assert any(rule.rstrip("/") == "__pycache__" for rule in rules)
        assert "*.py" not in rules
        assert "*.db" in content and "*.zip" in content
        if ignore_name == ".gitignore":
            assert all(f"!builtin_sources.bundle.part{index:02d}" in rules for index in range(1, len(PART_SHA256) + 1))


def test_production_image_has_no_secret_build_arguments_or_embedded_environment_file():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    forbidden = ("JWT_SECRET", "INITIAL_ADMIN_PASSWORD", "AI_API_KEY", "GEMINI_API_KEY", "COPY .env")
    assert all(item not in docker for item in forbidden)
    assert "COPY . /app" not in docker and "COPY . ." not in docker


def test_launcher_maps_railway_volume_and_dynamic_port():
    env = configure_runtime({"PORT": "9123", "RAILWAY_VOLUME_MOUNT_PATH": "/mnt/barsan"})
    assert env["DATABASE_URL"] == "sqlite:////mnt/barsan/barsan.db"
    assert env["UPLOAD_DIR"] == "/mnt/barsan/uploads"
    command = uvicorn_command(env)
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert command[command.index("--port") + 1] == "9123"
    assert command[command.index("--forwarded-allow-ips") + 1] == "127.0.0.1"


@pytest.mark.parametrize("value", ["", "zero", "0", "65536"])
def test_launcher_rejects_invalid_ports_before_start(value):
    with pytest.raises(RuntimeError, match="PORT"):
        configure_runtime({"PORT": value})


def test_launcher_rejects_filesystem_root_as_data_directory():
    with pytest.raises(RuntimeError, match="DATA_DIR"):
        configure_runtime({"DATA_DIR": "/"})


def test_single_root_builtin_bundle_installs_and_verifies_every_source(tmp_path):
    destination = tmp_path / "builtin_sources"
    parts = [ROOT / f"builtin_sources.bundle.part{index:02d}" for index in range(1, len(PART_SHA256) + 1)]
    install_from_parts(parts, destination)
    assert {path.name for path in destination.iterdir()} == set(EXPECTED_SHA256)
    assert all(path.stat().st_size > 0 for path in destination.iterdir())
    preindex = json.loads((destination / "preindex.json").read_text(encoding="utf-8"))
    assert len(preindex.get("sources", {})) == 4
    source_text = "\n".join(
        str((item.get("result") or {}).get("text") or "")
        for item in preindex["sources"].values()
    )
    assert "کنسلی پایه خاور" in source_text
    assert "رسیدن به مبدا" in source_text or "رسیدن به مبدأ" in source_text
