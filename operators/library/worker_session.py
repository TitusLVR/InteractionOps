"""Parent-side manager for the persistent IOPS Library worker session.

Keeps one background Blender process alive with the master library file
open, feeding it line-delimited JSON jobs over stdin (see
``session_worker.py``) and reading its responses off stdout on a reader
thread.

Concurrency contract:
  * The reader thread ONLY touches the results ``queue.Queue`` -- no bpy
    calls happen there.
  * All bpy access happens on the main thread, inside ``enqueue`` (called by
    operators) and ``_pump`` (a ``bpy.app.timers`` callback, which always
    runs on the main thread).

This module holds no operator classes -- it is glue consumed by the
operators in a later part of the rewiring.
"""

import json
import os
import queue
import subprocess
import threading
import time

import bpy

from ...utils.library_core import valid_master_file
from .common import abs_path, cache_directory, configured_master_file, worker_creation_flags

JOB_PREFIX = "IOPS_LIBRARY_JOB "
IDLE_TIMEOUT_SECONDS = 120.0
QUIT_GRACE_SECONDS = 5.0
PUMP_INTERVAL_SECONDS = 0.2

_state = {
    "process": None,
    "stdin": None,
    "reader_thread": None,
    "results": None,
    "pending": {},
    "next_id": 1,
    "master_file": "",
    "last_activity": 0.0,
    "quit_sent": False,
    "quit_deadline": 0.0,
}


def _session_worker_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "session_worker.py")


def _process_alive():
    process = _state["process"]
    return process is not None and process.poll() is None


def _reader_loop(process, results):
    """Runs on a daemon thread. Only touches ``results`` (thread-safe) --
    never bpy."""
    stdout = process.stdout
    try:
        for raw_line in stdout:
            line = raw_line.strip()
            if not line or not line.startswith(JOB_PREFIX):
                continue
            payload = line[len(JOB_PREFIX) :]
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            results.put(data)
    except (OSError, ValueError):
        pass
    finally:
        results.put({"__eof__": True})


def _register_timer():
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=PUMP_INTERVAL_SECONDS)


def _tag_ui_redraw():
    """Best-effort nudge so the library panel repaints after ``pending``
    changes -- timers alone don't trigger a redraw. Main-thread only."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                for region in area.regions:
                    if region.type == "UI":
                        region.tag_redraw()
    except Exception:
        pass


def _mark_dead(message):
    """Tear down a dead/broken session and fail every pending job with
    ``message`` -- called from any path that discovers the child is gone
    (EOF, a broken stdin write, ...). Terminates a still-alive child first
    so a broken-pipe write failure can never leave an orphaned background
    Blender process running untracked, and fails every pending job (not
    just the one that triggered this) before nulling the process state --
    otherwise a later respawn could silently clobber their callbacks."""
    process = _state["process"]
    if process is not None:
        try:
            process.stdin.close()
        except Exception:
            pass
        if process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass
    _fail_all_pending(message)
    _state["process"] = None
    _state["stdin"] = None


def _fail_all_pending(message):
    pending = _state["pending"]
    _state["pending"] = {}
    for _job_id, info in pending.items():
        try:
            info["on_done"](None, message)
        except Exception as error:
            print("IOPS Library session: on_done raised: %s" % error)


def ensure_session(context, master_file):
    """Ensure a live worker process exists for ``master_file``. Reuses an
    existing process if it is already running against the same master;
    restarts it (via ``shutdown_session``) if the master changed."""
    if not master_file:
        return False, "No master library file configured."

    target_master = abs_path(master_file)
    if _process_alive() and os.path.normcase(_state["master_file"]) == os.path.normcase(
        target_master
    ):
        return True, ""

    if _state["process"] is not None:
        shutdown_session()

    command = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        master_file,
        "--python",
        _session_worker_path(),
        "--",
        cache_directory(master_file),
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            creationflags=worker_creation_flags(),
        )
    except OSError as error:
        return False, "Could not start the library worker session: %s" % error

    results = queue.Queue()
    reader_thread = threading.Thread(
        target=_reader_loop,
        args=(process, results),
        daemon=True,
    )
    reader_thread.start()

    # Defensive: a spawn should never silently clobber jobs some earlier
    # (buggy) path left pending -- fail them instead of losing them.
    if _state["pending"]:
        _fail_all_pending("Worker session restarted.")

    _state["process"] = process
    _state["stdin"] = process.stdin
    _state["reader_thread"] = reader_thread
    _state["results"] = results
    _state["pending"] = {}
    _state["next_id"] = 1
    _state["master_file"] = target_master
    _state["last_activity"] = time.monotonic()
    _state["quit_sent"] = False
    _state["quit_deadline"] = 0.0

    _register_timer()
    return True, ""


def enqueue(context, op, payload, on_done, label):
    """Queue a job on the persistent session. ``payload`` is the job dict
    minus ``id``/``op`` (those are assigned here). ``on_done(result, error)``
    is called from ``_pump`` on the main thread once the worker answers, or
    immediately (still on the calling/main thread) if the job could not be
    queued at all."""
    master_file = configured_master_file(context)
    if not valid_master_file(master_file):
        message = "No master library file configured."
        on_done(None, message)
        return False, message

    ok, error = ensure_session(context, master_file)
    if not ok:
        on_done(None, error)
        return False, error

    job_id = _state["next_id"]
    _state["next_id"] += 1

    job = dict(payload)
    job["id"] = job_id
    job["op"] = op

    _state["pending"][job_id] = {"op": op, "on_done": on_done, "label": label}
    _state["last_activity"] = time.monotonic()

    try:
        stdin = _state["stdin"]
        stdin.write(json.dumps(job) + "\n")
        stdin.flush()
    except (OSError, ValueError) as error:
        # This job is already in `_state["pending"]` -- let `_mark_dead`
        # fail it (and every other pending job) through the normal path
        # instead of calling `on_done` here too, which would double-fire it.
        message = "Worker session died: %s" % error
        _mark_dead(message)
        # _mark_dead just emptied the pending queue -- repaint the panel.
        _tag_ui_redraw()
        return False, message

    try:
        context.window_manager.iops_library_status = "%s queued (%d pending)" % (
            label,
            len(_state["pending"]),
        )
    except Exception:
        pass

    _tag_ui_redraw()

    return True, ""


def _pump():
    """``bpy.app.timers`` callback -- main thread only."""
    results = _state["results"]
    if results is None:
        return None

    changed = False

    while True:
        try:
            data = results.get_nowait()
        except queue.Empty:
            break

        if data.get("__eof__"):
            _mark_dead("Worker session ended unexpectedly.")
            changed = True
            continue

        info = _state["pending"].pop(data.get("id"), None)
        if info is None:
            continue
        changed = True
        try:
            info["on_done"](data, None)
        except Exception as error:
            print("IOPS Library session: on_done raised: %s" % error)

    if _process_alive() and not _state["pending"]:
        if not _state["quit_sent"]:
            if time.monotonic() - _state["last_activity"] > IDLE_TIMEOUT_SECONDS:
                try:
                    _state["stdin"].write(json.dumps({"op": "quit"}) + "\n")
                    _state["stdin"].flush()
                    _state["quit_sent"] = True
                    _state["quit_deadline"] = time.monotonic() + QUIT_GRACE_SECONDS
                except (OSError, ValueError):
                    _mark_dead("Worker session died while idling.")
                    changed = True
        elif time.monotonic() > _state["quit_deadline"]:
            # Asked nicely and it didn't leave within the grace period --
            # stop waiting on it.
            process = _state["process"]
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass
            changed = True

    if changed:
        _tag_ui_redraw()

    if _process_alive() or _state["pending"]:
        return PUMP_INTERVAL_SECONDS

    return None


def shutdown_session():
    """Stop the worker session, if any. Safe to call repeatedly (e.g. from
    addon unregister)."""
    process = _state["process"]
    if process is not None and process.poll() is None:
        try:
            process.stdin.write(json.dumps({"op": "quit"}) + "\n")
            process.stdin.flush()
        except OSError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                pass
        except Exception:
            pass

    reader_thread = _state["reader_thread"]
    if reader_thread is not None:
        reader_thread.join(timeout=1)

    _fail_all_pending("Worker session shut down.")

    _state["process"] = None
    _state["stdin"] = None
    _state["reader_thread"] = None
    _state["results"] = None
    _state["pending"] = {}
    _state["master_file"] = ""
    _state["quit_sent"] = False
    _state["quit_deadline"] = 0.0


def queue_depth():
    return len(_state["pending"])


def pending_jobs():
    """Return ``[(op, label), ...]`` for jobs currently queued/running, in
    submission order. Main-thread only, like ``queue_depth``."""
    return [(info["op"], info["label"]) for info in _state["pending"].values()]
