"""Install the pinned official cross-platform SDK, verifying its published SHA256."""

import argparse
import hashlib
import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

SDK_VERSION = "8.5.3"
SDK_TAG = "8.5.3.26051504"
SDK_SHA256 = "eb0a9be7f0fb13632fe25ceade9a8bed5a1b4d6b6e83bd19eeeb29e1a1bb4a45"
SDK_URL = (
    f"https://github.com/renpy/renpy/releases/download/{SDK_TAG}/renpy-{SDK_VERSION}-sdk.tar.bz2"
)


def install(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination / f"renpy-{SDK_VERSION}-sdk"
    if (root / "renpy.sh").is_file() and (root / "renpy").is_dir():
        return root.resolve()
    if root.exists():
        raise ValueError(
            f"SDK incompleto em {root}; preserve seus arquivos e escolha outro destino."
        )
    archive = destination / f"renpy-{SDK_VERSION}-sdk.tar.bz2"
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        try:
            with urlopen(SDK_URL, timeout=120) as response, temporary.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            with temporary.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != SDK_SHA256:
                    raise ValueError(
                        "SHA256 do SDK difere do checksum oficial. Instalação cancelada."
                    )
            temporary.rename(archive)
        finally:
            temporary.unlink(missing_ok=True)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SDK_SHA256:
            raise ValueError("SHA256 inválido no SDK em cache. Use um arquivo oficial verificado.")
    with tempfile.TemporaryDirectory(prefix="sdk-install-", dir=destination) as folder:
        with tarfile.open(archive) as package:
            package.extractall(folder, filter="data")
        unpacked = Path(folder) / root.name
        if not (unpacked / "renpy.sh").is_file():
            raise ValueError("O arquivo não contém o SDK esperado.")
        shutil.move(str(unpacked), root)
    return root.resolve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baixar e verificar o SDK oficial Ren'Py 8.5.3")
    parser.add_argument("--destino", type=Path, required=True)
    print(install(parser.parse_args().destino))
