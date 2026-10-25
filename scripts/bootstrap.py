"""Install the locked development environment without model/provider setup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

UV_VERSION = "0.11.19"
ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify installed pins without installing")
    args = parser.parse_args(argv)
    uv = shutil.which("uv")
    if uv is None:
        parser.exit(2, f"Install uv {UV_VERSION} first; bootstrap does not install global tools.\n")
    actual_uv = subprocess.check_output([uv, "--version"], text=True).split()
    if actual_uv[:2] != ["uv", UV_VERSION]:
        parser.exit(2, f"Expected uv {UV_VERSION}; found {' '.join(actual_uv)}.\n")
    python_version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    env = dict(os.environ)
    env["UV_PYTHON_INSTALL_DIR"] = str(ROOT / ".agent-work" / "python")
    env["UV_PROJECT_ENVIRONMENT"] = str(ROOT / ".venv")
    env["UV_CACHE_DIR"] = str(ROOT / ".agent-work" / "uv-cache")
    env["UV_NO_ENV_FILE"] = "1"
    if not args.check:
        subprocess.run(
            [uv, "--no-config", "python", "install", python_version, "--no-bin", "--no-registry"],
            env=env,
            check=True,
        )
        managed = Path(
            subprocess.check_output(
                [uv, "--no-config", "python", "find", "--managed-python", python_version],
                env=env,
                text=True,
            ).strip()
        ).resolve()
        if not managed.is_relative_to((ROOT / ".agent-work" / "python").resolve()):
            parser.exit(2, "Managed interpreter is outside this checkout; refusing shared Python.\n")
        common = [
            uv,
            "--no-config",
            "sync",
            "--project",
            str(ROOT),
            "--locked",
            "--extra",
            "dev",
            "--group",
            "build",
            "--python",
            str(managed),
        ]
        # Build tools and their transitive dependencies come from uv.lock too.
        subprocess.run([*common, "--no-install-project", "--inexact"], env=env, check=True)
        subprocess.run([*common, "--no-build-isolation"], env=env, check=True)
    interpreter = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.is_file():
        parser.exit(2, "Project .venv is missing; run bootstrap without --check first.\n")
    subprocess.run(
        [
            uv,
            "--no-config",
            "lock",
            "--check",
            "--offline",
            "--project",
            str(ROOT),
            "--python",
            str(interpreter),
        ],
        env=env,
        check=True,
    )
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    pins = {p["name"]: p["version"] for p in lock["package"]}
    verify = (
        "import importlib.metadata as m,json,platform,sys; "
        "pins=json.loads(sys.argv[2]); "
        "assert platform.python_version()==sys.argv[1], 'Python pin mismatch'; "
        "bad={n:(v,m.version(n)) for n,v in pins.items() if m.version(n)!=v}; "
        "assert not bad, 'Dependency pin mismatch: '+str(bad); "
        "print('Verified Python '+platform.python_version()+' and '+str(len(pins))+' locked packages')"
    )
    subprocess.run(
        [str(interpreter), "-I", "-c", verify, python_version, json.dumps(pins)], env=env, check=True
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Bootstrap failed ({type(exc).__name__}); environment was not verified.", file=sys.stderr)
        raise SystemExit(1) from None
