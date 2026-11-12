# Changelog

All notable changes to Kalmido are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Kalmido uses
[semantic versioning](https://semver.org/): every published change gets at least a new patch version, new features a
minor one. Releases in which operators have to do something carry a fixed section "Action needed"; the update notice
in Settings > Help shows that section of the target version.

## Older versions

- [2.900-2.999](docs/changelog/2.900-2.999.md)
- [2.800-2.899](docs/changelog/2.800-2.899.md)
- [2.700-2.799](docs/changelog/2.700-2.799.md)
- [2.600-2.699](docs/changelog/2.600-2.699.md)
- [2.500-2.599](docs/changelog/2.500-2.599.md)
- [2.400-2.499](docs/changelog/2.400-2.499.md)
- [2.300-2.399](docs/changelog/2.300-2.399.md)
- [2.200-2.299](docs/changelog/2.200-2.299.md)
- [2.100-2.199](docs/changelog/2.100-2.199.md)
- [2.0-2.99](docs/changelog/2.0-2.99.md)
- [1.x](docs/changelog/1.x.md)

## [2.1007.0] - 2026-11-12

Package 2.997 (Bündel: Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher), Sammelpaket: Aufgaben ohne Paket (Dispatcher), Teil 1/6: Sammelpaket: Aufgabe).

### Fixed
- Undo: a setting the app saves by itself (the device's look on first start, view arrangements) no longer lends its undo group to the next step of another area - Undo took back the setting instead of the action (receipt suggestion, closed month, checked receipts, time entries, deadline task, agent proposal, new event) (#5697 #5699 #5700 #5701 #5703 #5704 #5707 #5710 #5711 #5478 #5607 #5615 #5702).
- Undo: the first upload of an account's look and the roadmap's view state (zoom, folded projects) are no undo steps any more (#5702 #5625).
- Undo: keys with several entries (favourites, workspace colours) are one undo step per change again, not bundled for 10 minutes (#5705 #5706).
- Undo: "Take it" and an idea taken over from a proposal record their server undo step; deleting a project into the list trash is a server undo step, so undo after redo makes it active again (#5606 #5611 #5609 #5709).
- Undo: a task's undo step keeps its code snippets and its lock (#5613 #5614).
- Table shares: an address row (pending invitation) can be removed and its role changed again (#5672).
- /api/state switches into the system context only when there are folder / group shares to read (#5137); a start no longer locks org_joins (#4841).
- The repair of lists in shared folders (#931) reads the folder shares from fs_shares again (#5677); restoring a rights group from the trash writes the rights log again (#5708).
- Tests follow the current behaviour (server undo stage 7, file version undo by pointer, confirmed addresses for shares, model-per-run agent defaults, word search, travel as a back step, CI speed calibration of the column width check) and static checks are clean again (#4949 #5682 #5683 #5671 #5617 #5624 #5354 #5679 #5680 #5678 #5612 #5616 #5618 #5620 #5622 #5698 #5681 #5641 #5720).

Package 2.1001 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- #5669: sharing a list or a list folder by e-mail address binds only an account that proved the address (the core helper used by tables and wiki since #5643); an address nobody proved is answered like an unknown address and reaches nobody. The address path is decided once per request, and its answer carries nothing account-specific.

## [2.1001.0] - 2026-11-12

Not released (the CI of this version was red); its changes are listed under 2.1007.0.

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.1007.0...HEAD
[2.1007.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.1007.0
[2.1001.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.1001.0
