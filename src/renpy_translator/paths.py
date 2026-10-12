from pathlib import Path, PurePosixPath


def relative_path(value: str) -> Path:
    """Validate archive/project paths consistently on Windows and Unix."""
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or any(any(ord(char) < 32 or char in '<>:"|?*' for char in part) for part in path.parts)
    ):
        raise ValueError(f"Caminho de arquivo inválido: {value!r}")
    # Windows silently strips these suffixes and interprets device names as files.
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)
    }
    if any(
        part.endswith((" ", ".")) or part.split(".")[0].upper() in reserved for part in path.parts
    ):
        raise ValueError(f"Caminho incompatível com Windows: {value!r}")
    return Path(*path.parts)


def contained_path(root: Path, value: str) -> Path:
    path = root / relative_path(value)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Arquivo fora da pasta de destino: {value!r}")
    return path
