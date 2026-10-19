## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## How it was tested

<!-- Which tests did you add or run (tests/run_all.sh)? Anything checked by hand (phone, offline, SSO)? -->

## Checklist

- [ ] `tests/run_all.sh` passes (CI will run it too)
- [ ] new user-facing strings use `tr()` / `trn()` and have a German translation (`python3 tools/i18n_check.py`)
- [ ] README updated if behaviour changed
- [ ] AI tools were used for this change: yes / no <!-- welcome, see CONTRIBUTING.md -->

## New e-invoice format (only for a new format, see CONTRIBUTING.md)

- [ ] example invoices with invented data only (no real companies, people or addresses)
- [ ] official validator / Schematron of the format runs in the `einvoice` CI job, pinned by SHA-256
- [ ] link and version of the specification are named in CONTRIBUTING.md; a maintainer of the format is named
- [ ] no real-time submission to an authority and no data sent to third parties (otherwise agreed in an issue first)
