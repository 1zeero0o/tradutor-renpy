import csv
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .paths import relative_path

MARKERS = re.compile(
    r"(?<!\[)\[(?!\[)[^\[\]\n]+\]|(?<!\{)\{(?!\{)[^{}\n]+\}"
    r"|%(?:\([\w]+\))?[-+#0 ]*\d*(?:\.\d+)?[sdifFeEgGuxXoc]"
)
LANGUAGE = re.compile(r"[a-z][a-z0-9_]*\Z")


@dataclass
class Entry:
    id: str
    kind: str
    file: str
    line: int
    source: str
    context: str = ""
    translation: str = ""
    reviewed: bool = False
    start: int = 0
    end: int = 0
    fragment: str = ""

    @property
    def issues(self) -> list[str]:
        if not self.translation:
            return []
        original = Counter(MARKERS.findall(self.source))
        translated = Counter(MARKERS.findall(self.translation))
        issues = []
        for marker, count in (original - translated).items():
            issues.append(f"Falta preservar {marker} ({count}×)")
        for marker, count in (translated - original).items():
            issues.append(f"Marcador adicional {marker} ({count}×)")
        return issues

    @property
    def status(self) -> str:
        if not self.translation:
            return "Pendente"
        if self.issues:
            return "Verificar tags"
        return "Revisado" if self.reviewed else "Traduzido"

    def update(self, translation: str, reviewed: bool = False) -> None:
        self.translation = translation
        self.reviewed = bool(reviewed and translation and not self.issues)


def make_entry(kind: str, file: str, line: int, source: str, **kwargs) -> Entry:
    fingerprint = f"{kind}\0{file}\0{kwargs.get('start', line)}\0{source}"
    identifier = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
    return Entry(identifier, kind, file, line, source, **kwargs)


@dataclass
class Project:
    game_name: str
    executable: str
    language: str = "portuguese_br"
    entries: list[Entry] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    path: Path | None = field(default=None, repr=False)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "total": len(self.entries),
            "translated": sum(bool(e.translation) for e in self.entries),
            "reviewed": sum(e.status == "Revisado" for e in self.entries),
        }

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        if target is None:
            raise ValueError("Escolha um arquivo para salvar o projeto.")
        if not LANGUAGE.fullmatch(self.language):
            raise ValueError("Idioma deve começar com uma letra e usar a–z, 0–9 e sublinhado.")
        payload = {
            "format": "renpy-translator",
            "version": 1,
            "game_name": self.game_name,
            "executable": self.executable,
            "language": self.language,
            "entries": [asdict(e) for e in self.entries],
            "sources": self.sources,
            "warnings": self.warnings,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp"
            ) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, target)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        self.path = target

    @classmethod
    def load(cls, path: Path) -> "Project":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != "renpy-translator" or data.get("version") != 1:
            raise ValueError("Formato de projeto desconhecido.")
        entries = [Entry(**row) for row in data["entries"]]
        if len({e.id for e in entries}) != len(entries):
            raise ValueError("Projeto contém identificadores duplicados.")
        for entry in entries:
            relative_path(entry.file)
            if not isinstance(entry.source, str) or not isinstance(entry.translation, str):
                raise ValueError("Texto inválido no projeto.")
            entry.update(entry.translation, entry.reviewed)
        sources = data["sources"]
        for name, content in sources.items():
            relative_path(name)
            if not isinstance(content, str):
                raise ValueError("Conteúdo de arquivo inválido no projeto.")
        project = cls(
            data["game_name"],
            data["executable"],
            data["language"],
            entries,
            sources,
            data.get("warnings", []),
            path,
        )
        if not LANGUAGE.fullmatch(project.language):
            raise ValueError("Identificador de idioma inválido no projeto.")
        return project


CSV_FIELDS = ["id", "tipo", "arquivo", "linha", "contexto", "original", "traducao", "revisado"]


def export_csv(project: Project, path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for entry in project.entries:
            writer.writerow(
                dict(
                    zip(
                        CSV_FIELDS,
                        (
                            entry.id,
                            entry.kind,
                            entry.file,
                            entry.line,
                            entry.context,
                            entry.source,
                            entry.translation,
                            "sim" if entry.reviewed else "nao",
                        ),
                        strict=True,
                    )
                )
            )


def import_csv(project: Project, path: Path) -> int:
    indexed = {entry.id: entry for entry in project.entries}
    updates = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"id", "original", "traducao"} <= set(reader.fieldnames):
            raise ValueError("CSV deve conter as colunas id, original e traducao.")
        for number, row in enumerate(reader, 2):
            entry = indexed.get(row["id"])
            if entry is None or entry.source != row["original"]:
                raise ValueError(f"Linha {number}: ID ou texto original não pertence ao projeto.")
            if row["id"] in seen or row["traducao"] is None:
                raise ValueError(f"Linha {number}: linha duplicada ou tradução ausente.")
            seen.add(row["id"])
            updates.append((entry, row["traducao"], row.get("revisado", "").lower() == "sim"))
    # Validate the complete file before applying anything.
    for entry, translation, reviewed in updates:
        entry.update(translation, reviewed)
    return len(updates)
