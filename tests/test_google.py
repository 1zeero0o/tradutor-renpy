import io
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtCore import Qt

from renpy_translator.google import TranslationError, translate_google
from renpy_translator.gui import GoogleWorker, MainWindow
from renpy_translator.model import Project, make_entry


def test_google_request_protects_variables_and_tags(monkeypatch):
    def response(request, timeout):
        assert urlsplit(request.full_url).hostname == "translate.googleapis.com"
        query = parse_qs(urlsplit(request.full_url).query)
        assert query["tl"] == ["pt"] and query["sl"] == ["auto"]
        assert "[name]" not in query["q"][0] and "{b}" not in query["q"][0]
        value = query["q"][0].replace("Hello", "Olá")
        return io.BytesIO(json.dumps([[[value, "source"]]]).encode())

    monkeypatch.setattr("renpy_translator.google.urlopen", response)
    assert translate_google("Hello [name] {b}world{/b}", "pt") == "Olá [name] {b}world{/b}"


def test_google_lost_placeholder_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "renpy_translator.google.urlopen", lambda *_args, **_kwargs: io.BytesIO(b'[[["Ola"]]]')
    )
    with pytest.raises(TranslationError, match="variável/tag"):
        translate_google("Hello [name]", "pt")


def test_google_http_error_is_actionable(monkeypatch):
    def response(*_args, **_kwargs):
        raise HTTPError("https://translate.googleapis.com", 429, "rate limited", {}, None)

    monkeypatch.setattr("renpy_translator.google.urlopen", response)
    with pytest.raises(TranslationError, match="HTTP 429"):
        translate_google("Hello", "pt")


def test_marking_never_exceeds_25_and_survives_filters(qtbot, tmp_path):
    entries = [make_entry("Diálogo", "script.rpy", line, f"Text {line}") for line in range(26)]
    project = Project("Game", str(tmp_path / "Game.exe"), entries=entries)
    window = MainWindow()
    qtbot.addWidget(window)
    window.load_project(project)
    window.model.limit_reached.disconnect()
    for row in range(25):
        assert window.model.setData(
            window.model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
        )
    assert not window.model.setData(
        window.model.index(25, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
    )
    assert len(window.model.marked_ids) == 25
    window.search.setText("Text 25")
    assert window.proxy.rowCount() == 1
    assert len(window.model.marked_ids) == 25
    window.clear_marks()
    assert not window.model.marked_ids
    assert not window.actions["google"].isEnabled()


def test_google_worker_translates_sequentially_and_stops_on_error(qtbot, monkeypatch):
    calls = []

    def translate(source, target):
        calls.append(source)
        if source == "Text 2":
            raise TranslationError("Service unavailable")
        return "Translation " + source

    monkeypatch.setattr("renpy_translator.gui.translate_google", translate)
    entries = [make_entry("Diálogo", "script.rpy", line, f"Text {line}") for line in range(4)]
    worker = GoogleWorker(entries, "pt")
    results = []
    worker.translated.connect(lambda identifier, text: results.append((identifier, text)))
    with qtbot.waitSignal(worker.completed, timeout=5000) as finished:
        worker.start()
    assert worker.wait(5000)
    assert calls == ["Text 0", "Text 1", "Text 2"]
    assert len(results) == 2 and finished.args == [2, 1]


def test_google_worker_refuses_oversize_batch():
    entries = [make_entry("Diálogo", "script.rpy", line, "Text") for line in range(26)]
    with pytest.raises(ValueError, match="1 a 25"):
        GoogleWorker(entries, "pt")
