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
containers=()
cleanup(){
  for cid in "${containers[@]}"; do
    current=$(docker inspect --format '{{index .Config.Labels "rce.owner-commit"}}' "$cid" 2>/dev/null || true)
    if test "$current" = "$commit"; then
      docker inspect "$cid" > "$out/container-$cid-before-retirement.json"
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
admit baseline
docker build --label rce.owner-commit="$commit" --tag "$baseline" --file "$repo/test/systemd-baseline.Dockerfile" "$repo"
docker image inspect "$baseline" > "$out/baseline-image.json"
admit build
docker run --rm --name rce-systemd-builder-"${commit:0:12}" \
  --label rce.owner-commit="$commit" --memory=6g --memory-swap=6g --cpus=2 \
  --env OWNER_COMMIT="$commit" --env SOURCE_DATE_EPOCH \
  --mount type=bind,src="$repo",dst=/source,readonly \
  --mount type=bind,src="$out/product",dst=/out \
  "$baseline" /bin/bash /source/scripts/build-empty-frozen-systemd-product.sh
admit patched
docker build --label rce.owner-commit="$commit" --build-arg BASE_IMAGE="$baseline" \
  --tag "$patched" --file "$repo/test/systemd-patched.Dockerfile" "$out"
docker image inspect "$patched" > "$out/patched-image.json"
for mode in baseline patched; do
  image=$baseline
  if test "$mode" = patched; then image=$patched; fi
  cid=$(docker run --detach --privileged --cgroupns=private --network=none \
    --memory=512m --memory-swap=512m --cpus=1 \
    --label rce.owner-commit="$commit" --label rce.work=registry-migration-599 \
    --tmpfs /run --tmpfs /run/lock "$image")
  containers+=("$cid")
  docker inspect "$cid" > "$out/$mode-container.json"
  readiness=$(docker exec "$cid" systemctl is-system-running --wait || true)
  case "$readiness" in (running|degraded) ;; (*) printf '%s\n' "$readiness"; exit 1;; esac
  docker exec "$cid" python3 /opt/rce/qualify-empty-frozen-thaw.py "$mode" > "$out/$mode-native-receiving.json"
  docker exec "$cid" journalctl --no-pager --output=json > "$out/$mode-journal.jsonl"
done
python3 - "$out" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1])
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
(root/"native-qualification.json").write_text(json.dumps({"kind":"rce.systemd-manager-native-qualification/v1","baseline":baseline["verdict"],"patched":patched["verdict"],"productionEffects":False,"files":files},sort_keys=True,indent=2)+"\n")
PY
