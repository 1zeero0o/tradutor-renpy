import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from .archive import copy_loose_file, extract_archive
from .extractors import decompile_script, extract_renpy, extract_yaml
from .model import LANGUAGE, Project, export_csv
from .paths import contained_path

SOURCE_EXTENSIONS = {".rpy", ".rpyc", ".rpym", ".rpymc", ".yml", ".yaml"}


def create_project(
    executable: Path,
    destination: Path,
    language: str = "portuguese_br",
    progress: Callable[[str], None] = lambda _: None,
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
        project = Project(executable.stem, str(executable), language)
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
        for compiled in sorted(extracted.rglob("*")):
            if compiled.suffix.lower() not in {".rpyc", ".rpymc"}:
                continue
            relative = compiled.relative_to(extracted)
            if any(part.lower() in {"tl", "cache", "saves"} for part in relative.parts[:-1]):
                continue
            source = compiled.with_suffix(".rpy" if compiled.suffix.lower() == ".rpyc" else ".rpym")
            if source.exists():
                continue
            progress(f"Descompilando {relative.as_posix()}")
            try:
                text, log = decompile_script(compiled)
                source.write_text(text, encoding="utf-8")
                project.warnings.extend(f"{relative}: {message}" for message in log)
            except Exception as exc:
                project.warnings.append(f"Não foi possível descompilar {relative}: {exc}")
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
                parser = (
                    extract_yaml if source.suffix.lower() in {".yml", ".yaml"} else extract_renpy
                )
                entries = parser(text, relative)
                project.sources[relative] = text
                project.entries.extend(entries)
            except Exception as exc:
                project.warnings.append(f"Não foi possível ler {relative}: {exc}")
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
