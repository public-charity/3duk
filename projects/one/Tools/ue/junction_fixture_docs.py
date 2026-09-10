"""Write the six frozen junction fixtures out as real Streetscape documents.

    C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/junction_fixture_docs.py <out-dir>

Run with the pipeline python (numpy), NOT inside the editor: the documents come from
``Tools/blender/tests/synthetic.py`` itself, so the files the Unreal import path is then driven over are the
numpy toolchain's own fixtures rather than a second hand-written copy of them. ``08_junction_fixtures.py`` reads
this directory and each document's ``_terrain`` note.

Nothing here is part of a site build; it exists so the junction parity claim can be made through
``ImportStreetscapeJson`` rather than through a unit test that calls the geometry directly.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "blender"))

from tests import synthetic  # noqa: E402


def main(argv):
    if len(argv) != 1:
        print("usage: junction_fixture_docs.py <out-dir>", file=sys.stderr)
        return 2
    out = argv[0]
    if not os.path.isdir(out):
        os.makedirs(out)
    names = sorted(synthetic.JUNCTION_BUILDERS)
    for name in names:
        doc = synthetic.JUNCTION_BUILDERS[name]()
        path = os.path.join(out, name + ".json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, indent=1, sort_keys=False)
            fh.write("\n")
        print("%-22s %d spline(s), %d junction(s) -> %s"
              % (name, len(doc["splines"]), len(doc["junctions"]), path))
    print("THANET_OK junction_fixture_docs %s" % json.dumps({"documents": len(names), "dir": out.replace("\\", "/")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
