"""Persistent IOPS Library worker daemon.

Launched as a standalone background Blender process with the master library
file already open:

    blender --background --factory-startup --disable-autoexec <master.blend>
        --python session_worker.py -- <cache_directory>

It then reads line-delimited JSON jobs from stdin and answers each one with
exactly one line on stdout, prefixed with ``IOPS_LIBRARY_JOB `` so the parent
process can tell protocol lines apart from bpy's own background-mode chatter
(and anything the reused workers print). It stays alive across jobs so the
master file is opened once instead of once per publish/delete/refresh.

This module intentionally reuses the existing one-shot workers instead of
duplicating their logic: they are plain modules whose ``main()`` only runs
under ``if __name__ == "__main__":``, so importing them here has no side
effects.
"""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import catalog_worker  # noqa: E402
import delete_worker  # noqa: E402
import publish_worker  # noqa: E402

import bpy  # noqa: E402

JOB_PREFIX = "IOPS_LIBRARY_JOB "

CACHE_DIRECTORY = ""


def emit(payload):
    sys.stdout.write(JOB_PREFIX + json.dumps(payload) + "\n")
    sys.stdout.flush()


def job_manifest(job):
    """The job dict, minus the protocol/transport keys, passed through to
    the reused worker functions untouched."""
    return {k: v for k, v in job.items() if k not in ("id", "op", "payload_file")}


def handle_job(job):
    job_id = job.get("id")
    op = job.get("op")

    if op == "publish":
        payload_file = job.get("payload_file", "")
        manifest = job_manifest(job)
        result = publish_worker.publish(payload_file, manifest)
        return {"id": job_id, **result}

    if op == "delete":
        manifest = job_manifest(job)
        result = delete_worker.remove_assets(manifest)
        return {"id": job_id, **result}

    if op == "refresh":
        entries = catalog_worker.catalog_assets(CACHE_DIRECTORY)
        return {
            "id": job_id,
            "ok": True,
            "assets": entries,
            "master_file": bpy.data.filepath,
            "master_mtime": os.path.getmtime(bpy.data.filepath),
            "master_size": os.path.getsize(bpy.data.filepath),
        }

    if op == "quit":
        return {"id": job_id, "ok": True}

    raise RuntimeError("Unsupported job op '%s'." % op)


def command_arguments():
    try:
        separator = sys.argv.index("--")
    except ValueError as error:
        raise RuntimeError("Session worker arguments are missing.") from error

    arguments = sys.argv[separator + 1 :]
    if len(arguments) != 1:
        raise RuntimeError("Expected a single thumbnail cache directory argument.")
    return arguments[0]


def main():
    global CACHE_DIRECTORY
    CACHE_DIRECTORY = command_arguments()

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            job = json.loads(line)
        except ValueError as error:
            emit({"id": None, "ok": False, "error": "Malformed job line: %s" % error})
            continue

        if not isinstance(job, dict):
            emit({"id": None, "ok": False, "error": "Job line is not a JSON object."})
            continue

        job_id = job.get("id")
        op = job.get("op")

        try:
            result = handle_job(job)
        except Exception as error:
            emit(
                {
                    "id": job_id,
                    "ok": False,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                }
            )
            continue

        emit(result)
        if op == "quit":
            break


if __name__ == "__main__":
    main()
