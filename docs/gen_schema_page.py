import json

import mkdocs_gen_files

from deadwax import Dossier

schema = json.dumps(Dossier.model_json_schema(), indent=2, ensure_ascii=False)
lines = [
    "# Schema",
    "",
    "This page is generated from `deadwax.Dossier.model_json_schema()`. It describes the JSON "
    "that `deadwax --format json` prints and `Dossier.model_dump_json()` returns; "
    "[Output](output.md) explains the fields.",
    "",
    "```json",
    schema,
    "```",
]

with mkdocs_gen_files.open("schema.md", "w") as fd:
    fd.write("\n".join(lines) + "\n")

mkdocs_gen_files.set_edit_path("schema.md", "../src/deadwax/core/models.py")
