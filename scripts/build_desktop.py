"""Build separate GUI and decompiler binaries so the worker has no Qt hooks."""

import shutil
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    common = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--distpath",
        str(root / "dist"),
        "--workpath",
        str(root / "build/pyinstaller"),
        "--specpath",
        str(root / "build/specs"),
    ]
    subprocess.run(
        common
        + [
            "--name",
            "RenpyDecompiler",
            "--console",
            "--collect-submodules",
            "renpy_translator._vendor.unrpyc",
            "--collect-data",
            "renpy_translator",
            str(root / "scripts/decompiler_entry.py"),
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        common
        + [
            "--name",
            "TradutorRenpy",
            "--windowed",
            "--collect-all",
            "renpy_translator",
            str(root / "scripts/desktop_entry.py"),
        ],
        cwd=root,
        check=True,
    )
    target = root / "dist/TradutorRenpy/worker/RenpyDecompiler"
    shutil.copytree(root / "dist/RenpyDecompiler", target)
    print(f"Aplicativo criado em {root / 'dist/TradutorRenpy'}")


if __name__ == "__main__":
    main()
