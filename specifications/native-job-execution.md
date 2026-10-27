# Native systemd job execution and receiving

## Work, ownership and scope

This engineering contract serves original MetroPlat engineering-delivery Work
`ni:///sha-256;ylvMNgq1vmF8vC0VCLir3C4XOKesE_9ztrVbXC5ggWQ`,
`task:qualify-native-code-worker-lifecycle`, and its original source QA/estate
consumers. The Linux source index already assigns this systemd section to
`red-cup-engineering/systemd-engineering-services-section`. Its only current die,
`systemd-unit-inventory-observation-service`, promises read-only observation.
That contract must remain read-only. A new independently hireable job-execution
die, if justified by native receiving, belongs in this existing OS family and
must have its own source repository/package; no section-wide runtime or shadow
process loop belongs in Code, an inventory service or each agent harness.
This document and controlled native fixtures are engineering qualification,
not an active new service, package release, deployment or completed CI.

## Source evidence and requirement

Code source at d49abb06c3368f1e730285ea0fcad375a2e55426 uses a live-parent
process-group executor. It arms options.timeout unconditionally and polls group
absence after sending SIGKILL for two seconds. A descendant can create another
process group; direct child close and disappearance of its former process group
cannot prove that descendant stopped. Code's frozen receiver additionally has
clock memory-wait/admission/install bounds, and its sealed build ticket requires
a timeout. Agent carriers independently implement unit/artifact polling and hour
deadlines. All these caller contracts need deliberate receiving; removing a
single timer or adding a provider label cannot qualify their execution.

The existing execute-javascript-node-command-service 0.3.1 asynchronous port
already omits its timer when timeoutMilliseconds is absent. It runs a literal
argv without a shell and can carry a systemd-run client. Its current receipt
reports direct child close, not cgroup quiescence. Reuse this command transport;
do not broaden what its existing receipt proves.

The actual host user manager and tools report systemd255.4-1ubuntu8.17.
Systemd255 documents ExitType=cgroup, synchronous --wait, --pipe and --collect.
The configured agent-work.slice is loaded and has an actual MemoryMax. Native
source/manager/kernel receiving must verify these facts at use; a caller's
provider name, namespace, fabricated PID, timeout value or success flag is not
that evidence. No machine configuration is changed by these controlled checks.

## SRS

R1. A job begins only after its original source/effect/resource admission. The
provider executes one exact absolute programme/argv/env/directory request in an
owned transient service and actual admitted slice. It shall not use a shell,
silently rewrite argv/environment, start a timer unit or fall back to unmanaged
execution. Variable expansion is disabled. Runtime/start/stop deadlines shall
not be synthesized; managed test units explicitly use infinity for these three
properties, Restart=no and Type=exec. Real resource limits and explicit caller
cancellation remain independent of artificial time/token/tool/turn ceilings.

R2. Completion shall be driven by native managed-job termination with
ExitType=cgroup. A direct main-process exit or pipe closure shall not settle a
job while a descendant is alive, including a setsid/detached descendant. Stdio
content or an application-written marker does not establish exit/quiescence.
Observe and retain actual unit, InvocationID, kernel boot and control-group
identity. Hold native wait/identity resources rather than polling by elapsed
clock. Unit-name reuse or a different invocation must never authorize stopping,
settling or relaunching another job.

R3. Cancellation acts on the original admitted job, not only the systemd-run
client or a potentially reused PID/group name. Receive an original cgroup.kill
file descriptor while that group belongs to the identified invocation, before
releasing admitted work. Writing it cancels that group atomically, including
its detached descendants; await native quiescence. Preserve the current Code
hard-cancel intent. If this capability cannot be received, refuse the stronger
execution profile rather than asserting it from a string or weaker fallback.
The provider may use an authenticated gated bootstrap before the payload: its
initial IPC identity is matched to actual manager/procfs identity, the existing
listening endpoint closes to new connections before payload activation, and
private provider handles are not inherited by the payload.

R4. Observer/client failure is a distinct state. A dead systemd-run client does
not prove the unit is stopped. Preserve exact invocation, controlled group,
source, evidence and reservation; do not clean live staging, invent an exit
marker, retry/restart on elapsed time or upgrade live-parent into restartable
custody. Persistent recovery needs its own genuine admitted provider contract.
Native evidence error cannot become success; preserve the original failure and
secondary evidence failures. Uncertain state remains explicit until actual
native state or receiving changes it.

R5. Native containment and real resource admission remain mandatory. Preserve
actual source/effect writable lanes, readonly filesystem/home, no unconfined
fallback, controlled group protection and the applicable actual network/tool
capabilities. The controlled fixtures use PrivateNetwork/PrivateTmp, readonly
filesystem/home, ProtectControlGroups and an inaccessible host user-bus socket;
they connect only through a privately owned Unix socket. Real callers require
source-owned profiles, not a hardcoded host, guessed scope or blanket expansion
of authority. Job completion does not discharge separately delegated external
Work/effects. The existing inventory die and its authority stay read-only.

R6. Code's fixed maker, executor and receiver must be changed together before
this stronger profile is activated there. Replace the unconditional deadline
requirement with the genuine received execution-provider contract. Preserve
source hashes/modes, fixed semantic command grammar, consumer input custody,
immutable dependency/QA products and unforgeable Code capabilities. A raw caller
callback or JSON provider label cannot mint them. Source/native controls,
registry publication, installed programme and operating CI remain separate.

R7. Resource admission shall use actual resource/slot readiness. A contended
source receiver returns a typed deferred observation before launching, or waits
on its genuine native resource event/lock. It shall not sleep five seconds and
repeat pressure reads, synthesize an admission expiry or drop uncertain leases.
Keep original Work dependencies and event-driven readiness; do not create a
second Work queue. Agent carriers require separate lawful model/quota/office
and confinement receiving before using this lower-layer resource.

## HLD

Code declares its worker/receiving capability requirement. The machine owner
binds an independently qualified native OS job resource from this systemd family.
The existing Node-command asynchronous transport carries literal native clients;
a provider-aware adapter supplies actual unit/cgroup identity, cancellation and
completion evidence. System-engine/Work composition conveys real source/effect
and resource authority; no dependency from generic Code back into host systems
is introduced. Code and harnesses consume the shared native job contract; neither
owns another systemctl polling loop or independent OS process interpretation.

Lifecycle states are prepared, starting, admitted-running, cancelling,
quiescent, refused and uncertain. Cancellation can latch before admission;
already cancelled requests do not launch. Before any payload instruction, an
owned bootstrap handshake permits actual InvocationID/ControlGroup/ExecMainPID
and source/profile verification and retention of the original cancellation
handle. A start refusal does not trigger unmanaged fallback. A held native wait
completes the managed unit. A failed observer retains its original live job;
source evidence and final product receiving remain independent. An external
caller restart or missing response never buys another attempt by itself.

## LLD and independent native qualification

First receive the kernel/provider behavior with controlled fixtures, before
writing or activating the reusable execution die. The Node fixture has parent
and detached-child modes and exchanges readiness/control over a private Unix
socket. It reports its actual PID, process group where observable, boot,
INVOCATION_ID and /proc/self/cgroup. It never uses delays or spawns another task
except its one declared detached fixture child. The parent waits for explicit
exit-main; the detached child waits for explicit release-child. Both are benign
and idle. Their I/O and owned runtime socket keep their lives observable.

The native controller uses Python3.12 os.pidfd_open and selectors/select for
actual process exit and socket/client readiness. No sleeps, timers, timeout
arguments or polling loops. A kernel pidfd is acquired while the controlled
process is held alive at its handshake, before the controller allows it to
exit. Client termination participates in the same readiness set so a failed
start cannot strand a socket accept. Use the pinned actual Node programme,
source-digested fixture, one random owned unit name per case, the existing
admitted slice, and only actual source-owned runtime/temp evidence paths.

Required managed-unit properties for these probes are Type=exec,
ExitType=cgroup, Restart=no, KillMode=control-group, KillSignal=SIGKILL,
RuntimeMaxSec=infinity, TimeoutStartSec=infinity, TimeoutStopSec=infinity,
PrivateUsers=yes, ProtectSystem=strict, ProtectHome=read-only, ProtectControlGroups=yes,
PrivateTmp=yes, PrivateNetwork=yes, InaccessiblePaths for this user's actual
bus, and ReadWritePaths restricted to the owned runtime socket directory.
Use systemd-run --user --wait --pipe --collect --expand-environment=no with the
actual existing slice. It does not install/enable a unit or change host limits.
Refuse an absent/unqualified slice. The systemd-run child and both fixture PIDs
have genuine kernel exit handles; observe actual properties before releasing
work. stdout/stderr and complete native facts remain in the owning evidence.

C1 natural completion: acquire live parent/child pidfds; command only the main
process to exit; await its native pidfd. The systemd-run client must remain alive
and the actual unit/group must still contain the child. Release the child; await
its pidfd and the client; the native job succeeds only then. This is not a
latency check, sleep or marker-based guess.

C2 cancellation: receive the exact original cgroup.kill descriptor and verified
unit invocation while both fixture processes are held. Cancel by writing it.
Both processes and the native waiter must terminate; record non-success and
native group quiescence. Never kill a name-matched unrelated unit.

C3 observer loss: kill only the controlled systemd-run client through its held
Popen handle. Its exit must not make the still-live fixture job successful or
quiescent. Preserve the original identity, then clean up through the original
group descriptor and observe both actual process exits. No second job or retry.

Cleanup is only for this case's known original job. If no bootstrap arrived,
actual native manager properties must match the unique attempt description,
exact intended execution and expected slice/group before cleanup. Unknown or
mismatched identity is retained as uncertainty, never stopped by a broad prefix.
Do not remove owned runtime/staging while a fixture may remain alive. Terminal
inactive/not-found observations and native pidfd/client results are evidence;
absence of a marker or an observation timeout is not.

The independent receiver reviews generated fixture/controller source before
allowing any native launch. Nonpremium construction gets real source, exact
edit tools and syntax tools; it does not run privileged/native effects before
that receiving. Complete transcripts/facts, actual exit handles and verified
source/profile identities—not a model's allPassed flag—support acceptance.
This qualification does not publish a service, activate Code/harness workers,
claim a persistent provider or close original private CI/estate obligations.

## Primary references

https://www.freedesktop.org/software/systemd/man/255/systemd.service.html
https://www.freedesktop.org/software/systemd/man/255/systemd-run.html
https://www.freedesktop.org/software/systemd/man/255/systemd.kill.html
https://docs.kernel.org/admin-guide/cgroup-v2.html
https://docs.python.org/3.12/library/os.html#os.pidfd_open

Native systemd, kernel and Python versions/capabilities must be received on the
actual host. Source references and design intent alone do not prove them.

The actual Python3.12.3 exposes os.pidfd_open. Source systemd255 documentation
requires user namespaces for mount/network sandboxing in a per-user manager;
PrivateUsers=yes is therefore explicit in the controlled profile. An actual
namespace admission failure must remain a native refusal, never permission to
disable confinement or change kernel configuration by hand. The native host
configuration services own any separately justified machine prerequisite.

## Received prerequisite; remaining qualification

On Bare Cedar Fog on 2026-10-27, the existing independently installed
execute-javascript-node-command-service 0.3.1 asynchronous port carried one
literal systemd-run command running /usr/bin/true. It used all confinement
properties specified above, the existing agent-work.slice, --wait/--collect,
and no artificial execution deadline. Its native receipt reports status 0,
result success, actual invocation 5e7f54d1c6284190b1c4248289340f6a.
The host owns the complete request and receipt; receipt identity:

`ni:///sha-256;11DqyXRFlz6VnSQyarlK1_qMo6GMzBXcAzvGsL61mdY`

This receives only native launch/confinement compatibility for that benign
command. C1/C2/C3, original cgroup cancellation, descendant quiescence, observer
loss, reusable execution-die construction and Code consumer activation remain
unreceived. Independently refused generated fixtures are not part of this
source publication. A model delivery or this prerequisite must not satisfy
those remaining controls.
