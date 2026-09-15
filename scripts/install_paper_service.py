#!/usr/bin/env python3
"""Install an explicitly registered paper worker under the current macOS user."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LABEL = "ai.tajari.continuous-paper"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=ROOT/".venv-paper/bin/python")
    parser.add_argument("--port", type=int, default=8022)
    args = parser.parse_args()
    if sys.platform != "darwin": raise SystemExit("Use the supplied systemd unit on Linux")
    for path in (args.run_dir/"registration.json", args.env_file, args.python):
        if not path.exists(): raise SystemExit(f"Required file is missing: {path}")
    target = Path.home()/"Library/LaunchAgents"/(LABEL+".plist")
    if target.exists(): raise SystemExit("Service already installed; inspect it before replacing")
    target.parent.mkdir(parents=True, exist_ok=True)
    args.run_dir.chmod(0o700); args.env_file.chmod(0o600)
    config = {"Label": LABEL,
      "ProgramArguments": ["/usr/bin/caffeinate", "-i", str(args.python.absolute()), str(ROOT/"scripts/continuous_paper.py"), "run", "--run-dir", str(args.run_dir.resolve()), "--env-file", str(args.env_file.resolve()), "--port", str(args.port)],
      "WorkingDirectory": str(ROOT), "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
      "ThrottleInterval": 30, "ProcessType": "Background", "Umask": 63,
      "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
      "StandardOutPath": str(args.run_dir/"service.stdout.log"),
      "StandardErrorPath": str(args.run_dir/"service.stderr.log")}
    with target.open("xb") as f: plistlib.dump(config, f)
    target.chmod(0o600)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(target)], check=True)
    print(f"Installed {LABEL}; idle sleep inhibited while this worker runs. Lid-close, logout and power loss still interrupt it.")
    print(target)


if __name__ == "__main__": main()
