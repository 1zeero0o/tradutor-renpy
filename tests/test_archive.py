import io
import pickle

import pytest

from renpy_translator.archive import PrimitiveUnpickler, extract_archive


@pytest.mark.parametrize("version", ["RPA-2.0", "RPA-3.0", "RPA-3.2"])
@pytest.mark.parametrize("prefix_size", [0, 4])
def test_extract_rpa_versions_with_prefix(tmp_path, make_rpa, version, prefix_size):
    content = 'title: "Olá"\n'.encode()
    archive = make_rpa(tmp_path / "data.rpa", {"texts/pt.yml": content}, version, prefix_size)
    assert extract_archive(archive, tmp_path / "out") == ["texts/pt.yml"]
    assert (tmp_path / "out/texts/pt.yml").read_bytes() == content


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "C:\\escape",
        "..\\escape",
        "NUL",
        "name\nline",
        "bad|name",
    ],
)
def test_reject_path_escape_before_writing(tmp_path, make_rpa, name):
    archive = make_rpa(tmp_path / "data.rpa", {"valid.txt": b"safe", name: b"unsafe"})
    with pytest.raises(ValueError, match="Caminho"):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "out/valid.txt").exists()


def test_reject_executable_pickle_globals():
    data = pickle.dumps(eval)
    with pytest.raises(ValueError, match="não permitidos"):
        PrimitiveUnpickler(io.BytesIO(data)).load()


def test_reject_invalid_header(tmp_path):
    archive = tmp_path / "invalid.rpa"
    archive.write_bytes(b"RPA-3.0 invalid invalid\n")
    with pytest.raises(ValueError, match="cabeçalho"):
        extract_archive(archive, tmp_path / "out")
