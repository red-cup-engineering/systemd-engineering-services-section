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
    main.write_text("import os,pathlib,signal,socket,sys\np=pathlib.Path(sys.argv[1])\n"
                    "n=int(p.read_text()) if p.exists() else 0\n"
                    "assert 0<=n<3\np.write_text(str(n+1))\n"
                    "s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)\n"
                    "s.connect(str(p.parent/\'payload.ready\'))\ns.sendall(b\'READY\\n\')\ns.close()\nsignal.pause()\n")
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
    assert payload_ready == b"READY\n"
    connection.close()
    listener.close()
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
    print(json.dumps(report, sort_keys=True))
finally:
    if pidfd is not None:
        os.close(pidfd)
    monitor.terminate()
    monitor.wait()
    os.close(monitor_pidfd)
    notify.close()
