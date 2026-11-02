"""2.372.0 (#3316): the snapshot of the approver's signature picture taken at approving an entertainment receipt
(office/meals.py bw_meal_approve: "<approver id>:<base64>", encrypted like the profile; '' = none / approved before 2.372,
then the PDF reads the profile as before). Older versions ignore it."""
MIGRATIONS = [
    ("office_meals", "sign_pic", "ALTER TABLE office_meals ADD COLUMN IF NOT EXISTS sign_pic TEXT NOT NULL DEFAULT ''"),
]
