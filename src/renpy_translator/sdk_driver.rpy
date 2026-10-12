# Runs inside the official SDK in an isolated utility project.
# Original game init/python statements are parsed, never executed.
init -999 python:
    def _rnt_generate():
        import json
        import os
        import renpy.translation.generation as generation

        parser = renpy.arguments.ArgumentParser()
        parser.add_argument("request")
        args = parser.parse_args()
        with open(args.request, encoding="utf-8") as stream:
            request = json.load(stream)

        result = {"warnings": [], "version": renpy.version_string}
        try:
            renpy.config.gamedir = request["game"]
            renpy.config.tl_directory = request["tl_directory"]
            renpy.config.translate_files = request["files"]
            # Keep the engine's own common/ UI texts out of the selected game.
            generation.translate_list_files = lambda: request["files"]
            renpy.game.script.translator = renpy.translation.ScriptTranslator()
            generation.todo = False
            for filename in request["files"]:
                renpy.parser.parse_errors[:] = []
                nodes = renpy.parser.parse(filename)
                if nodes is None:
                    result["warnings"].extend(str(error) for error in renpy.parser.parse_errors)
                    continue
                renpy.game.script.assign_names(nodes, filename)
                renpy.translation.restructure(nodes)
                renpy.game.script.translator.take_translates(renpy.script.collapse_stmts(nodes))
                generation.write_translates(filename, request["language"], generation.null_filter)

            renpy.parser.parse_errors[:] = []
            generation.write_strings(request["language"], generation.null_filter, 0, 999, False)
            generation.close_tl_files()
        except Exception as error:
            import traceback
            result["error"] = traceback.format_exc()
        finally:
            generation.close_tl_files()
            with open(request["result"], "w", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False)
        return False

    renpy.arguments.register_command("rnt_generate", _rnt_generate)
