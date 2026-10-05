#!/usr/bin/env python3
"""Build the referee programs from what scripts/fetch_references.py fetched.

Everything lands under reference/ (gitignored); nothing needs sudo. Run after
the fetch; each step is skipped when its output already exists.

- ``oss``: unpack the oss-cad-suite bundle into reference/build/oss-cad-suite
  (GHDL, Icarus Verilog, Verilator).
- ``rgbds``: unpack rgbds v1.0.4 into reference/build/rgbds.
- ``sameboy``: ``make tester`` in reference/src/SameBoy, giving
  build/bin/tester/sameboy_tester and SameBoy's free boot ROMs (dmg_boot.bin,
  cgb_boot.bin, ...) beside it.
- ``hdl``: a Python 3.12 venv at reference/build/hdl-venv with VUnit 4.7.0 for
  Gekkio's VHDL SM83 (reference/src/gb-research/sm83-cpu-core/hdl). VUnit's
  sdist needs an old setuptools to build, hence the two-step install.
- ``dmgsim``: ``make dmg_cpu_b_gameboy.vvp mkvid/mkimgs`` in
  reference/src/dmg-sim with the bundle's Icarus Verilog.

    python scripts/build_referees.py            # all steps
    python scripts/build_referees.py sameboy    # one step

uv is needed for the ``hdl`` step (``UV`` overrides the binary).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "reference" / "build"
SRC = ROOT / "reference" / "src"
OSS = BUILD / "oss-cad-suite"
RGBDS = BUILD / "rgbds"
VENV = BUILD / "hdl-venv"


def env_with_oss() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{OSS / 'bin'}:{env['PATH']}"
    return env


def unpack(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        bundle.extractall(target, filter="tar")


def step_oss() -> None:
    if (OSS / "bin" / "ghdl").exists():
        return
    unpack(BUILD / "oss-cad-suite-linux-x64-20261005.tgz", BUILD)


def step_rgbds() -> None:
    if (RGBDS / "rgbasm").exists():
        return
    unpack(BUILD / "rgbds-linux-x86_64.tar.xz", RGBDS)


def step_sameboy() -> None:
    if (SRC / "SameBoy" / "build" / "bin" / "tester" / "sameboy_tester").exists():
        return
    step_rgbds()
    subprocess.run(
        ["make", "tester", "CONF=release", f"RGBDS={RGBDS}/", f"-j{os.cpu_count() or 4}"],
        cwd=SRC / "SameBoy",
        check=True,
    )


def step_hdl() -> None:
    if (VENV / "bin" / "python").exists():
        return
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise SystemExit("hdl: uv not found (set UV=/path/to/uv)")
    python = str(VENV / "bin" / "python")
    subprocess.run([uv, "venv", "-q", "--python", "3.12", str(VENV)], check=True)
    pip = [uv, "pip", "install", "-q", "--python", python]
    subprocess.run([*pip, "setuptools<70", "setuptools_scm<8", "wheel"], check=True)
    subprocess.run([*pip, "--no-build-isolation", "vunit-hdl==4.7.0", "psutil", "toml"], check=True)


def step_dmgsim() -> None:
    if (SRC / "dmg-sim" / "dmg_cpu_b_gameboy.vvp").exists():
        return
    step_oss()
    subprocess.run(
        ["make", "dmg_cpu_b_gameboy.vvp", "mkvid/mkimgs"],
        cwd=SRC / "dmg-sim",
        env=env_with_oss(),
        check=True,
    )


STEPS = {
    "oss": step_oss,
    "rgbds": step_rgbds,
    "sameboy": step_sameboy,
    "hdl": step_hdl,
    "dmgsim": step_dmgsim,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("steps", nargs="*", choices=list(STEPS), help="default: all")
    args = parser.parse_args()
    for name in args.steps or STEPS:
        print(f"== {name}")
        STEPS[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
