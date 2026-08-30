# SuperYosh23 Repo

Personal Cydia / Sileo repo hosted on GitHub Pages.

## Add to Cydia / Sileo

Add the source:

```
https://superyosh23.github.io/repo/
```

## Packages

- **LegacyMusic** — a YouTube music client for legacy iOS (6.0+, armv7).

## Adding a new build

1. Put the `.deb` into `debs/`.
2. Commit and push to `main`.
3. GitHub Actions regenerates `Packages` / `Packages.bz2` / `Packages.gz` / `Release` automatically.

To rebuild manually:

```
python3 build_repo.py
```