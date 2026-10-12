import pickle
import zlib

import pytest


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
