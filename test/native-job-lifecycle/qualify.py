"""Controlled native receiving, not a production job executor or work queue."""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import select
import selectors
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import uuid


class ReceivingRefusal(RuntimeError):
    pass


PROFILE = {
    "Type": "exec", "ExitType": "cgroup", "Restart": "no",
    "KillMode": "control-group", "KillSignal": "SIGKILL",
    "RuntimeMaxSec": "infinity", "TimeoutStartSec": "infinity",
    "TimeoutStopSec": "infinity", "PrivateUsers": "yes",
    "ProtectSystem": "strict", "ProtectHome": "read-only",
    "ProtectControlGroups": "yes", "PrivateTmp": "yes", "PrivateNetwork": "yes",
}
OBSERVED_PROFILE = {
    **{k: v for k, v in PROFILE.items() if not k.endswith("Sec")},
    "KillSignal": str(int(signal.SIGKILL)),
    "RuntimeMaxUSec": "infinity", "TimeoutStartUSec": "infinity",
    "TimeoutStopUSec": "infinity",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NativeCase:
    def __init__(self, args, name):
        self.args, self.name = args, name
        self.unit = "native-job-qualify-" + str(uuid.uuid4()) + ".service"
        self.description = "Owned native lifecycle qualification " + self.unit
        self.record = {"case": name, "unit": self.unit, "status": "unreceived",
                       "checks": [], "events": [], "cleanupErrors": []}
        self.runtime = self.server = self.proc = None
        self.logs, self.connections, self.roles, self.fds = {}, [], {}, {}
        self.identity = None
        self.group_attempted = self.group_received = False
        self.cgdir = self.killfd = self.eventsfd = None
        self.quiescent = False

    def check(self, condition, claim):
        self.record["checks"].append({"claim": claim, "received": bool(condition)})
        if not condition:
            raise ReceivingRefusal(claim)

    def journal(self, event, facts):
        self.args.journal.write(json.dumps({"case": self.name, "unit": self.unit,
                                           "event": event, "facts": facts}) + "\n")
        self.args.journal.flush()
        os.fsync(self.args.journal.fileno())

    def observe(self, argv):
        result = subprocess.run(argv, capture_output=True, text=True)
        self.record["events"].append({"operation": "native-observation", "argv": argv,
                                      "status": result.returncode,
                                      "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode:
            raise ReceivingRefusal("Native observation refused: " + argv[0])
        return result.stdout

    def show(self, unit, names):
        raw = self.observe(["/usr/bin/systemctl", "--user", "show", "--no-pager",
                            "--property=" + ",".join(names), unit])
        return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)

    def typed_execution(self):
        native = "org.freedesktop.systemd1"
        unit = json.loads(self.observe([
            "/usr/bin/busctl", "--user", "--json=short", "call", native,
            "/org/freedesktop/systemd1", native + ".Manager", "GetUnit", "s", self.unit]))
        self.check(unit.get("type") == "o" and len(unit.get("data", [])) == 1,
                   "GetUnit supplied one typed native object")
        execution = json.loads(self.observe([
            "/usr/bin/busctl", "--user", "--json=short", "get-property", native,
            unit["data"][0], native + ".Service", "ExecStart"]))
        self.check(execution.get("type") == "a(sasbttttuii)" and len(execution.get("data", [])) == 1,
                   "ExecStart supplied the qualified systemd255 typed tuple")
        return execution["data"][0]

    def retain_pid(self, role, pid):
        if role not in self.fds:
            self.fds[role] = os.pidfd_open(pid, 0)
            self.record["events"].append({"operation": "retain-pidfd", "role": role, "pid": pid})
        return self.fds[role]

    def ready(self, role):
        probe = select.poll()
        probe.register(self.fds[role], select.POLLIN)
        observed = probe.poll(0)  # One current-state snapshot; no elapsed wait or retry.
        if observed:
            self.check(bool(observed[0][1] & select.POLLIN), "Retained pidfd is valid: " + role)
        return bool(observed)

    def await_processes(self, roles):
        pending = {self.fds[role]: role for role in roles}
        waiter = select.poll()
        for fd in pending:
            waiter.register(fd, select.POLLIN)
        while pending:
            for fd, mask in waiter.poll():
                self.check(bool(mask & select.POLLIN), "Native process exit event: " + pending[fd])
                self.record["events"].append({"operation": "pidfd-exited", "role": pending.pop(fd)})
                waiter.unregister(fd)

    def receive_original_group(self):
        if self.group_received:
            return
        self.check(not self.group_attempted, "A refused native group capability is not silently reacquired")
        self.group_attempted = True
        names = ["LoadState", "InvocationID", "ControlGroup", "Description", "Slice",
                 "ExecMainPID", "InaccessiblePaths", "ReadWritePaths", *OBSERVED_PROFILE]
        actual = self.show(self.unit, names)
        execution = self.typed_execution()
        expected_group = self.slice["ControlGroup"] + "/" + self.unit
        self.check(actual.get("LoadState") == "loaded", "Original transient unit is loaded")
        self.check(actual.get("Description") == self.description, "Unique original description matches")
        self.check(actual.get("Slice") == self.args.slice, "Original admitted slice matches")
        self.check(actual.get("ControlGroup") == expected_group, "Original native group is in that slice")
        self.check(bool(re.fullmatch("[0-9a-f]{32}", actual.get("InvocationID", ""))),
                   "Native invocation identity is present")
        self.check(execution[0] == self.args.node and execution[1] == self.payload and execution[2] is False,
                   "Typed native executable and entire literal argv match owned request")
        self.identity = actual
        self.record["identity"] = {**actual, "boot_id": self.boot, "typedExecStart": execution}
        path = Path("/sys/fs/cgroup") / expected_group.lstrip("/")
        self.cgdir = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.eventsfd = os.open("cgroup.events", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.cgdir)
        self.record["groupHandle"] = {"device": os.fstat(self.cgdir).st_dev,
                                      "inode": os.fstat(self.cgdir).st_ino}
        self.killfd = os.open("cgroup.kill", os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.cgdir)
        current = self.show(self.unit, ["InvocationID", "ControlGroup"])
        self.check(current.get("InvocationID") == actual["InvocationID"] and current.get("ControlGroup") == expected_group,
                   "Original invocation still matches after kernel handle acquisition")
        self.group_received = True
        self.retain_pid("main", int(actual["ExecMainPID"]))
        self.journal("received-original-native-identity",
                     {"identity": self.record["identity"], "groupHandle": self.record["groupHandle"]})

    def receive_profile(self):
        for key, expected in OBSERVED_PROFILE.items():
            self.check(self.identity.get(key) == expected, "Native profile " + key + "=" + expected)
        self.check(set(self.identity.get("InaccessiblePaths", "").split()) == set(self.inaccessible),
                   "Actual user bus and private manager runtime are inaccessible inside the fixture")
        self.check(self.identity.get("ReadWritePaths") == str(self.runtime),
                   "Only owned runtime is a writable exception")

    def hello(self, connection, message):
        self.check(isinstance(message, dict) and message.get("event") == "ready", "One actual ready object")
        role = message.get("role")
        self.check(role in ("parent", "child") and role not in self.roles, "Unique declared fixture role")
        pid, uid, _gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        self.check(message.get("pid") == pid and uid == os.getuid(), "Actual Unix peer identity matches handshake")
        self.receive_original_group()
        actual_group = Path(f"/proc/{pid}/cgroup").read_text().strip()
        parent = int(next(line.split()[1] for line in Path(f"/proc/{pid}/status").read_text().splitlines() if line.startswith("PPid:")))
        self.check(message.get("boot_id") == self.boot, "Actual fixture boot identity matches")
        self.check(message.get("invocation_id") == self.identity["InvocationID"], "Actual fixture invocation matches manager")
        self.check(actual_group == "0::" + self.identity["ControlGroup"],
                   "Actual host-view procfs group matches original managed job")
        namespace = os.readlink(f"/proc/{pid}/ns/cgroup")
        controller_namespace = os.readlink("/proc/self/ns/cgroup")
        self.check(isinstance(message.get("cgroup"), str) and message["cgroup"].strip().startswith("0::/"),
                   "Fixture reports an actual unified-cgroup view")
        if namespace == controller_namespace:
            self.check(message["cgroup"].strip() == actual_group, "Same-namespace fixture group agrees with host view")
        self.record["events"].append({"operation": "cgroup-namespace-views", "pid": pid,
                                      "fixtureNamespace": namespace, "controllerNamespace": controller_namespace,
                                      "fixtureView": message["cgroup"], "controllerView": actual_group})
        self.check(message.get("ppid") == parent, "Reported parent matches actual procfs parent")
        if role == "parent":
            self.check(pid == int(self.identity["ExecMainPID"]), "Parent is the actual native main process")
        else:
            self.check(parent == int(self.identity["ExecMainPID"]), "Detached fixture is the original main process child")
            self.check(os.getpgid(pid) == pid and os.getsid(pid) == pid,
                       "Actual child detached into its own process group and session")
            self.retain_pid("child", pid)
        self.roles[role] = {"socket": connection, "message": message}
        self.record["events"].append({"operation": "received-peer", "identity": message})

    def start(self):
        self.boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        self.slice = self.show(self.args.slice, ["LoadState", "ControlGroup", "MemoryMax"])
        self.check(self.slice.get("LoadState") == "loaded" and self.slice.get("ControlGroup", "").startswith("/"),
                   "Actual admitted slice is loaded with a native control group")
        self.record["slice"] = self.slice
        base = Path(os.environ["XDG_RUNTIME_DIR"]).resolve()
        self.check(not any(c.isspace() for c in str(base)), "Native path-list properties have a literal unambiguous runtime path")
        self.runtime = Path(tempfile.mkdtemp(prefix="native-job-", dir=base))
        address = str(self.runtime / "control.sock")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(address)
        self.server.listen()
        self.server.setblocking(False)
        self.payload = [self.args.node, self.args.fixture, address, "parent"]
        self.inaccessible = [str(base / "bus"), str(base / "systemd")]
        properties = {**PROFILE, "InaccessiblePaths": " ".join(self.inaccessible), "ReadWritePaths": str(self.runtime)}
        argv = ["/usr/bin/systemd-run", "--user", "--wait", "--pipe", "--collect", "--expand-environment=no",
                "--unit=" + self.unit, "--description=" + self.description, "--slice=" + self.args.slice,
                *["--property=" + k + "=" + v for k, v in properties.items()], *self.payload]
        self.record.update({"argv": argv, "expectedProperties": properties, "runtime": str(self.runtime),
                            "fixtureSHA256": digest(self.args.fixture), "controllerSHA256": digest(__file__)})
        for stream in ("stdout", "stderr"):
            self.logs[stream] = open(self.runtime / stream, "w+b", buffering=0)
        self.journal("prepared-owned-launch", {"controllerPid": os.getpid(), "boot_id": self.boot,
                                               "request": self.record})
        self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=self.logs["stdout"], stderr=self.logs["stderr"])
        self.retain_pid("observer", self.proc.pid)
        buffers = {}
        with selectors.DefaultSelector() as events:
            events.register(self.server, selectors.EVENT_READ, "listener")
            events.register(self.fds["observer"], selectors.EVENT_READ, "observer-exit")
            registered = {self.fds["observer"]}
            while len(self.roles) != 2:
                for key, _mask in events.select():
                    if key.data == "listener":
                        connection, _ = self.server.accept()
                        connection.setblocking(False)
                        self.connections.append(connection)
                        buffers[connection] = b""
                        events.register(connection, selectors.EVENT_READ, connection)
                    elif isinstance(key.data, str):
                        raise ReceivingRefusal("Native process exited before bootstrap completed: " + key.data)
                    else:
                        connection = key.data
                        chunk = connection.recv(65536)
                        self.check(bool(chunk), "Fixture connection stays live until admitted control")
                        buffers[connection] += chunk
                        if b"\n" not in buffers[connection]:
                            continue
                        line, rest = buffers[connection].split(b"\n", 1)
                        self.check(not rest, "Only one readiness frame precedes admission")
                        self.hello(connection, json.loads(line.decode("utf-8")))
                        events.unregister(connection)
                        for role, fd in self.fds.items():
                            if fd not in registered:
                                events.register(fd, selectors.EVENT_READ, role + "-exit")
                                registered.add(fd)
        self.server.close()
        self.server = None
        self.check(self.roles["parent"]["message"].get("child_pid") == self.roles["child"]["message"]["pid"],
                   "Actual spawn child identity matches independently received child")
        self.receive_profile()
        for role in ("main", "child", "observer"):
            self.check(not self.ready(role), "Original native process is held alive at admission: " + role)
        self.record["state"] = "admitted-running"
        self.journal("received-controlled-fixtures", {role: value["message"] for role, value in self.roles.items()})

    def population(self):
        try:
            os.lseek(self.eventsfd, 0, os.SEEK_SET)
            chunks = []
            while True:
                chunk = os.read(self.eventsfd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError as error:
            if error.errno != errno.ENODEV:
                raise
            original = os.fstat(self.cgdir)
            self.check((original.st_dev, original.st_ino) ==
                       (self.record["groupHandle"]["device"], self.record["groupHandle"]["inode"]),
                       "Offline core file belongs to the retained original kernel group")
            self.check(all(role in self.fds and self.ready(role) for role in ("main", "child")),
                       "Both original fixture processes exited before interpreting original core-group deactivation")
            # cgroup.events has no custom ENODEV result: kernfs returns it after
            # core-file deactivation. cgroup_destroy_locked refuses populated
            # groups/live children. Directory st_nlink is not this contract.
            self.record["events"].append({"operation": "original-core-group-offline", "errno": error.errno,
                                          "device": original.st_dev, "inode": original.st_ino,
                                          "links": original.st_nlink})
            return 0
        data = b"".join(chunks).decode("ascii")
        values = dict(line.split() for line in data.splitlines())
        self.check(values.get("populated") in ("0", "1"), "Original kernel group supplied population state")
        self.record["events"].append({"operation": "original-group-events", "contents": data})
        return int(values["populated"])

    def await_quiescence(self):
        events = select.poll()
        events.register(self.eventsfd, select.POLLPRI | select.POLLERR)
        while self.population():
            for _fd, mask in events.poll():  # Native notification; no scheduled reread.
                self.check(not (mask & select.POLLNVAL)
                           and bool(mask & (select.POLLPRI | select.POLLERR | select.POLLHUP)),
                           "Valid original kernel group event notification")
        self.quiescent = True
        self.record["quiescent"] = True

    def send(self, role, action):
        self.roles[role]["socket"].setblocking(True)
        self.roles[role]["socket"].sendall((json.dumps({"action": action}) + "\n").encode())
        self.record["events"].append({"operation": "fixture-control", "role": role, "action": action})

    def cancel_original(self):
        self.check(self.group_received and self.killfd is not None,
                   "Original received group cancellation descriptor exists")
        os.write(self.killfd, b"1\n")
        self.record["events"].append({"operation": "original-cgroup-kill", "identity": self.record["groupHandle"]})

    def run_transition(self):
        if self.name == "C1":
            self.send("parent", "exit-main")
            self.await_processes(["main"])
            self.check(not self.ready("child") and not self.ready("observer") and self.population() == 1,
                       "Main exit leaves actual detached child and native waiter live in populated original group")
            self.send("child", "release-child")
            self.await_processes(["child", "observer"])
            self.await_quiescence()
            self.check(self.proc.wait() == 0, "Native managed job succeeds only after detached child exits")
            self.record["jobOutcome"] = "succeeded"
        elif self.name == "C2":
            self.cancel_original()
            self.await_processes(["main", "child", "observer"])
            self.await_quiescence()
            self.check(self.proc.wait() != 0, "Original-group cancellation is non-success")
            self.record["jobOutcome"] = "cancelled"
        else:
            signal.pidfd_send_signal(self.fds["observer"], signal.SIGKILL)
            self.await_processes(["observer"])
            self.check(self.proc.wait() == -signal.SIGKILL, "Only original native observer was killed")
            self.check(not self.ready("main") and not self.ready("child") and self.population() == 1,
                       "Observer exit leaves actual original fixture job live and unsettled")
            self.record["observerLossState"] = "uncertain-live"
            self.cancel_original()
            self.await_processes(["main", "child"])
            self.await_quiescence()
            self.record["jobOutcome"] = "quiescent-after-owned-cleanup; observer-completion-unreceived"
        self.check(digest(self.args.fixture) == self.record["fixtureSHA256"], "Qualified fixture source remains unchanged")
        self.record["status"] = "passed"

    def cleanup(self):
        try:
            if self.proc is not None and not self.quiescent:
                self.receive_original_group()
                if self.population():
                    self.cancel_original()
                    self.await_processes([role for role in ("main", "child") if role in self.fds])
                self.await_quiescence()
            if self.proc is not None and self.quiescent:
                if not self.ready("observer"):
                    signal.pidfd_send_signal(self.fds["observer"], signal.SIGKILL)
                    self.record["events"].append({"operation": "cleanup-original-observer-after-group-quiescence"})
                self.await_processes(["observer"])
                self.record["observerStatus"] = self.proc.wait()
        except BaseException as error:
            self.cleanup_failure("original-job", error)
        finally:
            for stream, handle in self.logs.items():
                try:
                    handle.seek(0)
                    self.record[stream] = handle.read().decode("utf-8", errors="replace")
                except BaseException as error:
                    self.cleanup_failure("receive-" + stream, error)
                self.close_resource(handle.close, "close-" + stream)
            for connection in self.connections:
                self.close_resource(connection.close, "close-fixture-socket")
            if self.server is not None:
                self.close_resource(self.server.close, "close-listener")
            for fd in [*self.fds.values(), self.killfd, self.eventsfd, self.cgdir]:
                if fd is not None:
                    self.close_resource(lambda fd=fd: os.close(fd), "close-native-descriptor")
            if self.runtime is not None and (self.proc is None or self.quiescent):
                try:
                    for name in ("control.sock", "stdout", "stderr"):
                        (self.runtime / name).unlink(missing_ok=True)
                    self.runtime.rmdir()
                    self.record["ownedRuntimeRemoved"] = True
                except OSError as error:
                    self.cleanup_failure("remove-owned-runtime", error)
            else:
                self.record["ownedRuntimeRetained"] = self.runtime is not None

    def cleanup_failure(self, phase, error):
        self.record["cleanupErrors"].append({"phase": phase, "error": repr(error)})
        self.record["status"] = "uncertain"

    def close_resource(self, close, phase):
        try:
            close()
        except BaseException as error:
            self.cleanup_failure(phase, error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("node", "fixture", "slice", "evidence"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    for name in ("node", "fixture"):
        path = Path(getattr(args, name))
        if not path.is_absolute() or not path.is_file():
            parser.error("--" + name + " requires an actual absolute programme/source path")
    evidence = {"scope": "Controlled C1/C2/C3 native lifecycle qualification only",
                "python": sys.version, "cases": [], "status": "unreceived"}
    args.journal = open(args.evidence + ".jsonl", "x", encoding="utf-8")
    def cancel(signum, _frame):
        raise KeyboardInterrupt("Caller signal " + str(signum))
    signal.signal(signal.SIGTERM, cancel)
    try:
        for name in ("C1", "C2", "C3"):
            case = NativeCase(args, name)
            try:
                case.start()
                case.run_transition()
            except BaseException as error:
                case.record["primaryFailure"] = repr(error)
                case.record["status"] = "refused"
            finally:
                case.cleanup()
                evidence["cases"].append(case.record)
                try:
                    case.journal("received-case-outcome", case.record)
                except OSError as error:
                    case.cleanup_failure("receive-case-journal", error)
            if case.record["status"] != "passed":
                break
        evidence["status"] = "passed" if len(evidence["cases"]) == 3 and all(c["status"] == "passed" for c in evidence["cases"]) else "unreceived"
    finally:
        try:
            args.journal.close()
        except OSError as error:
            evidence["journalCloseFailure"] = repr(error)
            evidence["status"] = "unreceived"
        try:
            with open(args.evidence, "x", encoding="utf-8") as output:
                json.dump(evidence, output, indent=2)
                output.write("\n")
        except OSError as error:
            evidence["evidenceWriteFailure"] = repr(error)
            evidence["status"] = "unreceived"
        print(json.dumps(evidence))
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
