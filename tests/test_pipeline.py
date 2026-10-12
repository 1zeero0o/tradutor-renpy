import csv
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from renpy_translator.exporter import export_game
from renpy_translator.model import Project, import_csv, make_entry
from renpy_translator.pipeline import create_project


def test_exe_rpa_rpyc_yaml_review_import_export(tmp_path, make_rpa, sdk_path):
    game_root = tmp_path / "Game"
    game = game_root / "game"
    game.mkdir(parents=True)
    executable = game_root / "Game.exe"
    executable.write_bytes(b"not executed")
    compiled = (Path(__file__).parent / "fixtures/the_question-8.2.rpyc").read_bytes()
    archive = make_rpa(
        game / "scripts.rpa",
        {
            "script.rpyc": compiled,
            "data/strings.yml": b"name: Hello\nitems: [{name: World, id: Friend}]\ncount: 7\n",
            "images/scene.png": b"fake image",
        },
        prefix_size=5,
    )
    original_archive = archive.read_bytes()
    (game / "loose.yaml").write_text("description: Continue\n", encoding="utf-8")
    project = create_project(executable, tmp_path / "project", sdk_path=sdk_path, include_yaml=True)
    assert len(project.entries) == 80
    assert any(entry.kind == "Menu" for entry in project.entries)
    assert not project.warnings
    assert (tmp_path / "project/extraidos/images/scene.png").read_bytes() == b"fake image"
    assert project.path == tmp_path / "project/projeto.json"
    with (tmp_path / "project/traducoes.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert any(row["tipo"] == "YAML" and row["original"] == "Hello" for row in rows)
    for entry in project.entries:
        if entry.source in {"Hello", "World", "Continue", "Sylvie"}:
            entry.update(
                {"Hello": "Olá", "World": "Mundo", "Continue": "Continuar", "Sylvie": "Sílvia"}[
                    entry.source
                ],
                reviewed=True,
            )
    project.save()
    restored = Project.load(project.path)
    output = export_game(restored, tmp_path / "export", reviewed_only=True)
    exported_yaml = YAML(typ="safe").load((output / "game/data/strings.yml").read_text())
    assert exported_yaml == {
        "name": "Olá",
        "items": [{"name": "Mundo", "id": "Friend"}],
        "count": 7,
    }
    assert YAML(typ="safe").load((output / "game/loose.yaml").read_text()) == {
        "description": "Continuar"
    }
    catalog = (output / "game/tl/portuguese_br/script.rpy").read_text()
    assert 'old "Sylvie"' in catalog and 'new "Sílvia"' in catalog
    assert 'new ""' not in catalog
    assert (
        'config.language = "portuguese_br"'
        in (output / "game/renpy_translator_runtime.rpy").read_text()
    )
    assert "say_menu_text_filter" not in (output / "game/renpy_translator_runtime.rpy").read_text()
    assert import_csv(restored, output / "traducoes.csv") == 80
    assert archive.read_bytes() == original_archive
    assert not (game / "tl").exists()


def test_export_blocks_invalid_tags(tmp_path):
    first = make_entry("Diálogo", "script.rpy", 1, "Hello [name]")
    first.update("Olá")
    project = Project("Game", str(tmp_path / "Game/Game.exe"), entries=[first])
    with pytest.raises(ValueError, match="tags"):
        export_game(project, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_failed_project_does_not_leave_partial_output(tmp_path, make_rpa):
    game = tmp_path / "Game/game"
    game.mkdir(parents=True)
    executable = game.parent / "Game.exe"
    executable.touch()
    make_rpa(game / "bad.rpa", {"../escape.txt": b"unsafe"})
    with pytest.raises(ValueError):
        create_project(executable, tmp_path / "project")
    assert not (tmp_path / "project").exists()
    assert not list(tmp_path.glob(".renpy-extract-*"))


def test_damaged_script_never_silently_creates_yaml_only_project(tmp_path):
    game = tmp_path / "Game/game"
    game.mkdir(parents=True)
    executable = game.parent / "Game.exe"
    executable.touch()
    (game / "script.rpyc").write_bytes(b"corrupt")
    (game / "strings.yml").write_text("name: Hello\n")
    with pytest.raises(ValueError, match="script.rpyc"):
        create_project(executable, tmp_path / "project", include_yaml=True)
    assert not (tmp_path / "project").exists()
