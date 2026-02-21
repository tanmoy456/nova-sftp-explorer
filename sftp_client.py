import os
import stat
from dataclasses import dataclass
from datetime import datetime

import paramiko


@dataclass
class RemoteEntry:
    name: str
    file_type: str
    size_human: str
    modified: str
    full_path: str
    is_dir: bool
    st_mode: int
    st_size: int


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


class SFTPClient:
    def __init__(self):
        self.ssh = None
        self.sftp = None

    @property
    def connected(self) -> bool:
        return self.sftp is not None

    def connect(self, host: str, port: int, username: str, password: str, timeout: int = 10) -> str:
        self.disconnect()
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(hostname=host, port=port, username=username, password=password, timeout=timeout)
        self.sftp = self.ssh.open_sftp()
        return self.sftp.normalize(".")

    def disconnect(self):
        if self.sftp:
            try:
                self.sftp.close()
            except Exception:
                pass
        if self.ssh:
            try:
                self.ssh.close()
            except Exception:
                pass
        self.sftp = None
        self.ssh = None

    def normalize(self, path: str) -> str:
        return self.sftp.normalize(path)

    def stat(self, path: str):
        return self.sftp.stat(path)

    def listdir(self, path: str) -> list[RemoteEntry]:
        entries = self.sftp.listdir_attr(path)
        rows: list[RemoteEntry] = []
        for entry in entries:
            is_dir = stat.S_ISDIR(entry.st_mode)
            full_path = self.join_remote(path, entry.filename)
            rows.append(
                RemoteEntry(
                    name=entry.filename,
                    file_type="DIR" if is_dir else "FILE",
                    size_human="-" if is_dir else human_size(entry.st_size),
                    modified=datetime.fromtimestamp(entry.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    full_path=full_path,
                    is_dir=is_dir,
                    st_mode=entry.st_mode,
                    st_size=entry.st_size,
                )
            )
        rows.sort(key=lambda r: (not r.is_dir, r.name.lower()))
        return rows

    def read_range(self, path: str, offset: int, size: int) -> bytes:
        with self.sftp.open(path, "rb") as handle:
            handle.seek(offset)
            return handle.read(size)

    def read_head(self, path: str, size: int) -> bytes:
        with self.sftp.open(path, "rb") as handle:
            return handle.read(size)

    def put(self, local_path: str, remote_path: str, callback=None):
        self.sftp.put(local_path, remote_path, callback=callback)

    def get(self, remote_path: str, local_path: str, callback=None):
        self.sftp.get(remote_path, local_path, callback=callback)

    @staticmethod
    def join_remote(base: str, name: str) -> str:
        if base == "/":
            return f"/{name}"
        return f"{base.rstrip('/')}/{name}"

    @staticmethod
    def resolve_target_path(path: str, cwd: str, home: str) -> str:
        if not path:
            return "/"
        if path.startswith("~/"):
            path = SFTPClient.join_remote(home, path[2:])
        elif path == "~":
            path = home
        elif not path.startswith("/"):
            path = SFTPClient.join_remote(cwd, path)
        while "//" in path:
            path = path.replace("//", "/")
        return path
