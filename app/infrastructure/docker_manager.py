"""
Thin wrapper around the Docker SDK.
All container I/O (exec + file read/write) lives here.
"""
import io
import tarfile

import docker
from docker.errors import DockerException, NotFound

from ..core.config import settings


class DockerManager:
    def __init__(self) -> None:
        self._client = docker.DockerClient(base_url=settings.docker_socket)
        self._resolved_container_name: str | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _container(self):
        try:
            # Reuse previously detected container name to avoid listing on every call.
            if self._resolved_container_name:
                try:
                    return self._client.containers.get(self._resolved_container_name)
                except NotFound:
                    self._resolved_container_name = None

            preferred_names = [settings.container_name, "amnezia-awg2", "amnezia-awg"]
            tried: list[str] = []
            seen: set[str] = set()

            for name in preferred_names:
                if not name or name in seen:
                    continue
                seen.add(name)
                tried.append(name)
                try:
                    container = self._client.containers.get(name)
                    self._resolved_container_name = name
                    return container
                except NotFound:
                    continue

            available = [c.name for c in self._client.containers.list(all=True)]
            raise RuntimeError(
                f"AmneziaWG container not found. Tried: {', '.join(tried)}. "
                f"Available: {', '.join(available) if available else '(none)'}"
            )
        except DockerException as exc:
            raise RuntimeError(f"Docker socket error: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def exec_run(self, cmd: list[str]) -> str:
        """Run a command inside the container; return stdout or raise."""
        container = self._container()
        result = container.exec_run(cmd, demux=False)
        output = result.output.decode(errors="replace").strip() if result.output else ""
        if result.exit_code != 0:
            raise RuntimeError(
                f"Container command {cmd} failed (exit {result.exit_code}): {output}"
            )
        return output

    def exec_shell(self, shell_cmd: str) -> str:
        """Run a shell one-liner via sh -c."""
        return self.exec_run(["sh", "-c", shell_cmd])

    def read_file(self, path: str) -> str:
        """Read a text file from inside the container."""
        container = self._container()
        try:
            bits, _ = container.get_archive(path)
        except DockerException as exc:
            raise FileNotFoundError(f"Cannot read {path} from container: {exc}") from exc

        raw = io.BytesIO(b"".join(bits))
        with tarfile.open(fileobj=raw) as tar:
            member = tar.getmembers()[0]
            content = tar.extractfile(member)
            if content is None:
                raise FileNotFoundError(f"Cannot extract {path}")
            return content.read().decode()

    def write_file(self, path: str, content: str) -> None:
        """Write a text file into the container at the given path."""
        container = self._container()
        content_bytes = content.encode()
        filename = path.rsplit("/", 1)[-1]
        directory = path.rsplit("/", 1)[0]

        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(content_bytes)
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(content_bytes))
        stream.seek(0)

        try:
            container.put_archive(directory, stream)
        except DockerException as exc:
            raise RuntimeError(f"Cannot write {path} in container: {exc}") from exc


# Singleton – re-used across the lifetime of the process
docker_manager = DockerManager()
