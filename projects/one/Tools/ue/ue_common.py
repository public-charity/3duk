"""Shared helpers for the Thanet editor-Python scripts (UE_PLAN.md 5.3 row 0).

stdlib + ``unreal`` only: UE 5.8's bundled Python 3.11 has no numpy (BRIEF 4.5). Every script imports this
module, parses ``sys.argv`` (set by the PythonScriptPlugin from the ``-script="<file> <args>"`` string), and
ends with ``report(name, payload)`` which prints ``THANET_OK <name> <json>`` - or raises, which the commandlet
turns into "Python script executed with errors" and a non-zero exit.

Run directly (``run_ue_python.ps1 -Script ue_common.py``) it prints its own THANET_OK line with the resolved
project and data directories, which proves the headless runner and the python stub generation work.
"""
import json
import os
import sys
import time

import unreal

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

_T0 = time.time()


def _norm(path):
    return os.path.normpath(path).replace("\\", "/")


def project_dir():
    """Absolute project directory (the one holding Thanet.uproject), forward slashes, no trailing slash."""
    return _norm(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()))


def content_dir():
    return project_dir() + "/Content"


def data_dir():
    """StreetscapeSettings.DataDir resolved to an absolute path (adapter output, <repo>/data/<site>/out/unreal)."""
    settings = unreal.StreetscapeSettings.get_default_object()
    return _norm(settings.get_resolved_data_dir())


def site_name():
    return str(unreal.StreetscapeSettings.get_default_object().get_editor_property("site_name"))


def parse_args(argv, flags=(), options=None):
    """Tiny argv parser: ``--flag`` -> True, ``--key value`` -> value (defaults from ``options``).

    Unknown ``--`` arguments raise so a typo cannot silently change a run.
    """
    out = dict(options or {})
    for f in flags:
        out.setdefault(f, False)
    args = list(argv[1:])
    i = 0
    while i < len(args):
        a = args[i]
        if not a.startswith("--"):
            raise SystemExit("unexpected positional argument %r" % a)
        key = a[2:].replace("-", "_")
        if key in flags:
            out[key] = True
            i += 1
        elif options is not None and key in options:
            if i + 1 >= len(args):
                raise SystemExit("--%s needs a value" % key)
            out[key] = args[i + 1]
            i += 2
        else:
            raise SystemExit("unknown argument %s" % a)
    return out


def log(msg):
    line = "[thanet] %s" % msg
    print(line)
    unreal.log(line)


def elapsed_s():
    return round(time.time() - _T0, 1)


def save_all():
    """Save every dirty package - map, external actors (World Partition), assets."""
    ok = unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    log("save_dirty_packages -> %s" % ok)
    return ok


def report(script, payload):
    payload = dict(payload)
    payload.setdefault("elapsed_s", elapsed_s())
    line = "THANET_OK %s %s" % (script, json.dumps(payload, sort_keys=True))
    print(line)
    unreal.log(line)
    return line


def fail(script, msg):
    line = "THANET_FAIL %s %s" % (script, msg)
    print(line)
    unreal.log_error(line)
    raise RuntimeError(line)


if __name__ == "__main__":
    stub = project_dir() + "/Intermediate/PythonStub/unreal.py"
    report("ue_common", {
        "project_dir": project_dir(),
        "data_dir": data_dir(),
        "data_dir_exists": os.path.isdir(data_dir()),
        "site": site_name(),
        "python": sys.version.split()[0],
        "sys_path_has_tools_ue": SCRIPT_DIR.replace("\\", "/") in [p.replace("\\", "/") for p in sys.path],
        "python_stub": os.path.isfile(stub),
    })
