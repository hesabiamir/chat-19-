from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Mapping


def _port(value: str) -> str:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError("PORT must be an integer between 1 and 65535.") from exc
    if not 1 <= parsed <= 65535:
        raise RuntimeError("PORT must be an integer between 1 and 65535.")
    return str(parsed)


def _identity(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if not 1 <= parsed <= 2_147_483_647:
        raise RuntimeError(f"{name} must be a positive integer.")
    return parsed


def configure_runtime(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if environment is None else environment)
    raw_data_root = (env.get("RAILWAY_VOLUME_MOUNT_PATH") or env.get("DATA_DIR") or "/data").rstrip("/")
    if not raw_data_root or raw_data_root == "/":
        raise RuntimeError("DATA_DIR must be an absolute directory other than filesystem root.")
    if os.name == "posix" and not raw_data_root.startswith("/"):
        raise RuntimeError("DATA_DIR must be an absolute path on Linux.")
    data_root = PurePosixPath(raw_data_root) if raw_data_root.startswith("/") else Path(raw_data_root)
    env["DATA_DIR"] = str(data_root)

    if env.get("DATABASE_URL", "") in {"", "sqlite:////data/barsan.db"}:
        env["DATABASE_URL"] = f"sqlite:///{(data_root / 'barsan.db').as_posix()}"
    defaults = {
        "UPLOAD_DIR": ("/data/uploads", data_root / "uploads"),
        "UPLOAD_SESSION_DIR": ("/data/upload-sessions", data_root / "upload-sessions"),
        "BACKUP_DIR": ("/data/backups", data_root / "backups"),
    }
    for name, (legacy, target) in defaults.items():
        if env.get(name, "") in {"", legacy}:
            env[name] = str(target)

    env["PORT"] = _port(env.get("PORT", "8080"))
    env.setdefault("TRUSTED_PROXY_IPS", "127.0.0.1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    return env


def prepare_storage(env: Mapping[str, str]) -> None:
    paths = {
        Path(env["DATA_DIR"]),
        Path(env["UPLOAD_DIR"]),
        Path(env["UPLOAD_SESSION_DIR"]),
        Path(env["BACKUP_DIR"]),
    }
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)

    if os.name != "posix" or os.geteuid() != 0:
        return
    uid = _identity(env.get("BARSAN_RUN_UID", "10001"), "BARSAN_RUN_UID")
    gid = _identity(env.get("BARSAN_RUN_GID", "10001"), "BARSAN_RUN_GID")
    data_root = Path(env["DATA_DIR"])
    ownership_marker = data_root / f".barsan-owner-{uid}-{gid}"
    if not ownership_marker.exists():
        for current_root, directories, files in os.walk(data_root, followlinks=False):
            os.chown(current_root, uid, gid, follow_symlinks=False)
            for name in directories:
                os.chown(Path(current_root) / name, uid, gid, follow_symlinks=False)
            for name in files:
                os.chown(Path(current_root) / name, uid, gid, follow_symlinks=False)
        ownership_marker.touch(exist_ok=True)
    for path in paths | {ownership_marker}:
        os.chown(path, uid, gid, follow_symlinks=False)
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)


def uvicorn_command(env: Mapping[str, str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "0.0.0.0",
        "--port",
        env["PORT"],
        "--proxy-headers",
        "--forwarded-allow-ips",
        env["TRUSTED_PROXY_IPS"],
    ]


def main() -> None:
    env = configure_runtime()
    prepare_storage(env)
    print(
        f"BARSAN_START mode=docker port={env['PORT']} "
        f"data_root={env['DATA_DIR']} trusted_proxies={env['TRUSTED_PROXY_IPS']}",
        flush=True,
    )
    command = uvicorn_command(env)
    if os.name == "posix":
        os.execvpe(sys.executable, command, env)
    raise SystemExit(subprocess.call(command, env=env))


if __name__ == "__main__":
    main()
