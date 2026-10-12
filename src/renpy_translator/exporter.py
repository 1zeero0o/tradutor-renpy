import json
import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

from .model import LANGUAGE, Entry, Project, export_csv
from .paths import contained_path


def quote(text: str) -> str:
    # Ren'Py collapses literal spaces before expanding escapes and does not
    # interpret Python's \\t/\\r. Encode controls and repeated spaces explicitly.
    pieces = []
    for index, char in enumerate(text):
        if char in {'"', "\\"}:
            pieces.append("\\" + char)
        elif char == "\n":
            pieces.append("\\n")
        elif ord(char) < 32:
            pieces.append(f"\\u{ord(char):04x}")
        elif char == " " and (
            (index > 0 and text[index - 1] == " ")
            or (index + 1 < len(text) and text[index + 1] == " ")
        ):
            pieces.append("\\ ")
        else:
            pieces.append(char)
    return '"' + "".join(pieces) + '"'


def translated_yaml(source: str, entries: list[Entry]) -> str:
    result = source
    boundary = len(source)
    for entry in sorted(entries, key=lambda e: e.start, reverse=True):
        if (
            not 0 <= entry.start < entry.end <= boundary
            or source[entry.start : entry.end] != entry.fragment
        ):
            raise ValueError(f"Posição de texto YAML inválida: {entry.file}:{entry.line}")
        boundary = entry.start
        replacement = json.dumps(entry.translation, ensure_ascii=False)
        # A block scalar owns the final newline, unlike an inline scalar.
        if entry.fragment.endswith("\n"):
            comment = re.match(r"[|>][^\n#]*?(#[^\n]*)", entry.fragment)
            if comment:
                replacement += " " + comment[1]
            replacement += "\n"
        result = result[: entry.start] + replacement + result[entry.end :]
    return result


def export_game(
    project: Project,
    destination: Path,
    reviewed_only: bool = False,
    activate: bool = True,
) -> Path:
    if not LANGUAGE.fullmatch(project.language):
        raise ValueError("Identificador de idioma inválido.")
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("A pasta de exportação já existe. Escolha uma pasta nova.")
    game_root = Path(project.executable).resolve().parent
    if destination.is_relative_to(game_root):
        raise ValueError("Exporte para uma pasta fora do jogo; instale a tradução depois.")
    selected = [
        entry
        for entry in project.entries
        if entry.translation and (not reviewed_only or entry.status == "Revisado")
    ]
    if not selected:
        raise ValueError("Não há traduções para exportar com o filtro escolhido.")
    invalid = [entry for entry in selected if entry.issues]
    if invalid:
        first = invalid[0]
        raise ValueError(f"Corrija as tags em {first.file}:{first.line}: {'; '.join(first.issues)}")
    strings = {}
    yaml_entries = defaultdict(list)
    for entry in selected:
        if entry.kind == "YAML":
            yaml_entries[entry.file].append(entry)
            continue
        previous = strings.get(entry.source)
        if previous and previous.translation != entry.translation:
            raise ValueError(
                f"O texto {entry.source!r} tem traduções diferentes. "
                "Textos Ren'Py iguais devem usar a mesma tradução nesta versão."
            )
        strings[entry.source] = entry
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".renpy-export-", dir=destination.parent) as folder:
        root = Path(folder)
        game = root / "game"
        tl = game / "tl" / project.language
        tl.mkdir(parents=True)
        if strings:
            lines = [
                "# Gerado pelo Tradutor Ren'Py. Textos pendentes mantêm o original.",
                f"translate {project.language} strings:",
            ]
            for entry in strings.values():
                lines.extend(
                    [
                        "",
                        f"    # {entry.file.replace(chr(10), ' ')}:{entry.line}",
                        f"    old {quote(entry.source)}",
                        f"    new {quote(entry.translation)}",
                    ]
                )
            (tl / "renpy_translator_strings.rpy").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
            if activate:
                # Ren'Py's native string substitutions already translate dialogue.
                # A say_menu_text_filter would translate twice (A→B→C).
                bridge = (
                    "# Gerado pelo Tradutor Ren'Py: idioma inicial da tradução.\n"
                    "init 999 python:\n"
                    f"    config.language = {quote(project.language)}\n"
                )
                (game / "renpy_translator_runtime.rpy").write_text(bridge, encoding="utf-8")
        for filename, entries in yaml_entries.items():
            if filename not in project.sources:
                raise ValueError(f"O projeto não contém o arquivo original {filename}.")
            target = contained_path(game, filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(translated_yaml(project.sources[filename], entries), encoding="utf-8")
        export_csv(project, root / "traducoes.csv")
        (root / "LEIA-ME.txt").write_text(
            f"Tradução de {project.game_name} · idioma {project.language}\n\n"
            "Feche o jogo. Faça backup da pasta game antes de instalar.\n"
            "Copie o conteúdo da pasta game desta exportação para a pasta game do jogo.\n"
            "Os arquivos YAML exportados substituem apenas os arquivos de mesmo nome.\n"
            "Textos pendentes continuam no idioma original.\n"
            "O catálogo Ren'Py aplica a mesma tradução a todas as ocorrências de um texto.\n"
            "Se já existir uma tradução deste idioma, verifique conflitos de old/new.\n"
            + (
                "O idioma será ativado na próxima inicialização.\n"
                if activate and strings
                else f"Selecione o idioma {project.language} nas opções do jogo.\n"
            ),
            encoding="utf-8",
        )
        if destination.exists():
            raise ValueError("A pasta de destino foi criada durante a exportação; escolha outra.")
        shutil.move(str(root), str(destination))
    return destination
