# Native lifecycle qualification

The source-owned contract is [native-job-execution.md](../../specifications/native-job-execution.md).
These controlled fixtures receive Linux/systemd behavior before an independently
owned execution die or consumer activation is admitted.

`qualify.py` requires Python with `os.pidfd_open` and
`signal.pidfd_send_signal`, the qualified systemd user manager and its literal
native tools, unified cgroup-v2, and an existing owner-admitted slice.
`fixture.mjs` requires the actual pinned Node programme. The caller supplies:

- `--node`: its absolute programme path;
- `--fixture`: the absolute path to this exact reviewed fixture;
- `--slice`: the existing owner-admitted slice;
- `--evidence`: a new absolute filename in an existing caller-owned directory.

The receipt and adjacent `.jsonl` journal are exclusive new files. The journal
retains original request/source identity before launch and native identity
before controlled release. The controller performs all three cases using one
owned lifecycle: detached-descendant completion, original-group cancellation,
and observer loss followed by owned cleanup. Waits follow actual pidfd and
cgroup events; immediate readiness snapshots impose no wait bound.

Receive the literal command receipt and evidence together. Verify exact source,
native properties and process/group events, actual observer results, primary
and cleanup errors, and owned resource retirement. A model report or aggregate
`passed` field is insufficient. A failed or uncertain case stops further
launches and retains its evidence. Existing artifacts are never overwritten.

The qualified host run receives these three controlled behaviors only. The
inventory service stays read-only; no permanent unit, machine configuration,
production executor, Code capability or persistent provider is installed here.
