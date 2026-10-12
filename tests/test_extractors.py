from pathlib import Path

from ruamel.yaml import YAML

from renpy_translator.exporter import translated_yaml
from renpy_translator.extractors import decompile_script, extract_renpy, extract_yaml


def test_dialogue_menu_interface_and_comments():
    text = """# "Ignore comment"
define e = Character("Eileen", color="#ffffff")
image bg room = "room.png"
label start:
    scene bg room
    play music "track.ogg"
    e happy "Hello, [player]! {b}Welcome{/b}"
    "Narration with \\"quotes\\"."
    menu:
        "Continue":
            e "Let's go."
    $ prompt = _("Your name?")
    python:
        "Ignore Python docstring"
        resource = "Ignore resource"
        message = _("Translate this")
screen title():
    text "Welcome"
    textbutton _("Start") action Start()
"""
    entries = extract_renpy(text, "script.rpy")
    assert [entry.source for entry in entries] == [
        "Eileen",
        "Hello, [player]! {b}Welcome{/b}",
        'Narration with "quotes".',
        "Continue",
        "Let's go.",
        "Your name?",
        "Translate this",
        "Welcome",
        "Start",
    ]
    assert entries[1].context == "start · e happy"
    assert entries[1].line == 7
    assert entries[3].kind == "Menu"


def test_yaml_documents_aliases_types_and_comments():
    text = """# Keep this comment
name: &greeting "Hello" # inline
alias: *greeting
enabled: true
count: 42
description: | # block comment
  First line
  Second line
---
items:
  - name: World
    id: !!str 42
"""
    entries = extract_yaml(text, "strings.yml")
    assert [entry.source for entry in entries] == [
        "Hello",
        "First line\nSecond line\n",
        "World",
    ]
    for entry in entries:
        entry.update(
            {"Hello": "Olá", "World": "Mundo", "42": "Quarenta e dois"}.get(
                entry.source, "Primeira linha\nSegunda linha\n"
            )
        )
    exported = translated_yaml(text, entries)
    documents = list(YAML(typ="safe").load_all(exported))
    assert documents[0]["name"] == documents[0]["alias"] == "Olá"
    assert documents[0]["enabled"] is True
    assert documents[0]["count"] == 42
    assert documents[0]["description"] == "Primeira linha\nSegunda linha\n"
    assert documents[1]["items"][0] == {"name": "Mundo", "id": "42"}
    for comment in ("# Keep this comment", "# inline", "# block comment"):
        assert comment in exported


def test_cyclic_yaml_alias_does_not_recurse():
    entries = extract_yaml("tree: &tree\n  name: Hello\n  children: [*tree]\n", "tree.yaml")
    assert len(entries) == 1
    assert entries[0].source == "Hello"


def test_decompile_real_renpy_82_script_after_qt_import():
    # Qt installs an import hook; worker isolation must still handle fake Ren'Py modules.
    from PySide6 import QtCore  # noqa: F401

    path = Path(__file__).parent / "fixtures/the_question-8.2.rpyc"
    text, warnings = decompile_script(path)
    entries = extract_renpy(text, "script.rpy")
    assert not warnings
    assert len(entries) == 77
    assert any(entry.source == "Sylvie" for entry in entries)
    assert any("Professor Eileen" in entry.source for entry in entries)
    assert any(entry.source == "Hi there! How was class?" for entry in entries)
