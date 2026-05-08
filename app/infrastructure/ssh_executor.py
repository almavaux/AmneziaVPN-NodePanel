import asyncio
import logging
from pathlib import Path
import secrets
import shlex
import json
import time
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from ..core.config import settings
from ..core.db import SessionLocal, SSHTask, Node

logger = logging.getLogger(__name__)


def _build_payload_entries(project_root: Path) -> list[str]:
    """Return relative paths to upload from project root."""
    required = ["app", "docker", "scripts", "requirements.txt"]
    optional = [".env.example", "README.md"]

    missing = [rel for rel in required if not (project_root / rel).exists()]
    if missing:
        raise FileNotFoundError(f"Missing required project paths for SSH upload: {', '.join(missing)}")

    entries: list[str] = []
    for rel in required + optional:
        if (project_root / rel).exists():
            entries.append(rel)
    return entries


def _auto_register_node(target_host: str, attempts: int = 20, delay_sec: int = 3) -> tuple[bool, str, str | None]:
    """Trigger full bootstrap enrollment on master after SSH node install."""
    last_error = ""
    for attempt in range(1, attempts + 1):
        qs = urlparse.urlencode({"target": target_host, "force": "true"})
        req = urlrequest.Request(
            url=f"http://127.0.0.1:8000/panel/register-node?{qs}",
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                status = payload.get("status", "unknown")
                node_id = payload.get("node_id")
                return True, (
                    f"Bootstrap registration status: {status} "
                    f"(attempt {attempt}/{attempts})"
                ), node_id
        except urlerror.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {exc.code} {body}"
        except Exception as exc:
            last_error = str(exc)

        if attempt < attempts:
            time.sleep(delay_sec)

    return False, f"Bootstrap registration failed after {attempts} attempts: {last_error}", None


class SSHExecutor:
    """Execute SSH commands with progress tracking and logging."""

    @staticmethod
    async def execute_install(task_id: str, host: str, port: int, user: str, password: str) -> None:
        """Execute install script on remote host via SSH and log progress."""
        session = SessionLocal()
        task = None
        try:
            task = session.query(SSHTask).filter_by(id=task_id).first()
            if not task:
                logger.error(f"Task {task_id} not found")
                return

            task.status = "running"
            session.commit()

            project_root = Path(__file__).resolve().parents[2]

            # Resolve unified remote node installer from repository-level scripts directory.
            script_path = project_root / "scripts" / "install_node_remote.sh"
            if not script_path.exists():
                log_msg = f"Install script not found at {script_path}"
                task.log = log_msg
                task.status = "failed"
                session.commit()
                logger.error(log_msg)
                return

            remote_dir = "/opt/awg-api"
            api_key = secrets.token_urlsafe(32)
            master_ip = settings.server_host or "127.0.0.1"
            allowed_ip = settings.server_host or "0.0.0.0"
            dns = settings.dns or "1.1.1.1"

            try:
                payload_entries = _build_payload_entries(project_root)
            except FileNotFoundError as exc:
                task.status = "failed"
                task.log = str(exc)
                session.commit()
                logger.warning(f"SSH payload validation failed: {exc}")
                return

            tar_entries = " ".join(shlex.quote(entry) for entry in payload_entries)

            # 1) Upload project payload to remote host.
            payload_cmd = (
                f"tar --warning=no-timestamp -C {shlex.quote(str(project_root))} -cf - {tar_entries} "
                f"| sshpass -p {shlex.quote(password)} ssh -o StrictHostKeyChecking=no "
                f"-p {port} {shlex.quote(f'{user}@{host}')} "
                f"\"mkdir -p {remote_dir} && tar -xf - -C {remote_dir}\""
            )

            upload_proc = await asyncio.create_subprocess_shell(
                payload_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            up_out, up_err = await upload_proc.communicate()
            upload_logs = up_out.decode(errors="ignore") + up_err.decode(errors="ignore")
            if upload_proc.returncode != 0:
                task.status = "failed"
                task.log = f"Project upload failed:\n{upload_logs}"
                session.commit()
                logger.warning(f"SSH upload failed on {host}:{port}: {upload_logs}")
                return

            # 2) Execute shared node installer script on remote host.
            remote_install_cmd = [
                "sshpass",
                "-p",
                password,
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-p",
                str(port),
                f"{user}@{host}",
                "bash",
                f"{remote_dir}/scripts/install_node_remote.sh",
                "--master-ip",
                master_ip,
                "--allowed-ip",
                allowed_ip,
                "--public-ip",
                host,
                "--dns",
                dns,
                "--api-key",
                api_key,
                "--target-dir",
                remote_dir,
            ]

            proc = await asyncio.create_subprocess_exec(
                *remote_install_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate()
            logs = upload_logs + stdout.decode(errors="ignore") + stderr.decode(errors="ignore")

            if proc.returncode == 0:
                ok, bootstrap_msg, enrolled_node_id = await asyncio.to_thread(_auto_register_node, host)
                logs = f"{logs}\n{bootstrap_msg}\n"
                if ok:
                    task.status = "success"
                    node = session.query(Node).filter_by(id=task.node_id).first()
                    if node:
                        node.status = "active"
                        node.node_version = settings.node_version
                        if enrolled_node_id:
                            node.node_id = enrolled_node_id
                    task.log = logs
                else:
                    task.status = "failed"
                    task.log = logs
            else:
                task.status = "failed"
                task.log = logs
                logger.warning(f"SSH install failed on {host}:{port}: {logs}")

            session.commit()
        except Exception as exc:
            logger.exception(f"SSH executor error for task {task_id}")
            if task:
                task.status = "failed"
                task.log = str(exc)
                session.commit()
        finally:
            session.close()

    @staticmethod
    async def execute_update(task_id: str, host: str, port: int, user: str, password: str) -> None:
        """Upload current project and update existing remote node in-place."""
        session = SessionLocal()
        task = None
        try:
            task = session.query(SSHTask).filter_by(id=task_id).first()
            if not task:
                logger.error(f"Task {task_id} not found")
                return

            task.status = "running"
            session.commit()

            project_root = Path(__file__).resolve().parents[2]
            payload_entries = _build_payload_entries(project_root)
            tar_entries = " ".join(shlex.quote(entry) for entry in payload_entries)
            remote_dir = "/opt/awg-api"

            payload_cmd = (
                f"tar --warning=no-timestamp -C {shlex.quote(str(project_root))} -cf - {tar_entries} "
                f"| sshpass -p {shlex.quote(password)} ssh -o StrictHostKeyChecking=no "
                f"-p {port} {shlex.quote(f'{user}@{host}')} "
                f"\"mkdir -p {remote_dir} && tar -xf - -C {remote_dir}\""
            )

            upload_proc = await asyncio.create_subprocess_shell(
                payload_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            up_out, up_err = await upload_proc.communicate()
            upload_logs = up_out.decode(errors="ignore") + up_err.decode(errors="ignore")
            if upload_proc.returncode != 0:
                task.status = "failed"
                task.log = f"Project upload failed:\n{upload_logs}"
                node = session.query(Node).filter_by(id=task.node_id).first()
                if node:
                    node.status = "offline"
                session.commit()
                return

            remote_update_cmd = [
                "sshpass",
                "-p",
                password,
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-p",
                str(port),
                f"{user}@{host}",
                "bash",
                f"{remote_dir}/scripts/install_project.sh",
                "--project-dir",
                remote_dir,
                "--mode",
                "update",
            ]

            proc = await asyncio.create_subprocess_exec(
                *remote_update_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            logs = upload_logs + stdout.decode(errors="ignore") + stderr.decode(errors="ignore")

            node = session.query(Node).filter_by(id=task.node_id).first()
            if proc.returncode == 0:
                task.status = "success"
                task.log = logs
                if node:
                    node.status = "active"
                    node.node_version = settings.node_version
            else:
                task.status = "failed"
                task.log = logs
                if node:
                    node.status = "offline"

            session.commit()
        except Exception as exc:
            logger.exception(f"SSH update executor error for task {task_id}")
            if task:
                task.status = "failed"
                task.log = str(exc)
                node = session.query(Node).filter_by(id=task.node_id).first()
                if node:
                    node.status = "offline"
                session.commit()
        finally:
            session.close()


ssh_executor = SSHExecutor()
