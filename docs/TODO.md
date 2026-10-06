# TODO

- [x] Option to glue videos uploaded via multiple upload into one file: when several files are uploaded, ask for confirmation — output a single glued file or separate files
- [x] dock-server holds ~575 MB of commit at idle because launcher/cli import GUI + numpy/OpenBLAS before dispatching; dispatch `dock-server` before any heavy import (the `OPENBLAS_NUM_THREADS` cap was rejected: dock children inherit its environment) — handoff: docs/plans/20261006-dock-server-openblas-commit.md
