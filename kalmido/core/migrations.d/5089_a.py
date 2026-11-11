"""2.652.0 (#5089): sharing anew in the calendar / address book dialog brings a person back whose share in the core ran out.
kalmido_kern_mirror (4712_a.py) mirrored a member row added or changed in ev_cal_members / book_members into the shares of the
object's reference node by setting only the role: a share there with an expiry date in the past kept it, and the person stayed
out although the owner had just shared again (events/model.py cal_member_set / contacts/model.py book_member_set always write
the row, which fires the trigger, also with the same role). Now an added or changed old row also clears an expiry date that
has already passed on the person's / agent's shares of that node: sharing anew in those dialogs lets the person in again,
without end date, as the dialog shows it. A still valid end date given in the file store's share dialog stays (fable review:
a role change in the old dialog, an import or a repair writes the row too and must not lift a deliberate end date); its expiry
alone changes nothing (kalmido_kern_back, 5046_a.py: no UPDATE OF expires_at).
The mirror's own UPDATE still fires kalmido_kern_back (UPDATE OF role); that one finds the old row as the share has it: a no-op.

The same function as 4712_a.py with that one column more, replaced here: the fragments run sorted by file name, so this body
wins on every start (4712_a.py's CREATE OR REPLACE runs first). The triggers stay as 4712_a.py made them. The way back: an
older version's start writes 4712_a.py's body again (shares then keep their expiry when shared anew, the error of before).
fs_shares.expires_at exists since 2.48.
2.924.0 (#5069, stage 7b): the function and trigger (kalmido_kern_mirror) went with the old member tables (events/evkern.py ev_kern_drop,
core/migrations.d/5069_b.py); this fragment keeps only its history.
"""
