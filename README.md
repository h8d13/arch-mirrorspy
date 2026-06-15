# mirrorpy (std only)

Django-free reimplementation of archweb's mirrors JSON API, shipped as
per-file patches over [upstream](https://github.com/archlinux/archweb) `mirrors/`.

- `./archwebmirr` 
> fetch upstream `mirrors/` and apply `patches/`
- `./gen-patches` 
> regenerate `patches/` after editing `mirrors/standalone/`.

Then load data and serve (`--check` also runs via `.gitlab-ci.yml`, ~15 min):

```sh
python -m mirrors.standalone.app --db mirrors.db --init --import-urls  # ~1.2k mirrors
python -m mirrors.standalone.app --db mirrors.db --check               # poll lastsync
python -m mirrors.standalone.app --db mirrors.db --serve               # JSON API
```
