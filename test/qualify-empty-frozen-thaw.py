#!/usr/bin/env python3
"""Private-container regression for the original empty frozen manager state."""
import hashlib
import json
import os
import pathlib
import select
import signal
import socket
import struct
import subprocess
import sys

mode = sys.argv[1]
assert mode in ("baseline", "patched")
root = pathlib.Path("/run") / ("rce-empty-thaw-" + str(os.getpid()))
root.mkdir(mode=0o700)
unit = "rce-empty-thaw-" + str(os.getpid()) + ".service"
marker = root / "publisher-runtime.pending"
path = root / unit
fields = "MainPID,ControlPID,ExecMainPID,ActiveState,SubState,FreezerState,ControlGroup,InvocationID,Job,Result,ExecCondition"
report = {"controllerSha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(), "kind": "rce.systemd-empty-frozen-thaw/v1", "mode": mode, "unit": unit,
          "boot": pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
          "cgroupNamespace": os.readlink("/proc/self/ns/cgroup"),
          "managerCgroupNamespace": os.readlink("/proc/1/ns/cgroup")}
assert report["cgroupNamespace"] == report["managerCgroupNamespace"]

def run(*args, check=True):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)

def observe():
    text = run("systemctl", "show", unit, "--property=" + fields).stdout
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

notify = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
notify.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
notify.bind(str(root / "monitor.notify"))
env = dict(os.environ, NOTIFY_SOCKET=str(root / "monitor.notify"))
monitor = subprocess.Popen(["busctl", "--json=short", "monitor", "org.freedesktop.systemd1"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
monitor_pidfd = os.pidfd_open(monitor.pid)
pidfd = None
try:
    ready, _, _ = select.select([notify, monitor_pidfd], [], [])
    if monitor_pidfd in ready:
        raise RuntimeError("native observer exited before ready: " + monitor.stderr.read().decode())
    message, controls, _, _ = notify.recvmsg(4096, socket.CMSG_SPACE(struct.calcsize("3i")))
    credentials = [struct.unpack("3i", value) for level, kind, value in controls
                   if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS]
    assert credentials == [(monitor.pid, os.getuid(), os.getgid())]
    assert b"READY=1" in message

    def wait_native(predicate):
        while True:
            state = observe()
            if predicate(state):
                return state
            readable, _, _ = select.select([monitor.stdout, monitor_pidfd], [], [])
            if monitor_pidfd in readable:
                raise RuntimeError("native observer ended before receiving: " + monitor.stderr.read().decode())
            if not os.read(monitor.stdout.fileno(), 65536):
                raise RuntimeError("native observer stream closed before receiving")

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(root / "payload.ready"))
    listener.listen(1)
    main = root / "main.py"
    main.write_text("""import os,pathlib,signal,socket,sys
p=pathlib.Path(sys.argv[1])
n=int(p.read_text()) if p.exists() else 0
assert 0<=n<3
p.write_text(str(n+1))
def ready(role):
 s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
 s.connect(str(p.parent/'payload.ready'))
 s.sendall((role+' '+str(os.getpid())+'\\n').encode())
 s.close()
if len(sys.argv)>2:
 assert sys.argv[2]=='descendant'
 if os.fork()==0:
  os.setsid()
  ready('CHILD')
  signal.pause()
  os._exit(0)
ready('MAIN')
signal.pause()
""")
    os.chmod(main, 0o600)
    report["payloadSha256"] = hashlib.sha256(main.read_bytes()).hexdigest()
    original = ("[Unit]\nDescription=Owned empty-frozen manager qualification\n[Service]\nType=exec\n"
                "ExecStart=/usr/bin/python3 " + str(main) + " " + str(root / "count") + "\n"
                "Restart=on-failure\nRestartSec=0\nUMask=0077\n"
                "TimeoutStartSec=infinity\nTimeoutStopSec=infinity\n")
    path.write_text(original)
    os.chmod(path, 0o600)
    run("systemctl", "link", "--runtime", str(path))
    run("systemctl", "daemon-reload")
    run("systemctl", "start", unit)
    live = wait_native(lambda state: int(state["MainPID"]) > 0 and state["SubState"] == "running")
    pid = int(live["MainPID"])
    pidfd = os.pidfd_open(pid)
    argv = pathlib.Path("/proc", str(pid), "cmdline").read_bytes().split(b"\0")[:-1]
    assert argv == [b"/usr/bin/python3", str(main).encode(), str(root / "count").encode()]
    readable, _, _ = select.select([listener, pidfd, monitor_pidfd], [], [])
    assert listener in readable, "original payload or observer ended before readiness"
    connection, _ = listener.accept()
    peer = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
    assert peer == (pid, os.getuid(), os.getgid())
    payload_ready = b""
    while b"\n" not in payload_ready:
        piece = connection.recv(128)
        assert piece and len(payload_ready) + len(piece) <= 128
        payload_ready += piece
    assert payload_ready == ("MAIN " + str(pid) + "\n").encode()
    connection.close()
    listener.close()
    (root / "payload.ready").unlink()
    group = live["ControlGroup"]
    assert group.startswith("/") and ".." not in group.split("/")
    run("systemctl", "freeze", unit)
    frozen_live = observe()
    report["ownedPidfd"] = {"pid": pid, "nativeArgv": [x.decode() for x in argv], "readinessPeer": list(peer)}
    assert frozen_live["MainPID"] == live["MainPID"]
    assert frozen_live["InvocationID"] == live["InvocationID"]
    assert frozen_live["FreezerState"] == "frozen"
    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
    select.select([pidfd], [], [])
    frozen = wait_native(lambda state: state["MainPID"] == "0" and state["ControlPID"] == "0"
                         and state["FreezerState"] == "frozen")
    assert frozen["InvocationID"] == live["InvocationID"]
    original_group = pathlib.Path("/sys/fs/cgroup" + group)
    if original_group.exists():
        events = (original_group / "cgroup.events").read_text()
        assert "populated 0" in events.splitlines()
        report["originalGroup"] = {"path": group, "events": events}
    else:
        report["originalGroup"] = {"path": group, "absentAfterOriginalPidfdExit": True}
    with marker.open("x") as output:
        output.write("publisher runtime transition pending\n")
        output.flush()
        os.fsync(output.fileno())
    revised = original.replace("[Unit]\n", "[Unit]\nConditionPathExists=!" + str(marker) + "\n")
    revised = revised.replace("[Service]\n", "[Service]\nExecCondition=/usr/bin/test ! -e " + str(marker) + "\n")
    next_path = root / (unit + ".next")
    next_path.write_text(revised)
    os.chmod(next_path, 0o600)
    with next_path.open() as source:
        os.fsync(source.fileno())
    os.replace(next_path, path)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    os.fsync(directory)
    os.close(directory)
    run("systemctl", "daemon-reload")
    fenced = observe()
    assert fenced["MainPID"] == "0" and fenced["FreezerState"] == "frozen"
    assert fenced["InvocationID"] == live["InvocationID"]
    assert str(marker) in fenced["ExecCondition"]
    thaw = run("systemctl", "thaw", unit, check=False)
    report.update({"live": live, "frozen": frozen, "fenced": fenced,
                   "fenceSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "thaw": {"returncode": thaw.returncode, "stdout": thaw.stdout, "stderr": thaw.stderr}})
    if mode == "baseline":
        assert thaw.returncode != 0 and "Unit is not active" in thaw.stderr
        assert observe()["FreezerState"] == "frozen"
        report["verdict"] = "original-defect-reproduced"
    else:
        assert thaw.returncode == 0
        run("systemctl", "stop", unit)
        stopped = wait_native(lambda state: state["MainPID"] == "0" and state["ControlPID"] == "0"
                              and state["ActiveState"] in ("inactive", "failed")
                              and state["SubState"] in ("dead", "failed") and state["Job"] == "")
        assert stopped["FreezerState"] == "running"
        assert (root / "count").read_text() == "1"
        if original_group.exists():
            assert "populated 0" in (original_group / "cgroup.events").read_text().splitlines()
        report.update({"stopped": stopped, "mainInvocations": 1, "verdict": "corrected-native-thaw-received"})
        # Main loss while a controlled frozen descendant remains creates a
        # non-active populated unit without any artificial clock. THAW must
        # refuse it until both original pidfds report actual process exit.
        marker.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(root / "payload.ready"))
        listener.listen(2)
        with_descendant = revised.replace(str(root / "count") + "\n",
                                          str(root / "count") + " descendant\n")
        next_path.write_text(with_descendant)
        os.chmod(next_path, 0o600)
        os.replace(next_path, path)
        run("systemctl", "daemon-reload")
        run("systemctl", "start", unit)
        second = wait_native(lambda state: int(state["MainPID"]) > 0 and state["SubState"] == "running")
        second_pid = int(second["MainPID"])
        second_pidfd = os.pidfd_open(second_pid)
        child_pidfd = None
        roles = {}
        while len(roles) < 2:
            readable, _, _ = select.select([listener, second_pidfd, monitor_pidfd], [], [])
            assert listener in readable
            connection, _ = listener.accept()
            peer = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
            ready_bytes = b""
            while b"\n" not in ready_bytes:
                piece = connection.recv(128)
                assert piece and len(ready_bytes) + len(piece) <= 128
                ready_bytes += piece
            role, peer_pid = ready_bytes.decode().strip().split(" ")
            peer_pid = int(peer_pid)
            assert role in ("MAIN", "CHILD") and role not in roles
            assert peer == (peer_pid, os.getuid(), os.getgid())
            if role == "MAIN":
                assert peer_pid == second_pid
            else:
                child_pidfd = os.pidfd_open(peer_pid)
                status = pathlib.Path("/proc", str(peer_pid), "status").read_text().splitlines()
                assert int([line.split()[1] for line in status if line.startswith("PPid:")][0]) == second_pid
                group_text = pathlib.Path("/proc", str(peer_pid), "cgroup").read_text().splitlines()
                assert "0::" + second["ControlGroup"] in group_text
            roles[role] = peer_pid
            connection.close()
        listener.close()
        (root / "payload.ready").unlink()
        assert child_pidfd is not None
        second_argv = pathlib.Path("/proc", str(second_pid), "cmdline").read_bytes().split(b"\0")[:-1]
        assert second_argv == argv + [b"descendant"]
        assert (root / "count").read_text() == "2"
        run("systemctl", "freeze", unit)
        second_frozen = observe()
        assert second_frozen["InvocationID"] == second["InvocationID"]
        assert second_frozen["FreezerState"] == "frozen"
        signal.pidfd_send_signal(second_pidfd, signal.SIGKILL)
        select.select([second_pidfd], [], [])
        deactivating = wait_native(lambda state: state["ActiveState"] == "deactivating"
                                   and state["FreezerState"] == "frozen" and state["MainPID"] == "0")
        assert deactivating["InvocationID"] == second["InvocationID"]
        assert not select.select([child_pidfd], [], [], 0)[0]
        second_group = pathlib.Path("/sys/fs/cgroup" + second["ControlGroup"])
        populated = (second_group / "cgroup.events").read_text()
        assert "populated 1" in populated.splitlines()
        refused = run("systemctl", "thaw", unit, check=False)
        assert refused.returncode != 0
        assert observe()["FreezerState"] == "frozen"
        assert not select.select([child_pidfd], [], [], 0)[0]
        signal.pidfd_send_signal(child_pidfd, signal.SIGKILL)
        select.select([child_pidfd], [], [])
        second_empty = wait_native(lambda state: state["MainPID"] == "0" and state["ControlPID"] == "0"
                                  and state["FreezerState"] == "frozen"
                                  and state["SubState"] in ("auto-restart", "auto-restart-queued"))
        assert second_empty["InvocationID"] == second["InvocationID"]
        if second_group.exists():
            assert "populated 0" in (second_group / "cgroup.events").read_text().splitlines()
        with marker.open("x") as output:
            output.write("publisher runtime transition pending\n")
            output.flush()
            os.fsync(output.fileno())
        run("systemctl", "thaw", unit)
        run("systemctl", "stop", unit)
        second_terminal = wait_native(lambda state: state["MainPID"] == "0" and state["ControlPID"] == "0"
                                     and state["ActiveState"] in ("inactive", "failed")
                                     and state["SubState"] in ("dead", "failed") and state["Job"] == "")
        assert second_terminal["FreezerState"] == "running"
        assert (root / "count").read_text() == "2"
        inactive_freeze = run("systemctl", "freeze", unit, check=False)
        assert inactive_freeze.returncode != 0
        os.close(second_pidfd)
        os.close(child_pidfd)
        report["populatedBoundary"] = {"original": second, "roles": roles, "deactivating": deactivating,
                                     "events": populated, "thawRefused": {"code": refused.returncode, "stderr": refused.stderr},
                                     "empty": second_empty, "terminal": second_terminal,
                                     "inactiveFreezeRefused": inactive_freeze.returncode, "mainInvocationsTotal": 2}
    print(json.dumps(report, sort_keys=True))
finally:
    if pidfd is not None:
        os.close(pidfd)
    monitor.terminate()
    monitor.wait()
    os.close(monitor_pidfd)
    notify.close()
