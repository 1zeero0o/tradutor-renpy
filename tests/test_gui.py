from PySide6.QtCore import Qt

from renpy_translator.gui import ExtractionWorker, MainWindow
from renpy_translator.model import Project, make_entry


def test_edit_review_filter_save_and_reopen(qtbot, tmp_path):
    entries = [
        make_entry("Diálogo", "script.rpy", 1, "Hello [name]"),
        make_entry("YAML", "strings.yml", 3, "Welcome"),
    ]
    project = Project("Example", str(tmp_path / "Game/Game.exe"), entries=entries)
    project.save(tmp_path / "projeto.json")
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.load_project(project)
    assert window.original.toPlainText() == "Hello [name]"
    window.translation.setPlainText("Olá")
    assert not window.review_button.isEnabled()
    assert "[name]" in window.validation.text()
    window.translation.setPlainText("Olá [name]")
    qtbot.mouseClick(window.review_button, Qt.MouseButton.LeftButton)
    assert entries[0].reviewed
    assert window.original.toPlainText() == "Welcome"
    window.translation.setPlainText("Bem-vindo")
    window.kind_filter.setCurrentText("YAML")
    assert window.proxy.rowCount() == 1
    window.search.setText("bem")
    assert window.proxy.rowCount() == 1
    assert window.save_project()
    restored = Project.load(project.path)
    assert restored.entries[0].translation == "Olá [name]"
    assert restored.entries[0].reviewed
    assert restored.entries[1].translation == "Bem-vindo"
    assert not window.dirty
    window.close()


def test_background_extraction_worker(qtbot, tmp_path, make_rpa):
    game = tmp_path / "Game/game"
    game.mkdir(parents=True)
    executable = game.parent / "Game.exe"
    executable.touch()
    make_rpa(game / "data.rpa", {"texts.yml": b"title: Hello\n"})
    worker = ExtractionWorker(executable, tmp_path / "project", "portuguese_br")
    with qtbot.waitSignal(worker.succeeded, timeout=10000) as signal:
        worker.start()
    assert worker.wait(10000)
    assert len(signal.args[0].entries) == 1
