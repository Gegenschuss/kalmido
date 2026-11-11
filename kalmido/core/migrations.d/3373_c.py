"""2.609.0 (#3373): labels of an organisation (lists/orglabels.py): org_tags = a label defined once for every project of the
organisation; list_tags.org_tag_id = the label a project tag stood for. 2.925.0 (#5275, stage Q5a): both moved into the core's
obj_tags (scope org, the label sits on the task itself); migrations.d/5275_a.py drops org_tags, so this fragment makes nothing
any more (a table that is dropped may be created nowhere, tools/check_migrations.py)."""
