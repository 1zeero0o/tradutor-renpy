import contextlib
import io
import json
import struct
import sys
from pathlib import Path

from .archive import decompress_limited


def decompile_local(path: Path) -> tuple[str, list[str]]:
    from ._vendor.unrpyc import decompiler
    from ._vendor.unrpyc.decompiler.renpycompat import pickle_safe_loads

    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("RPYC excede o limite de 128 MiB.")
    raw = path.read_bytes()
    if raw.startswith(b"RENPY RPC2"):
        position = 10
        compressed = None
        while position + 12 <= len(raw):
            slot, offset, length = struct.unpack_from("<III", raw, position)
            position += 12
            if slot == 0:
                break
            if offset + length > len(raw):
                raise ValueError("RPYC truncado.")
            if slot == 1:
                compressed = raw[offset : offset + length]
        if compressed is None:
            raise ValueError("RPYC sem bloco de roteiro.")
    else:
        compressed = raw
    _, nodes = pickle_safe_loads(decompress_limited(compressed, 128 * 1024 * 1024))
    output = io.StringIO()
    log = []
    decompiler.pprint(output, nodes, decompiler.Options(log=log, init_offset=True))
    return output.getvalue(), log


def main(filename: str | None = None, output_path: str | None = None) -> int:
    output_path = output_path or (sys.argv[2] if filename is None and len(sys.argv) > 2 else None)
    try:
        with contextlib.redirect_stdout(io.StringIO()) as diagnostics:
            text, log = decompile_local(Path(filename or sys.argv[1]))
        if diagnostics.getvalue():
            log.append(diagnostics.getvalue())
        payload = json.dumps({"text": text, "warnings": log}, ensure_ascii=False)
        if output_path:
            Path(output_path).write_text(payload, encoding="utf-8")
        else:
            print(payload)
        return 0
    except Exception as exc:
        if output_path:
            Path(output_path).write_text(json.dumps({"error": str(exc)}), encoding="utf-8")
        elif sys.stderr is not None:
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
