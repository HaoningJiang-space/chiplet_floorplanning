"""Fetch hash-locked public models; optionally build the pinned OpenSTA engine."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("local"))
    parser.add_argument("--build-sta", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    lock = json.loads(Path(__file__).with_name("sources.lock.json").read_text())
    for record in lock["files"]:
        path = args.root / record["path"]
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError(f"existing file does not match source lock: {path}")
        else:
            for attempt in range(3):
                try:
                    with urlopen(record["url"], timeout=25) as stream:
                        data = stream.read()
                    if record["decompress_gzip"]:
                        data = gzip.decompress(data)
                    if hashlib.sha256(data).hexdigest() != record["sha256"]:
                        raise ValueError(f"download hash mismatch: {path}")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    break
                except OSError:
                    if attempt == 2:
                        raise
        print("verified", path)
    if args.build_sta:
        repo = args.root / "upstream/OpenSTA"
        source = lock["opensta"]
        if not repo.exists():
            subprocess.run(["git", "clone", "--depth", "1", "--branch", source["tag"], source["url"], str(repo)], check=True)
        actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        if actual != source["commit"]:
            raise ValueError("OpenSTA commit mismatch")
        patches = {"CMakeLists.txt": ("find_package(SWIG REQUIRED 3.0)", "find_package(SWIG 3.0 REQUIRED)"),
                   "tcl/Exception.i": ("$function", "$action")}
        changed = subprocess.check_output(["git", "-C", str(repo), "diff", "HEAD", "--name-only"], text=True).splitlines()
        if set(changed) - patches.keys():
            raise ValueError("OpenSTA sources have unrelated edits")
        for name, (before, after) in patches.items():
            original = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{name}"], text=True)
            patched = original.replace(before, after)
            path = repo / name
            if path.read_text() not in (original, patched):
                raise ValueError(f"OpenSTA {name} has unrelated edits")
            path.write_text(patched)
        build = args.root / "build/opensta"
        subprocess.run(["cmake", "-S", str(repo), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"], check=True)
        subprocess.run(["cmake", "--build", str(build), "-j", str(args.jobs)], check=True)
        subprocess.run([str(repo / "app/sta"), "-version"], check=True)


if __name__ == "__main__":
    main()
