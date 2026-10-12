import os
import pickle
import zlib
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def sdk_path():
    root = os.environ.get("RENPY_SDK")
    if not root:
        pytest.skip("Defina RENPY_SDK para executar os testes com o SDK real.")
    from renpy_translator.sdk import sdk_launcher

    sdk_launcher(Path(root))
    return Path(root)


@pytest.fixture
def make_rpa():
    def build(path, files, version="RPA-3.0", prefix_size=0, key=0x12345678):
        header_size = 64
        data = bytearray(b"\x00" * header_size)
        index = {}
        for name, content in files.items():
            prefix = content[:prefix_size]
            position = len(data)
            data.extend(content[len(prefix) :])
            archive_key = 0 if version == "RPA-2.0" else key
            index[name] = [(position ^ archive_key, len(content) ^ archive_key, prefix)]
        offset = len(data)
        header = f"{version} {offset:016x}"
        if version != "RPA-2.0":
            header += f" {key:08x}"
        header = (header + "\n").encode()
        data[: len(header)] = header
        data.extend(zlib.compress(pickle.dumps(index, protocol=2)))
        path.write_bytes(data)
        return path

    return build
