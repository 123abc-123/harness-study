"""Two explicit backends: isolated Docker, or opted-in trusted local execution."""

import os
from pathlib import Path
import signal
import subprocess
import threading
import uuid

from .files import Workspace


class Executor:
    def __init__(self, workspace: Workspace, mode: str = "disabled", image: str = "python:3.12-slim"):
        if mode not in ("disabled", "docker", "trusted-local"):
            raise ValueError("Unknown executor")
        self.workspace, self.mode, self.image = workspace, mode, image

    def run_command(self, argv: list[str], cwd: str = "work", timeout: int = 30) -> dict:
        """Execute an argument array, never a shell string. Executor must be enabled by the operator."""
        if self.mode == "disabled":
            raise PermissionError("Execution disabled. Select docker or explicitly trusted-local")
        if not argv or not all(isinstance(arg, str) for arg in argv):
            raise ValueError("argv must be a nonempty string array")
        if not 1 <= timeout <= 120:
            raise ValueError("timeout must be 1..120 seconds")
        workdir = self.workspace.resolve(cwd, write=True)
        workdir.mkdir(parents=True, exist_ok=True)
        container = "kg-harness-" + uuid.uuid4().hex
        if self.mode == "docker":
            root = self.workspace.root
            command = ["docker", "run", "--rm", "--name", container, "--pull=never",
                       "--network=none", "--read-only", "--cap-drop=ALL",
                       "--security-opt=no-new-privileges", "--pids-limit=64",
                       "--memory=512m", "--cpus=1", "--user=65534:65534",
                       "--tmpfs=/tmp:rw,nosuid,size=64m"]
            for folder in ("inputs", "work", "outputs"):
                mount = f"type=bind,source={root / folder},target=/workspace/{folder}"
                if folder == "inputs":
                    mount += ",readonly"
                command += ["--mount", mount]
            command += ["--workdir", "/workspace/" + workdir.relative_to(root).as_posix(),
                        self.image, *argv]
        else:
            command = argv
        # Do not forward API keys or the full parent environment to child programs.
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}}
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(command, cwd=workdir, env=env, shell=False,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=os.name != "nt",
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        output = bytearray()
        total = [0]

        def drain():
            while chunk := process.stdout.read(4096):
                total[0] += len(chunk)
                remaining = 32000 - len(output)
                if remaining > 0:
                    output.extend(chunk[:remaining])

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    # The trusted backend cannot promise descendant isolation.
                    # Still terminate the immediate process when tree cleanup fails.
                    pass
                finally:
                    if process.poll() is None:
                        process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        finally:
            if self.mode == "docker":
                subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=15)
        reader.join(timeout=2)
        if not reader.is_alive():
            process.stdout.close()
        return {"exit_code": process.returncode, "timed_out": timed_out,
                "output": output.decode("utf-8", errors="replace"),
                "truncated": total[0] > len(output), "executor": self.mode}
