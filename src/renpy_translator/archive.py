import io
import pickle
import shutil
import zlib
from collections.abc import Callable
from pathlib import Path

from .paths import contained_path

MAX_INDEX_SIZE = 64 * 1024 * 1024


def safe_encode(value, encoding):
    if not isinstance(value, str) or encoding not in {"latin1", "latin-1"}:
        raise ValueError("Codificação não permitida no índice RPA.")
    return value.encode("latin-1")


def safe_empty_bytes():
    return b""


class PrimitiveUnpickler(pickle.Unpickler):
    """RPA indices require primitives only, never executable pickle globals."""

    def find_class(self, module, name):
        # Python 3 serializes bytes in protocol 2 via these two constructors.
        # Only accept the exact primitive operations required by standard RPA.
        if (module, name) == ("_codecs", "encode"):
            return safe_encode
        if module in {"builtins", "__builtin__"} and name == "bytes":
            return safe_empty_bytes
        raise ValueError("O índice RPA contém objetos não permitidos.")

    def persistent_load(self, pid):
        raise ValueError("Referência externa não permitida no índice RPA.")


def decompress_limited(data: bytes, limit: int = MAX_INDEX_SIZE) -> bytes:
    decoder = zlib.decompressobj()
    result = decoder.decompress(data, limit + 1)
    if len(result) > limit or not decoder.eof:
        raise ValueError("Conteúdo comprimido excede o limite ou está incompleto.")
    return result


def extract_archive(
    archive: Path,
    destination: Path,
    progress: Callable[[str], None] = lambda _: None,
) -> list[str]:
    """Extract standard RPA 2.0/3.0/3.2 with streaming and path validation."""
    extracted = []
    with archive.open("rb") as stream:
        header = stream.readline(256).split()
        if not header or header[0] not in (b"RPA-2.0", b"RPA-3.0", b"RPA-3.2"):
            raise ValueError(f"{archive.name}: versão RPA não suportada.")
        try:
            index_offset = int(header[1], 16)
            key = 0 if header[0] == b"RPA-2.0" else int(header[2], 16)
        except (IndexError, ValueError) as exc:
            raise ValueError(f"{archive.name}: cabeçalho RPA inválido.") from exc
        size = archive.stat().st_size
        if not 0 < index_offset < size or size - index_offset > MAX_INDEX_SIZE:
            raise ValueError(f"{archive.name}: posição/tamanho do índice inválido.")
        stream.seek(index_offset)
        index = PrimitiveUnpickler(
            io.BytesIO(decompress_limited(stream.read())), encoding="bytes"
        ).load()
        if not isinstance(index, dict):
            raise ValueError(f"{archive.name}: índice RPA inválido.")
        # Validate all entries before writing this archive's files.
        validated = []
        for name, segments in index.items():
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            if not isinstance(name, str) or not isinstance(segments, (list, tuple)):
                raise ValueError("Nome/segmentos inválidos no índice RPA.")
            target = contained_path(destination, name)
            pieces = []
            for segment in segments:
                if not isinstance(segment, (list, tuple)) or len(segment) not in (2, 3):
                    raise ValueError(f"Segmento inválido: {name}")
                if type(segment[0]) is not int or type(segment[1]) is not int:
                    raise ValueError(f"Posição/tamanho inválidos: {name}")
                offset, length = segment[0] ^ key, segment[1] ^ key
                prefix = segment[2] if len(segment) == 3 else b""
                if isinstance(prefix, str):
                    prefix = prefix.encode("latin-1")
                if (
                    not isinstance(prefix, bytes)
                    or length < len(prefix)
                    or not 0 <= offset <= offset + length - len(prefix) <= index_offset
                ):
                    raise ValueError(f"Segmento fora do arquivo: {name}")
                pieces.append((offset, length, prefix))
            validated.append((name, target, pieces))
        for name, target, pieces in validated:
            progress(f"Extraindo {archive.name}: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as output:
                for offset, length, prefix in pieces:
                    output.write(prefix)
                    stream.seek(offset)
                    remaining = length - len(prefix)
                    while remaining:
                        chunk = stream.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise ValueError(f"Arquivo RPA truncado: {name}")
                        output.write(chunk)
                        remaining -= len(chunk)
            extracted.append(name)
    return extracted


def copy_loose_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
