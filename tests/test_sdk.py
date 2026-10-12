from pathlib import Path

import pytest

from renpy_translator.exporter import export_game
from renpy_translator.model import Project
from renpy_translator.pipeline import create_project
from renpy_translator.sdk import extract_template, generate_templates


def test_native_dialogue_repeated_text_can_have_different_translations(tmp_path, sdk_path):
    game = tmp_path / "sources"
    game.mkdir()
    script = game / "script.rpy"
    script.write_text("""init python:
    raise RuntimeError("Original init must not execute")
label first:
    e happy "Hello [name]" nointeract
    extend "...again"
label second:
    e "Hello [name]"
    return
""")
    templates, warnings, version = generate_templates(game, [script], "portuguese_br", sdk_path)
    assert not warnings
    assert "Ren'Py" in version
    entries = extract_template(templates["script.rpy"], "script.rpy")
    same = [entry for entry in entries if entry.source == "Hello [name]"]
    assert len(same) == 2 and same[0].identifier != same[1].identifier
    same[0].update("Olá [name]", True)
    same[1].update("Oi [name]", True)
    project = Project("Game", str(tmp_path / "Game/Game.exe"), entries=entries, templates=templates)
    output = export_game(project, tmp_path / "out", reviewed_only=True)
    result = (output / "game/tl/portuguese_br/script.rpy").read_text()
    assert 'e happy "Olá [name]" nointeract' in result
    assert 'e "Oi [name]"' in result
    assert 'extend "...again"' not in result
    assert "Original init" not in result


@pytest.mark.parametrize("extension", [".rpyc", ".rpcy"])
def test_compiled_alias_and_yaml_choice(tmp_path, sdk_path, extension):
    game = tmp_path / "Game/game"
    game.mkdir(parents=True)
    exe = game.parent / "Game.exe"
    exe.touch()
    fixture = Path(__file__).parent / "fixtures/the_question-8.2.rpyc"
    (game / f"script{extension}").write_bytes(fixture.read_bytes())
    (game / "strings.yml").write_text("name: Hello\ndescription: Description\nid: ignored\n")
    project = create_project(exe, tmp_path / "project", sdk_path=sdk_path, include_yaml=False)
    assert len(project.entries) == 77
    assert all(entry.kind != "YAML" and entry.identifier for entry in project.entries)
    assert (tmp_path / "project/extraidos/script.rpy").is_file()
    assert project.sdk_version and project.templates


def test_sdk_missing_has_actionable_error(tmp_path, monkeypatch):
    monkeypatch.delenv("RENPY_SDK", raising=False)
    game = tmp_path / "Game/game"
    game.mkdir(parents=True)
    exe = game.parent / "Game.exe"
    exe.touch()
    (game / "script.rpy").write_text('label start:\n    "Hello"\n    return\n')
    with pytest.raises(ValueError, match="SDK oficial"):
        create_project(exe, tmp_path / "project")


def test_sdk_does_not_mix_existing_target_language_files(tmp_path, sdk_path):
    game = tmp_path / "game"
    locale = game / "tl/portuguese_br"
    locale.mkdir(parents=True)
    existing = locale / "script.rpy"
    existing.write_text('translate portuguese_br old_dialogue:\n    e "Existing translation"\n')
    previous = existing.read_bytes()
    script = game / "script.rpy"
    script.write_text('label start:\n    e "Original dialogue"\n    return\n')
    templates, warnings, _version = generate_templates(game, [script], "portuguese_br", sdk_path)
    assert not warnings
    assert "Existing translation" not in templates["script.rpy"]
    assert "Original dialogue" in templates["script.rpy"]
    assert existing.read_bytes() == previous
