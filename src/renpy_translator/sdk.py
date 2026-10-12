import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from bisect import bisect_left
from contextlib import contextmanager
from pathlib import Path

from .extractors import extract_renpy, renpy_literal, string_tokens
from .model import Entry, make_entry

BLOCK = re.compile(r"^translate\s+([a-z][a-z0-9_]*)\s+([\w]+)\s*:\s*$", re.MULTILINE)


@contextmanager
def sdk_dll_search_path():
    """A frozen Qt app must not inject its own DLLs into the SDK's process."""
    if os.name == "nt" and getattr(sys, "frozen", False):
        kernel = ctypes.windll.kernel32
        previous = ctypes.create_unicode_buffer(32768)
        kernel.GetDllDirectoryW(len(previous), previous)
        kernel.SetDllDirectoryW(None)
        try:
            yield
        finally:
            kernel.SetDllDirectoryW(previous.value or None)
    else:
        yield


def sdk_launcher(root: Path) -> Path:
    root = root.expanduser().resolve()
    launcher = root / ("renpy.exe" if os.name == "nt" else "renpy.sh")
    if not launcher.is_file() or not (root / "renpy").is_dir():
        raise ValueError(
            "Selecione a pasta do SDK oficial, que contém renpy.exe ou renpy.sh e renpy/."
        )
    return launcher


def find_sdk() -> Path | None:
    if os.environ.get("RENPY_SDK"):
        root = Path(os.environ["RENPY_SDK"])
        sdk_launcher(root)
        return root
    return None


def generate_templates(
    game: Path, files: list[Path], language: str, sdk: Path
) -> tuple[dict, list, str]:
    launcher = sdk_launcher(sdk)
    with tempfile.TemporaryDirectory(prefix="renpy-sdk-") as folder:
        utility = Path(folder)
        (utility / "game").mkdir()
        shutil.copyfile(Path(__file__).with_name("sdk_driver.rpy"), utility / "game/script.rpy")
        result_path = utility / "result.json"
        request_path = utility / "request.json"
        request_path.write_text(
            json.dumps(
                {
                    "game": str(game.resolve()),
                    "files": [str(file.resolve()) for file in files],
                    "language": language,
                    "result": str(result_path),
                    "tl_directory": str(utility / "generated"),
                }
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "SDL_VIDEODRIVER": "dummy",
            "SDL_AUDIODRIVER": "dummy",
            "RENPY_LOG_TO": str(utility),
            "PYTHONIOENCODING": "utf-8",
        }
        if getattr(sys, "frozen", False):
            if "LD_LIBRARY_PATH_ORIG" in env:
                env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
            else:
                env.pop("LD_LIBRARY_PATH", None)
        with sdk_dll_search_path():
            result = subprocess.run(
                [str(launcher), str(utility), "rnt_generate", str(request_path)],
                cwd=utility,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        if not result_path.exists():
            diagnostic = result.stderr or result.stdout
            for name in ("traceback.txt", "errors.txt"):
                if (utility / name).exists():
                    diagnostic += (utility / name).read_text(encoding="utf-8-sig")
            raise ValueError("O SDK não conseguiu gerar a tradução:\n" + diagnostic[-6000:])
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if result.returncode or payload.get("error"):
            raise ValueError("Erro na geração pelo SDK:\n" + payload.get("error", result.stderr))
        tl = utility / "generated" / language
        templates = {}
        for path in sorted(tl.rglob("*.rpy")):
            content = path.read_text(encoding="utf-8-sig")
            content = "".join(
                line.replace(str(game.resolve()), "game") if line.lstrip().startswith("#") else line
                for line in content.splitlines(keepends=True)
            )
            templates[path.relative_to(tl).as_posix()] = content
        return templates, payload["warnings"], payload["version"]


def template_blocks(text: str):
    matches = list(BLOCK.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        yield match[2], match.start(), end


def extract_template(text: str, filename: str) -> list[Entry]:
    entries = []
    comments = list(re.finditer(r"^\s*# [^\n]+:(\d+)\s*$", text, re.MULTILINE))
    comment_positions = [comment.start() for comment in comments]

    def original_line(position, default):
        index = bisect_left(comment_positions, position) - 1
        return int(comments[index][1]) if index >= 0 else default

    for identifier, start, end in template_blocks(text):
        block = text[start:end]
        if identifier == "strings":
            original = None
            for token in string_tokens(block):
                prefix = block[block.rfind("\n", 0, token.start) + 1 : token.start].strip()
                if prefix == "old":
                    original = renpy_literal(token.raw)
                elif prefix == "new" and original is not None:
                    entries.append(
                        make_entry(
                            "Interface",
                            filename,
                            original_line(start + token.start, 1),
                            original,
                            context="SDK · strings",
                            start=start + token.start,
                            end=start + token.end,
                            fragment=token.raw,
                            template_file=filename,
                            identifier="strings",
                        )
                    )
                    original = None
        else:
            for entry in extract_renpy(block, filename):
                entry.start += start
                entry.end += start
                entry.line = original_line(start, entry.line)
                entry.context = f"SDK · {identifier}"
                entry.template_file = filename
                entry.identifier = identifier
                entry.id = make_entry(
                    entry.kind,
                    filename,
                    entry.line,
                    entry.source,
                    start=entry.start,
                ).id
                entries.append(entry)
    return entries
