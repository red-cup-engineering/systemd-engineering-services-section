#!/bin/bash
set -euo pipefail
umask 022
source_version=$(python3 - <<'PY'
from pathlib import Path
import hashlib,json,re
root=Path("/source")
r=json.loads((root/"data/records/native-manager-repair-records/emptythaw2.json").read_text())
assert r["kind"]=="rce.systemd-native-manager-repair-intent/v1" and r["version"]==1
assert r["sourceDateEpoch"]==int(__import__("os").environ["SOURCE_DATE_EPOCH"])
assert all(re.fullmatch(r"[0-9A-Za-z.+:~-]+",r[key]) for key in ("sourceVersion","productVersion"))
assert hashlib.sha256((root/r["patch"]["path"]).read_bytes()).hexdigest()==r["patch"]["sha256"]
print(r["sourceVersion"])
PY
)
source_root=/work/source
mkdir -p "$source_root" /out
retain_build_evidence(){
  build_status=$?
  trap - EXIT
  for evidence in "$source_root"/systemd_*.dsc "$source_root"/systemd_*.tar.gz "$source_root"/systemd_*.tar.xz; do
    if test -f "$evidence"; then cp -- "$evidence" /out/; fi
  done
  for evidence in testlog.txt testlog.json testlog.junit.xml meson-log.txt; do
    original="$source_root/tree/obj-x86_64-linux-gnu/meson-logs/$evidence"
    if test -f "$original"; then cp -- "$original" "/out/$evidence"; fi
  done
  printf '%s\n' "$build_status" > /out/vendor-build-exit-code.txt
  exit "$build_status"
}
trap retain_build_evidence EXIT
# This is the disposable, declared build container, never a tenant host.
python3 - <<'PY'
from pathlib import Path
for p in Path("/etc/apt/sources.list.d").glob("*.sources"):
    text=p.read_text()
    p.write_text(text.replace("Types: deb\n", "Types: deb deb-src\n"))
PY
apt-get update
apt-get install --yes --no-install-recommends build-essential dpkg-dev ca-certificates patch util-linux
# Receive the mount authority used by the unmodified vendor test suite.
unshare --mount --propagation slave /bin/sh -ec '
  mountpoint --quiet /run
  mount --options remount,ro /run
  mount --options remount,rw /run
'
cd "$source_root"
apt-get source --download-only "systemd=$source_version"
printf '%s\n' \
 'b27dcc100a738b4b5b81f7c5174c1239a6495f5bdf3d3caa94a17b8373e6a1ca  systemd_257.9.orig.tar.gz' \
 'edf2e73f46ac5e35af5f76c6e5a6768c0eab45727b64c0f5b078655cfa7a4a2d  systemd_257.9-0ubuntu2.5.debian.tar.xz' | sha256sum --check -
apt-get build-dep --yes --no-install-recommends "systemd=$source_version"
dpkg-source --extract "systemd_${source_version}.dsc" tree
cd tree
sha256sum src/core/unit.c > /out/original-unit-source.sha256
patch --batch --fuzz=0 --strip=1 < /source/patches/systemd-empty-frozen-thaw.patch
sha256sum src/core/unit.c > /out/patched-unit-source.sha256
python3 - <<'PY'
from pathlib import Path
import email.utils
import os,json
intent=json.loads(Path("/source/data/records/native-manager-repair-records/emptythaw2.json").read_text())
p=Path("debian/changelog")
head=("systemd ("+intent["productVersion"]+") questing; urgency=medium\n\n"
      "  * Receive explicit thaw of an empty, non-active, cached-frozen unit.\n"
      "    Original registry migration Work599; no automatic version allocation.\n\n"
      " -- emsenn <emsenn@emsenn.net>  "+email.utils.formatdate(int(os.environ["SOURCE_DATE_EPOCH"]),usegmt=False)+"\n\n")
p.write_text(head+p.read_text())
PY
dpkg-buildpackage --build=binary --no-sign -j2
cd "$source_root"
python3 - <<'PY'
from pathlib import Path
import hashlib,json,os,shutil,subprocess
source=Path("/work/source")
destination=Path("/out")
files=[]
for p in sorted(source.iterdir()):
    if p.is_file() and (p.suffix in (".deb",".buildinfo",".changes",".dsc") or p.name.endswith(".tar.xz") or p.name.endswith(".tar.gz")):
        shutil.copy2(p,destination/p.name)
        files.append({"name":p.name,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
inventory=subprocess.check_output(["dpkg-query","--show","--showformat=${binary:Package} ${Version}\n"],text=True)
(destination/"build-package-inventory.txt").write_text(inventory)
patch=Path("/source/patches/systemd-empty-frozen-thaw.patch").read_bytes()
intent=json.loads(Path("/source/data/records/native-manager-repair-records/emptythaw2.json").read_text())
receipt={"kind":"rce.systemd-manager-package-product/v1","sourceVersion":intent["sourceVersion"],"productVersion":intent["productVersion"],"ownerCommit":os.environ["OWNER_COMMIT"],"sourceDateEpoch":int(os.environ["SOURCE_DATE_EPOCH"]),"patchSha256":hashlib.sha256(patch).hexdigest(),"files":files}
(destination/"product.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
PY
