#!/usr/bin/env python3
"""Retire one exact factory-owned private container, retaining native exit."""
import hashlib,json,os,pathlib,select,subprocess,sys
cid,commit,out=sys.argv[1:]
def run(*args,check=True):
    return subprocess.run(args,check=check,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
before=json.loads(run("docker","inspect",cid).stdout)[0]
assert before["Id"]==cid
assert before["Config"]["Labels"]["rce.owner-commit"]==commit
state=before["State"]
pid=state["Pid"]
assert isinstance(pid,int) and pid>=0
if pid==0:
    assert state["Status"] in ("exited","dead")
    assert not state["Running"] and not state["Restarting"] and not state["Paused"]
    assert isinstance(state["ExitCode"],int)
    # Without --force, concurrent native reuse refuses rather than stopping it.
    run("docker","rm",cid)
    assert run("docker","inspect",cid,check=False).returncode!=0
    receipt={"kind":"rce.owned-native-container-retirement/v1","container":cid,"commit":commit,"image":before["Image"],"basis":"already-terminal-native-container-state","state":state,"pidfdReceived":False,"containerAbsent":True}
else:
    pidfd=os.pidfd_open(pid)
    lines=pathlib.Path("/proc",str(pid),"cgroup").read_text().splitlines()
    group=[line[3:] for line in lines if line.startswith("0::")][0]
    assert group.startswith("/") and ".." not in group.split("/")
    directory=pathlib.Path("/sys/fs/cgroup"+group)
    identity=directory.stat()
    current=json.loads(run("docker","inspect",cid).stdout)[0]
    assert current["State"]["Pid"]==pid and current["State"]["StartedAt"]==state["StartedAt"]
    assert current["Config"]["Labels"]["rce.owner-commit"]==commit
    run("docker","rm","--force",cid)
    select.select([pidfd],[],[])
    os.close(pidfd)
    assert run("docker","inspect",cid,check=False).returncode!=0
    if directory.exists():
        after=directory.stat()
        assert (after.st_dev,after.st_ino)==(identity.st_dev,identity.st_ino)
        events=(directory/"cgroup.events").read_text()
        assert "populated 0" in events.splitlines()
    else:
        events="original cgroup absent after original container PID exit"
    receipt={"kind":"rce.owned-native-container-retirement/v1","container":cid,"commit":commit,"image":before["Image"],"basis":"captured-original-pidfd-and-cgroup","pid":pid,"group":group,"identity":{"dev":identity.st_dev,"ino":identity.st_ino},"events":events,"nativePidfdExited":True,"containerAbsent":True}
with pathlib.Path(out,"container-retirement.jsonl").open("a") as output:
    output.write(json.dumps(receipt,sort_keys=True)+"\n")
    output.flush()
    os.fsync(output.fileno())
