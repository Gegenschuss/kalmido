"""Kalmido: files of lists with the lock, encrypted in the browser with the list key (2.64.2, #1817, stage 2).

Format (static/js/liste2efile.js): b"KENC\\x02" | gen (4 bytes, big endian) | iv (12) | AES-256-GCM(list key of gen,
AAD "kalmido-lfile:v1:<list_id>:<gen>", u32 header length | header JSON {name, type, size} | file bytes). attachments.enc = 2,
attachments.e2e_gen = gen, attachments.name = the file name as list cipher (field "file_name"), mime application/octet-stream.
Readable for every member with the list key; no text extract, no preview, no agent access. Upload, conversion when the lock
goes on / off / after a key change, and the guards of the plain upload ways live here (part B)."""
