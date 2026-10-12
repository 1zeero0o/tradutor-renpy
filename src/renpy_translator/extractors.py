import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import warnings
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, ScalarNode, SequenceNode
from ruamel.yaml.tokens import ScalarToken

from .model import Entry, make_entry


@dataclass
class StringToken:
    start: int
    end: int
    raw: str


def string_tokens(text: str):
    """Find literals while skipping comments, including multiline/escaped literals."""
    position = 0
    while position < len(text):
        if text[position] == "#":
            newline = text.find("\n", position)
            position = len(text) if newline < 0 else newline + 1
        elif text[position] in "\"'`":
            start = position
            quote = text[position]
            if (
                position
                and text[position - 1] == "r"
                and (
                    position < 2 or not (text[position - 2].isalnum() or text[position - 2] == "_")
                )
            ):
                start -= 1
            delimiter = quote * 3 if text.startswith(quote * 3, position) else quote
            position += len(delimiter)
            while position < len(text):
                if text[position] == "\\":
                    position += 2
                elif text.startswith(delimiter, position):
                    position += len(delimiter)
                    yield StringToken(start, position, text[start:position])
                    break
                else:
                    position += 1
        else:
            position += 1


NON_DIALOGUE = {
    "scene",
    "show",
    "hide",
    "play",
    "queue",
    "stop",
    "voice",
    "image",
    "define",
    "default",
    "label",
    "jump",
    "call",
    "return",
    "python",
    "init",
    "transform",
    "style",
    "screen",
    "add",
    "use",
    "key",
    "timer",
    "window",
    "if",
    "elif",
    "while",
    "old",
    "new",
    "translate",
    "font",
    "sound",
    "music",
    "on",
    "with",
    "pause",
    "import",
    "from",
    "raise",
    "assert",
    "print",
    "pass",
    "del",
    "yield",
}
WRAPPED = re.compile(r"(?:\b_+|\bCharacter|\brenpy\.input)\s*\(\s*\Z")
SPEAKER = re.compile(r"[\w.]+(?:\s+[-\w]+)*\s*\Z", re.UNICODE)


def renpy_literal(raw: str) -> str:
    is_raw = raw.startswith("r")
    if is_raw:
        raw = raw[1:]
    value = raw[1:-1]
    if is_raw:
        return value
    value = re.sub(r"[ \n]+", " ", value)

    def unescape(match):
        char = match[1]
        if char in {"{", "[", "%"}:
            return char * 2
        if char == "n":
            return "\n"
        if char.startswith("u") and len(char) > 1:
            return chr(int(char[1:], 16))
        return char

    return re.sub(r"\\(u[0-9a-fA-F]{1,4}|.)", unescape, value)


def extract_renpy(text: str, filename: str) -> list[Entry]:
    entries = []
    label = ""
    lines = text.splitlines()
    line_starts = [0] + [index + 1 for index, char in enumerate(text) if char == "\n"]
    label_at_line = {}
    python_indent = None
    python_lines = set()
    for number, line in enumerate(lines, 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped and not stripped.startswith("#"):
            if python_indent is not None and indent <= python_indent:
                python_indent = None
            if python_indent is not None:
                python_lines.add(number)
            if re.match(r"(?:init\s+(?:-?\d+\s+)?)?python(?:\s+\w+)*\s*:", stripped):
                python_indent = indent
        match = re.match(r"\s*label\s+([\w.]+)", line)
        if match:
            label = match[1]
        label_at_line[number] = label
    for token in string_tokens(text):
        number = bisect_right(line_starts, token.start)
        line_start = line_starts[number - 1]
        prefix = text[line_start : token.start]
        stripped = prefix.strip()
        wrapped = WRAPPED.search(prefix)
        if wrapped:
            kind = "Interface"
        elif number in python_lines:
            continue
        elif not stripped:
            if token.raw.startswith(('"""', "'''")):
                continue
            line_end = text.find("\n", token.end)
            tail = text[token.end : line_end if line_end >= 0 else None]
            kind = "Menu" if tail.split("#", 1)[0].rstrip().endswith(":") else "Diálogo"
        elif stripped in {"text", "textbutton", "tooltip", "prompt", "label"}:
            kind = "Interface"
        elif SPEAKER.fullmatch(stripped) and stripped.split()[0] not in NON_DIALOGUE:
            kind = "Diálogo"
        else:
            continue
        try:
            if kind in {"Diálogo", "Menu"}:
                if token.raw.lstrip("r").startswith(('"""', "'''")):
                    continue
                value = renpy_literal(token.raw)
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    value = ast.literal_eval(token.raw)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        context = label_at_line.get(number, "")
        if kind == "Diálogo" and stripped:
            context = f"{context} · {stripped}".strip(" ·")
        entries.append(
            make_entry(
                kind,
                filename,
                number,
                value,
                context=context,
                start=token.start,
                end=token.end,
                fragment=token.raw,
            )
        )
    return entries


def extract_yaml(text: str, filename: str) -> list[Entry]:
    yaml = YAML(typ="safe", pure=True)
    entries = []
    seen = set()
    # Scalar nodes include anchors/tags in their span; scalar tokens do not.
    # Keeping those prefixes intact lets aliases keep referring to the same value.
    tokens = {
        token.end_mark.index: token for token in yaml.scan(text) if isinstance(token, ScalarToken)
    }

    def walk(node, context: str, ancestry: frozenset):
        if id(node) in ancestry:
            return
        ancestry = ancestry | {id(node)}
        if isinstance(node, ScalarNode):
            if node.tag != "tag:yaml.org,2002:str" or not node.value.strip():
                return
            token = tokens[node.end_mark.index]
            span = (token.start_mark.index, token.end_mark.index)
            # An alias shares its anchor's node; edit the anchor once.
            if span in seen:
                return
            seen.add(span)
            entries.append(
                make_entry(
                    "YAML",
                    filename,
                    node.start_mark.line + 1,
                    node.value,
                    context=context,
                    start=span[0],
                    end=span[1],
                    fragment=text[span[0] : span[1]],
                )
            )
        elif isinstance(node, SequenceNode):
            for index, child in enumerate(node.value):
                walk(child, f"{context}[{index}]", ancestry)
        elif isinstance(node, MappingNode):
            for key, value in node.value:
                name = key.value if isinstance(key, ScalarNode) else "<chave composta>"
                walk(value, f"{context}.{name}", ancestry)

    for index, document in enumerate(yaml.compose_all(text)):
        if document is not None:
            walk(document, f"documento[{index}]", frozenset())
    return entries


def decompile_script(path: Path) -> tuple[str, list[str]]:
    """Keep unrpyc's fake Ren'Py modules isolated from Qt's import hooks."""
    with tempfile.TemporaryDirectory(prefix="renpy-decompile-") as folder:
        output = Path(folder) / "result.json"
        args = [sys.executable]
        if getattr(sys, "frozen", False):
            name = "RenpyDecompiler.exe" if os.name == "nt" else "RenpyDecompiler"
            worker = Path(sys.executable).parent / "worker" / "RenpyDecompiler" / name
            if not worker.is_file():
                raise ValueError(
                    "Descompilador não encontrado. Distribua a pasta completa do aplicativo."
                )
            args = [str(worker), str(path), str(output)]
        else:
            args += ["-m", "renpy_translator.compiled", str(path), str(output)]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        if result.returncode:
            raise ValueError(
                payload.get("error")
                or result.stderr.strip()
                or "Falha no processo de descompilação."
            )
        return payload["text"], payload["warnings"]
