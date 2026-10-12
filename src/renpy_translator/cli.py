import argparse
import sys
from pathlib import Path

from .exporter import export_game
from .model import Project, export_csv, import_csv
from .pipeline import create_project


def main() -> int:
    parser = argparse.ArgumentParser(description="Tradutor Ren'Py — ferramentas de projeto")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extrair", help="Criar projeto a partir do .exe do jogo")
    extract.add_argument("exe", type=Path)
    extract.add_argument("--projeto", type=Path, required=True)
    extract.add_argument("--idioma", default="portuguese_br")
    export = commands.add_parser("exportar", help="Gerar arquivos para instalar no jogo")
    export.add_argument("projeto", type=Path)
    export.add_argument("--destino", type=Path, required=True)
    export.add_argument("--somente-revisados", action="store_true")
    export.add_argument("--nao-ativar", action="store_true")
    for command in ("importar-csv", "exportar-csv"):
        csv_parser = commands.add_parser(command)
        csv_parser.add_argument("projeto", type=Path)
        csv_parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "extrair":
            project = create_project(args.exe, args.projeto, args.idioma, print)
            print(project.path)
            for warning in project.warnings:
                print(f"Aviso: {warning}", file=sys.stderr)
        else:
            project = Project.load(args.projeto)
            if args.command == "exportar":
                print(
                    export_game(project, args.destino, args.somente_revisados, not args.nao_ativar)
                )
            elif args.command == "importar-csv":
                count = import_csv(project, args.csv)
                project.save()
                print(f"{count} textos importados.")
            else:
                export_csv(project, args.csv)
                print(args.csv)
    except Exception as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
