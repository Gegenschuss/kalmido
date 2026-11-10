"""2.809.0 (#5476): undo across devices -- renaming / moving a folder of the sidebar in the core's step groups (a diff part,
core/undodiff.py).

A folder is a path of its person (lists.folder, the folder order in the settings), not a row: POST /api/folders/rename records
a diff part of kind "folder_path" (ref = the person, {old, new}) in the person's group, labelled with the new name -- only when
it did not merge into a folder that existed already (a merge cannot be split again). Taking back / forward runs the same way
as the route (sections.py folder_rename_do: lists, member rows, order, shares, templates, repositories, playbook, colour,
favourite go along), only while the folder is still where the step left it and the other name is free; the depth rule of
the route applies. Only the person's own folders (no rights of others are involved). Dissolving a folder (POST
/api/folders/delete) records no step: its people and agents go with it.

Interface:
  fpu_add(c, uid, old, new, merged) -> group id | None   after the route's rename, before its commit"""
from flask import g

from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.pg import write_lock
from ..core.undoareas import UA_RENAMED, ua_plain
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from .lists import FOLDER_DEPTH, FOLDER_SEP, folder_under
from .sections import _folder_paths, folder_rename_do

FPU_KIND = "folder_path"
FPU_GONE = N_("The folder is not where this step left it, so it cannot be undone")


def fpu_add(c, uid, old, new, merged):
    if merged or undo_person(c) is None:
        return None
    label = (UA_RENAMED, [ua_plain(new.replace(FOLDER_SEP, " / "))])
    if not ug_diff_add(c, uid, FPU_KIND, uid, None, "tasks", label, {"old": old, "new": new}):
        return None
    return (g.get("undo_group") or {}).get("id")


def fpu_run(c, uid, rid, data, redo):
    if int(rid) != int(uid):
        raise Denied(404)
    src, dst = (data.get("old"), data.get("new")) if redo else (data.get("new"), data.get("old"))
    if not isinstance(src, str) or not isinstance(dst, str) or not src or not dst or folder_under(dst, src):
        raise Denied(409, tr(FPU_GONE))
    write_lock(c, f"usettings-{int(uid)}")  # as the route
    paths = _folder_paths(c, uid)
    if src not in paths or any(p == dst or folder_under(p, dst) for p in paths):
        raise Denied(409, tr(FPU_GONE))
    below = max([p.count(FOLDER_SEP) - src.count(FOLDER_SEP) for p in paths if folder_under(p, src)] or [0])
    if dst.count(FOLDER_SEP) + 1 + below > FOLDER_DEPTH:
        raise Denied(409, tr("Folders nest at most {0} levels deep", FOLDER_DEPTH))
    folder_rename_do(c, uid, src, dst)
    return data, []


undo_diff_reg(FPU_KIND, fpu_run, "tasks")
