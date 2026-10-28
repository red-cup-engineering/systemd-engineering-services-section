#!/bin/bash
set -euo pipefail
umask 077
out=${1:?an owned output directory is required}
mkdir -p "$out/product"
out=$(realpath "$out")
repo=$(realpath "$(dirname "$0")/..")
commit=${OWNER_COMMIT:?exact original source commit required}
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:?declared source epoch required}
case "$commit" in (*[!a-f0-9]*|'') exit 1;; esac
test "${#commit}" = 40
baseline=rce-systemd-baseline:"$commit"
patched=rce-systemd-patched:"$commit"
cleanup(){
  for mode in baseline patched; do
    test -f "$out/$mode-container.cid" || continue
    cid=$(cat "$out/$mode-container.cid")
    [[ "$cid" =~ ^[a-f0-9]{64}$ ]] || return 1
    current=$(docker inspect --format '{{index .Config.Labels "rce.owner-commit"}}' "$cid" 2>/dev/null || true)
    if test "$current" = "$commit"; then
      docker inspect "$cid" > "$out/container-$cid-before-retirement.json"
      docker logs "$cid" > "$out/$mode-container.stdout" 2> "$out/$mode-container.stderr" || true
      docker exec "$cid" journalctl --no-pager --output=json > "$out/$mode-journal.jsonl" 2> "$out/$mode-journal.stderr" || true
      python3 "$repo/scripts/retire-owned-native-container.py" "$cid" "$commit" "$out"
    else
      printf '%s\n' "Original container ownership changed; retained $cid" >&2
      return 1
    fi
  done
}
trap cleanup EXIT
admit(){
  python3 - "$out" "$1" <<'PY'
import json,os,pathlib,sys
path,stage=sys.argv[1:]
assert os.environ.get("GITHUB_ACTIONS")=="true"
assert os.environ.get("RUNNER_ENVIRONMENT")=="github-hosted"
assert os.environ.get("RUNNER_OS")=="Linux" and os.environ.get("RUNNER_ARCH")=="X64"
assert os.environ.get("GITHUB_REPOSITORY")=="red-cup-engineering/systemd-engineering-services-section"
v=os.statvfs(path)
available=v.f_bavail*v.f_frsize
initial=pathlib.Path(path,"initial-capacity.json")
if not initial.exists():
    initial.write_text(json.dumps({"availableBytes":available,"providerContractStorageBytes":14000000000,"providerContractMemoryBytes":16000000000,"runId":os.environ["GITHUB_RUN_ID"],"job":os.environ["GITHUB_JOB"],"imageOS":os.environ.get("ImageOS"),"imageVersion":os.environ.get("ImageVersion"),"contract":"https://docs.github.com/en/actions/reference/runners/github-hosted-runners"})+"\n")
start=json.loads(initial.read_text())
remaining=start["providerContractStorageBytes"]-max(0,start["availableBytes"]-available)
peak=8*1024**3
growth=2*1024**3
reserve=(v.f_blocks*v.f_frsize*3+99)//100
required=peak+growth+reserve
contract_reserve=(start["providerContractStorageBytes"]*3+99)//100
memory={line.split(":")[0]:int(line.split()[1])*1024 for line in pathlib.Path("/proc/meminfo").read_text().splitlines() if line.startswith(("MemTotal:","MemAvailable:"))}
memory_required=7*1024**3
row={"providerContractRemainingBytes":remaining,"contractReserveBytes":contract_reserve,"memory":memory,"memoryRequiredBytesEstimate":memory_required,"kind":"systemd-package-factory-capacity/v1","stage":stage,"guestAvailableBytes":available,"guestTotalBytes":v.f_blocks*v.f_frsize,"peakBytesEstimate":peak,"growthBytes":growth,"reserveBytes":reserve,"freeInodes":v.f_favail,"requiredInodes":500000,"provider":"dedicated GitHub-hosted Ubuntu job; no tenant-host fabrication","admitted":available>=required and remaining>=peak+growth+contract_reserve and v.f_favail>=500000 and memory["MemAvailable"]>=memory_required}
pathlib.Path(path,"capacity-"+stage+".json").write_text(json.dumps(row,sort_keys=True)+"\n")
assert row["admitted"], "original factory capacity refused"
PY
}
receive_retained_product(){
  python3 - "$repo" "$out" <<'PY'
import hashlib,json,os,pathlib,re,stat,sys,urllib.error,urllib.parse,urllib.request,zipfile
repo,out=map(pathlib.Path,sys.argv[1:])
key=os.environ["RETAINED_PRODUCT_RECORD"]
assert re.fullmatch(r"[a-f0-9]{12}",key), "exact owned product record required"
record=repo/"data/records/native-manager-product-records"/(key+".json")
assert record.is_file() and not record.is_symlink() and record.stat().st_size<=65536
raw=record.read_bytes();r=json.loads(raw)
assert r["kind"]=="rce.systemd-retained-product-input/v1" and r["version"]==1
assert r["repository"]=="red-cup-engineering/systemd-engineering-services-section"
assert r["producerCommit"].startswith(key) and re.fullmatch(r"[a-f0-9]{40}",r["producerCommit"])
intent=json.loads((repo/"data/records/native-manager-repair-records/emptythaw2.json").read_bytes())
assert intent["kind"]=="rce.systemd-native-manager-repair-intent/v1" and intent["version"]==1
assert r["sourceVersion"]==intent["sourceVersion"] and r["productVersion"]==intent["productVersion"]
assert r["sourceDateEpoch"]==int(os.environ["SOURCE_DATE_EPOCH"])
assert r["patchSha256"]==hashlib.sha256((repo/"patches/systemd-empty-frozen-thaw.patch").read_bytes()).hexdigest()
assert 0<r["artifactBytes"]<=67108864 and 0<r["uncompressedBytes"]<=268435456 and r["fileCount"]<=512
assert r["vendorBuild"]=={"passed":1690,"skipped":26,"failed":0,"exitCode":0}
token=os.environ["RETAINED_PRODUCT_TOKEN"]
assert token and os.environ["GITHUB_REPOSITORY"]==r["repository"]
api="https://api.github.com/repos/"+r["repository"]+"/actions/artifacts/"+str(r["artifactId"])
headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
opener=urllib.request.build_opener(NoRedirect)
with opener.open(urllib.request.Request(api,headers=headers),timeout=30) as response:
    meta=json.load(response)
assert meta["id"]==r["artifactId"] and not meta["expired"]
assert meta["size_in_bytes"]==r["artifactBytes"] and meta["digest"]=="sha256:"+r["artifactSha256"]
assert meta["workflow_run"]["id"]==r["runId"] and meta["workflow_run"]["head_sha"]==r["producerCommit"]
custody=out/"retained-input";custody.mkdir(mode=0o700)
(custody/"source-input.json").write_bytes(raw)
(custody/"provider-metadata.json").write_text(json.dumps(meta,sort_keys=True)+"\n")
try:
    opener.open(urllib.request.Request(api+"/zip",headers=headers),timeout=30)
    raise RuntimeError("original signed artifact redirect absent")
except urllib.error.HTTPError as error:
    if error.code!=302: raise RuntimeError("original artifact API refused: HTTP "+str(error.code)) from None
    location=error.headers["Location"]
parsed=urllib.parse.urlsplit(location)
assert parsed.scheme=="https" and not parsed.username and not parsed.password
archive=custody/"original-product.zip";digest=hashlib.sha256();size=0
try:
    with opener.open(urllib.request.Request(location),timeout=60) as response,archive.open("xb") as target:
        assert response.status==200
        while chunk:=response.read(1048576):
            size+=len(chunk);assert size<=r["artifactBytes"]
            target.write(chunk);digest.update(chunk)
except urllib.error.URLError:
    raise RuntimeError("original signed artifact byte transport unreceived") from None
assert size==r["artifactBytes"] and digest.hexdigest()==r["artifactSha256"]
with zipfile.ZipFile(archive) as source:
    files=[item for item in source.infolist() if not item.is_dir()]
    assert len(files)==r["fileCount"] and sum(item.file_size for item in files)==r["uncompressedBytes"]
    seen=set()
    for item in files:
        path=pathlib.PurePosixPath(item.filename)
        assert not path.is_absolute() and all(part not in ("",".","..") for part in path.parts)
        assert item.filename not in seen and not stat.S_ISLNK(item.external_attr>>16)
        assert item.file_size<=67108864
        seen.add(item.filename)
        target=(out.joinpath(*path.parts) if path.parts[0]=="product"
                else custody.joinpath("producer-metadata",*path.parts))
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with source.open(item) as incoming,target.open("xb") as destination:
            while chunk:=incoming.read(1048576): destination.write(chunk)
        assert target.stat().st_size==item.file_size
product=out/"product";manifest=product/"product.json"
assert hashlib.sha256(manifest.read_bytes()).hexdigest()==r["productManifestSha256"]
p=json.loads(manifest.read_bytes())
assert p["ownerCommit"]==r["producerCommit"] and p["patchSha256"]==r["patchSha256"]
assert p["sourceVersion"]==r["sourceVersion"] and p["productVersion"]==r["productVersion"]
assert p["sourceDateEpoch"]==r["sourceDateEpoch"]
for item in p["files"]:
    assert pathlib.PurePosixPath(item["name"]).name==item["name"]
    target=product/item["name"];digest=hashlib.sha256()
    with target.open("rb") as incoming:
        while chunk:=incoming.read(1048576): digest.update(chunk)
    assert target.stat().st_size==item["bytes"] and digest.hexdigest()==item["sha256"]
required={name+"_"+intent["productVersion"]+"_amd64.deb" for name in ("systemd","libsystemd-shared","libsystemd0")}
assert {item["name"] for item in r["nativePackageInputs"]}==required
assert all(item in p["files"] for item in r["nativePackageInputs"])
assert (product/"vendor-build-exit-code.txt").read_text().strip()=="0"
(custody/"received.json").write_text(json.dumps({"kind":"rce.systemd-retained-product-receiving/v1",
    "producerCommit":p["ownerCommit"],"consumerCommit":os.environ["OWNER_COMMIT"],
    "artifactSha256":r["artifactSha256"],"productManifestSha256":r["productManifestSha256"],
    "nativePackageInputs":r["nativePackageInputs"],"recompiled":False},sort_keys=True)+"\n")
PY
}
if test -n "${RETAINED_PRODUCT_RECORD:-}"; then
  admit retained-product
  receive_retained_product
fi
admit baseline
docker build --label rce.owner-commit="$commit" --tag "$baseline" --file "$repo/test/systemd-baseline.Dockerfile" "$repo"
docker image inspect "$baseline" > "$out/baseline-image.json"
if test -z "${RETAINED_PRODUCT_RECORD:-}"; then
  admit build
  docker run --rm --name rce-systemd-builder-"${commit:0:12}" \
    --label rce.owner-commit="$commit" --memory=6g --memory-swap=6g --cpus=2 \
    --cap-add SYS_ADMIN --security-opt apparmor=unconfined --cgroupns=private --tmpfs /run:size=16m \
    --env OWNER_COMMIT="$commit" --env SOURCE_DATE_EPOCH \
    --mount type=bind,src="$repo",dst=/source,readonly \
    --mount type=bind,src="$out/product",dst=/out \
    "$baseline" /bin/bash /source/scripts/build-empty-frozen-systemd-product.sh
fi
admit patched
docker build --label rce.owner-commit="$commit" --build-arg BASE_IMAGE="$baseline" \
  --tag "$patched" --file "$repo/test/systemd-patched.Dockerfile" "$out"
docker image inspect "$patched" > "$out/patched-image.json"
for mode in baseline patched; do
  image=$baseline
  if test "$mode" = patched; then image=$patched; fi
  python3 - "$out" "$mode" "$image" "$commit" <<'PY'
import json,os,pathlib,re,select,socket,struct,subprocess,sys,time
out=pathlib.Path(sys.argv[1]);mode,image,commit=sys.argv[2:]
def run(*args):
    return subprocess.run(args,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
directory=out/(mode+"-notify");directory.mkdir(mode=0o700)
with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as notify:
    notify.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1)
    notify.bind(str(directory/"notify"))
    cid=run("docker","create","--privileged","--cgroupns=private","--network=none",
        "--memory=512m","--memory-swap=512m","--cpus=1",
        "--label","rce.owner-commit="+commit,"--label","rce.work=registry-migration-599",
        "--tmpfs","/run","--tmpfs","/run/lock",
        "--mount","type=bind,src="+str(directory)+",dst=/run/host,readonly",
        "--env","NOTIFY_SOCKET=/run/host/notify",image).stdout.strip()
    assert re.fullmatch(r"[a-f0-9]{64}",cid)
    # Record ownership before start so failed boot remains exactly retireable.
    with (out/(mode+"-container.cid")).open("x") as record:
        record.write(cid+"\n");record.flush();os.fsync(record.fileno())
    run("docker","start",cid)
    before=json.loads(run("docker","inspect",cid).stdout)[0]
    (out/(mode+"-container.json")).write_text(json.dumps([before],sort_keys=True)+"\n")
    assert before["Id"]==cid and before["Config"]["Labels"]["rce.owner-commit"]==commit
    state=before["State"];pid=state["Pid"]
    assert state["Running"] and pid>0, "original container exited before manager readiness"
    pidfd=os.pidfd_open(pid)
    try:
        current=json.loads(run("docker","inspect",cid).stdout)[0]
        assert current["State"]["Pid"]==pid and current["State"]["StartedAt"]==state["StartedAt"]
        assert current["Config"]["Labels"]["rce.owner-commit"]==commit
        deadline=time.monotonic()+300
        received=[]
        while True:
            ready,_,_=select.select([notify,pidfd],[],[],max(0,deadline-time.monotonic()))
            assert ready, "manager readiness observation budget exhausted; not qualified"
            assert pidfd not in ready, "original manager exited before readiness"
            payload,ancillary,flags,_=notify.recvmsg(65536,socket.CMSG_SPACE(struct.calcsize("3i")))
            assert not flags&(socket.MSG_TRUNC|socket.MSG_CTRUNC)
            credentials=[struct.unpack("3i",data) for level,kind,data in ancillary
                if level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS]
            assert len(credentials)==1 and credentials[0][:2]==(pid,0)
            fields=payload.decode().splitlines()
            received.append({"fields":fields,"senderPid":credentials[0][0],"senderUid":credentials[0][1]})
            assert len(received)<=128, "unexpected manager readiness message volume"
            if "READY=1" in fields:
                assert not select.select([pidfd],[],[],0)[0], "original manager exited at readiness"
                (out/(mode+"-manager-readiness.json")).write_text(json.dumps({
                    "kind":"rce.native-container-manager-readiness/v1","container":cid,
                    "commit":commit,"pid":pid,"startedAt":state["StartedAt"],
                    "basis":"original-pidfd-and-kernel-SCM_CREDENTIALS-READY=1",
                    "notifications":received,"ready":True},sort_keys=True)+"\n")
                break
    finally:
        os.close(pidfd)
PY
  cid=$(cat "$out/$mode-container.cid")
  readiness=$(docker exec "$cid" systemctl is-system-running --wait || true)
  case "$readiness" in (running|degraded) ;; (*) printf '%s\n' "$readiness"; exit 1;; esac
  docker exec "$cid" python3 /opt/rce/qualify-empty-frozen-thaw.py "$mode" > "$out/$mode-native-receiving.json"
done
python3 - "$out" <<'PY'
import hashlib,json,pathlib,sys,os
root=pathlib.Path(sys.argv[1])
product=json.loads((root/"product/product.json").read_text())
baseline=json.loads((root/"baseline-native-receiving.json").read_text())
patched=json.loads((root/"patched-native-receiving.json").read_text())
assert baseline["verdict"]=="original-defect-reproduced"
assert patched["verdict"]=="corrected-native-thaw-received"
assert patched["mainInvocations"]==1
assert patched["populatedBoundary"]["thawRefused"]["code"]!=0
assert patched["populatedBoundary"]["inactiveFreezeRefused"]!=0
assert patched["populatedBoundary"]["mainInvocationsTotal"]==2
files=[]
for p in sorted(root.iterdir()):
    if p.is_file():
        files.append({"name":p.name,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
(root/"native-qualification.json").write_text(json.dumps({"kind":"rce.systemd-manager-native-qualification/v1","consumerCommit":os.environ["OWNER_COMMIT"],"productProducerCommit":product["ownerCommit"],"productManifestSha256":hashlib.sha256((root/"product/product.json").read_bytes()).hexdigest(),"baseline":baseline["verdict"],"patched":patched["verdict"],"productionEffects":False,"files":files},sort_keys=True,indent=2)+"\n")
PY
