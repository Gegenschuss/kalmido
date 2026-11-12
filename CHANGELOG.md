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

## [2.1001.0] - 2026-11-12

Package 2.1001 (Bündel: Sammelpaket: Aufgaben ohne Paket (Dispatcher)).
### Security
- #5669: sharing a list or a list folder by e-mail address binds only an account that proved the address (the core helper used by tables and wiki since #5643); an address nobody proved is answered like an unknown address and reaches nobody. The address path is decided once per request, and its answer carries nothing account-specific.

[Unreleased]: https://github.com/Gegenschuss/kalmido/compare/v2.1001.0...HEAD
[2.1001.0]: https://github.com/Gegenschuss/kalmido/releases/tag/v2.1001.0
