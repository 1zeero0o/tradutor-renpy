from renpy_translator.exporter import translated_yaml
from renpy_translator.extractors import extract_yaml


def test_yaml_only_requested_keys_and_single_quoted_condition():
    text = """name: Camila
description: A friendly girl
title: Ignore this title
condition: '"camila_event_03" in DONE'
items:
  - condition: "not DONE"
    name: Friend
    technical: script_name
  - condition: DONE
  - description: Other description
"""
    entries = extract_yaml(text, "events.yml")
    assert [entry.source for entry in entries] == [
        "Camila",
        "A friendly girl",
        '"camila_event_03" in DONE',
        "Friend",
        "Other description",
    ]
    condition = next(entry for entry in entries if entry.context.endswith(".condition"))
    condition.update('"camila_event_04" in DONE')
    exported = translated_yaml(text, [condition])
    assert "condition: '\"camila_event_04\" in DONE'" in exported
    assert 'condition: "not DONE"' in exported
    assert "title: Ignore this title" in exported
