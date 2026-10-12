from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from renpy_translator.gui import MainWindow
from renpy_translator.model import Project, make_entry


@pytest.mark.parametrize("include_yaml", [True, False])
def test_game_selection_asks_yaml_before_extraction(
    qtbot, monkeypatch, tmp_path, sdk_path, include_yaml
):
    game = tmp_path / "Game/game"
    game.mkdir(parents=True)
    exe = game.parent / "Game.exe"
    exe.touch()
    (game / "script.rpyc").write_bytes(
        (Path(__file__).parent / "fixtures/the_question-8.2.rpyc").read_bytes()
    )
    (game / "strings.yml").write_text("name: Hello\ndescription: Description\nignored: Ignore me\n")
    window = MainWindow()
    qtbot.addWidget(window)
    window.sdk_path = sdk_path
    errors = []
    monkeypatch.setattr(window, "show_error", lambda error: errors.append(error))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_: (str(exe), ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(tmp_path))
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kw: ("portuguese_br", True))
    questions = []

    def answer(*args):
        assert window.worker is None
        questions.append(args[1])
        return QMessageBox.StandardButton.Yes if include_yaml else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", answer)
    window.select_game()
    qtbot.waitUntil(lambda: window.project is not None or bool(errors), timeout=15000)
    assert window.worker.wait(10000)
    assert not errors
    assert questions == ["Incluir textos YAML?"]
    assert window.project.include_yaml == include_yaml
    assert sum(entry.kind == "YAML" for entry in window.project.entries) == (
        2 if include_yaml else 0
    )
    assert any(entry.kind == "Diálogo" for entry in window.project.entries)


def test_google_ui_applies_only_marked_strings_and_leaves_review_pending(
    qtbot, monkeypatch, tmp_path
):
    entries = [make_entry("Diálogo", "script.rpy", line, f"Text {line}") for line in range(3)]
    entries[2].update("Manual translation", True)
    project = Project("Game", str(tmp_path / "Game.exe"), entries=entries)
    project.save(tmp_path / "project.json")
    window = MainWindow()
    qtbot.addWidget(window)
    window.load_project(project)
    for row in (0, 1):
        window.model.setData(
            window.model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
        )
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kw: ("pt", True))
    calls = []

    def translate(source, target):
        calls.append(source)
        return source.replace("Text", "Texto")

    monkeypatch.setattr("renpy_translator.gui.translate_google", translate)
    window.start_google()
    qtbot.waitUntil(lambda: entries[1].translation != "", timeout=5000)
    qtbot.waitUntil(lambda: not window.google_worker.isRunning(), timeout=5000)
    qtbot.waitUntil(lambda: window.actions["save"].isEnabled(), timeout=5000)
    assert calls == ["Text 0", "Text 1"]
    assert entries[0].translation == "Texto 0" and not entries[0].reviewed
    assert entries[1].translation == "Texto 1" and not entries[1].reviewed
    assert entries[2].translation == "Manual translation" and entries[2].reviewed
    assert not window.model.marked_ids
    assert window.save_project()
    assert Project.load(project.path).entries[0].status == "Traduzido"
