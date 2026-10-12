import csv

import pytest

from renpy_translator.model import Project, export_csv, import_csv, make_entry


def test_review_requires_preserved_markers():
    entry = make_entry("Diálogo", "script.rpy", 1, "Hello [name]! {b}Score: %(score)d{/b}")
    entry.update("Olá! Pontuação", reviewed=True)
    assert entry.status == "Verificar tags"
    assert not entry.reviewed
    entry.update("Olá [name]! {b}Pontuação: %(score)d{/b}", reviewed=True)
    assert entry.status == "Revisado"
    entry.update("Oi [name]! {b}Pontuação: %(score)d{/b}")
    assert entry.status == "Traduzido"


def test_csv_and_project_roundtrip_with_multiline(tmp_path):
    entry = make_entry("YAML", "strings.yml", 2, 'Hello, "friend"\nNext line')
    entry.update('Olá, "amigo"\nPróxima linha', reviewed=True)
    project = Project("Game", "/game/Game.exe", entries=[entry])
    path = tmp_path / "project.json"
    project.save(path)
    restored = Project.load(path)
    csv_path = tmp_path / "texts.csv"
    export_csv(project, csv_path)
    restored.entries[0].update("")
    assert import_csv(restored, csv_path) == 1
    assert restored.entries[0].translation == entry.translation
    assert restored.entries[0].reviewed
    assert restored.path == path


def test_csv_import_is_atomic_on_wrong_original(tmp_path):
    first = make_entry("Diálogo", "script.rpy", 1, "Hello")
    second = make_entry("Diálogo", "script.rpy", 2, "World")
    project = Project("Game", "/game/Game.exe", entries=[first, second])
    path = tmp_path / "texts.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "original", "traducao"])
        writer.writeheader()
        writer.writerow({"id": first.id, "original": "Hello", "traducao": "Olá"})
        writer.writerow({"id": second.id, "original": "Incorrect", "traducao": "Mundo"})
    with pytest.raises(ValueError, match="original"):
        import_csv(project, path)
    assert first.translation == second.translation == ""
