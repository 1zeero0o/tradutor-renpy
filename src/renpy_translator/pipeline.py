import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from .archive import copy_loose_file, extract_archive
from .extractors import decompile_script, extract_renpy, extract_yaml
from .model import LANGUAGE, Project, export_csv
from .paths import contained_path
from .sdk import extract_template, find_sdk, generate_templates

SOURCE_EXTENSIONS = {".rpy", ".rpyc", ".rpcy", ".rpym", ".rpymc", ".yml", ".yaml"}


def create_project(
    executable: Path,
    destination: Path,
    language: str = "portuguese_br",
    progress: Callable[[str], None] = lambda _: None,
    *,
    sdk_path: Path | None = None,
    include_yaml: bool = False,
) -> Project:
    executable = executable.resolve()
    destination = destination.resolve()
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise ValueError("Selecione o arquivo .exe do jogo Ren'Py.")
    game = executable.parent / "game"
    if not game.is_dir():
        raise ValueError("A pasta game não foi encontrada ao lado do executável.")
    if not LANGUAGE.fullmatch(language):
        raise ValueError("Identificador de idioma inválido. Exemplo: portuguese_br.")
    if destination.is_relative_to(executable.parent) or destination.is_relative_to(game.resolve()):
        raise ValueError("Escolha uma pasta de projeto fora da pasta do jogo.")
    if destination.exists():
        raise ValueError("A pasta de projeto já existe. Escolha uma pasta nova.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".renpy-extract-", dir=destination.parent) as folder:
        root = Path(folder)
        extracted = root / "extraidos"
        extracted.mkdir()
        project = Project(executable.stem, str(executable), language, include_yaml=include_yaml)
        occupied = set()
        for archive in sorted(game.rglob("*")):
            if archive.suffix.lower() != ".rpa" or not archive.is_file():
                continue
            if archive.is_symlink() or not archive.resolve().is_relative_to(game.resolve()):
                raise ValueError(f"Arquivo fora da pasta game: {archive.name}")
            base = archive.parent.relative_to(game)
            names = extract_archive(archive, extracted / base, progress)
            for name in names:
                relative = (base / Path(name.replace("\\", "/"))).as_posix()
                if relative in occupied:
                    project.warnings.append(
                        f"Arquivo repetido em arquivos RPA: {relative}. Usada a última cópia "
                        "em ordem alfabética; confira a prioridade dos arquivos do jogo."
                    )
                occupied.add(relative)
        for loose in sorted(game.rglob("*")):
            if not loose.is_file() or loose.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            relative = loose.relative_to(game).as_posix()
            if loose.is_symlink() or not loose.resolve().is_relative_to(game.resolve()):
                raise ValueError(f"Arquivo fora da pasta game: {relative}")
            progress(f"Copiando {relative}")
            copy_loose_file(loose, contained_path(extracted, relative))
        compiled_count = 0
        for compiled in sorted(extracted.rglob("*")):
            if compiled.suffix.lower() not in {".rpyc", ".rpcy", ".rpymc"}:
                continue
            relative = compiled.relative_to(extracted)
            if any(part.lower() in {"tl", "cache", "saves"} for part in relative.parts[:-1]):
                continue
            compiled_count += 1
            source = compiled.with_suffix(
                ".rpym" if compiled.suffix.lower() == ".rpymc" else ".rpy"
            )
            if source.exists() and source.stat().st_size:
                continue
            progress(f"Descompilando {relative.as_posix()}")
            try:
                text, log = decompile_script(compiled)
                source.write_text(text, encoding="utf-8")
                project.warnings.extend(f"{relative}: {message}" for message in log)
            except Exception as exc:
                project.warnings.append(f"Não foi possível descompilar {relative}: {exc}")
        scripts = []
        for source in sorted(extracted.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in {
                ".rpy",
                ".rpym",
                ".yml",
                ".yaml",
            }:
                continue
            relative = source.relative_to(extracted).as_posix()
            if any(
                part.lower() in {"tl", "cache", "saves"}
                for part in source.relative_to(extracted).parts[:-1]
            ):
                continue
            progress(f"Lendo textos de {relative}")
            try:
                text = source.read_text(encoding="utf-8-sig")
                is_yaml = source.suffix.lower() in {".yml", ".yaml"}
                if is_yaml and include_yaml:
                    project.sources[relative] = text
                    project.entries.extend(extract_yaml(text, relative))
                elif not is_yaml:
                    scripts.append(source)
                    project.sources[relative] = text
            except Exception as exc:
                project.warnings.append(f"Não foi possível ler {relative}: {exc}")
        if scripts:
            sdk_path = sdk_path or find_sdk()
            if sdk_path is None:
                raise ValueError(
                    "Selecione o SDK oficial do Ren'Py para gerar os diálogos. "
                    "Na CLI, use --sdk ou a variável RENPY_SDK."
                )
            progress(f"Gerando traduções de {len(scripts)} roteiros com o SDK Ren'Py…")
            templates, log, version = generate_templates(extracted, scripts, language, sdk_path)
            project.templates = templates
            project.sdk_version = version
            project.warnings.extend(log)
            for filename, template in templates.items():
                entries = extract_template(template, filename)
                menu_strings = {
                    entry.source
                    for entry in extract_renpy(project.sources.get(filename, ""), filename)
                    if entry.kind == "Menu"
                }
                for entry in entries:
                    # SDK menu locations can point to the end of the option block.
                    # Use source text only for the UI category; SDK owns generation/IDs.
                    if entry.identifier == "strings" and entry.source in menu_strings:
                        entry.kind = "Menu"
                project.entries.extend(entries)
        renpy_count = sum(entry.kind != "YAML" for entry in project.entries)
        if (compiled_count or scripts) and not renpy_count:
            raise ValueError(
                "O jogo contém roteiros Ren'Py, mas nenhum diálogo/texto foi gerado. "
                "Não foi criado um projeto contendo apenas YAML.\n"
                + "\n".join(project.warnings[:10])
            )
        progress(
            f"Textos encontrados: {renpy_count} Ren'Py; {len(project.entries) - renpy_count} YAML."
        )
        if not project.entries:
            details = "\n".join(project.warnings[:10])
            raise ValueError("Nenhum texto traduzível foi encontrado no jogo.\n" + details)
        project.save(root / "projeto.json")
        export_csv(project, root / "traducoes.csv")
        # Move only after the complete project is valid; never change the game's files.
        if destination.exists():
            raise ValueError("A pasta de destino foi criada durante a extração; escolha outra.")
        shutil.move(str(root), str(destination))
        project.path = destination / "projeto.json"
    progress(f"Projeto criado: {len(project.entries)} textos.")
    return project
