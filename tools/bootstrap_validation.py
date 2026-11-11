"""Fetch hash-locked public models; optionally build the pinned OpenSTA engine."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("local"))
    parser.add_argument("--build-sta", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--windows-toolchain", type=Path,
                        help="Native conda-forge toolchain prefix (Windows only)")
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
        patches = {"CMakeLists.txt": [("find_package(SWIG REQUIRED 3.0)", "find_package(SWIG 3.0 REQUIRED)")],
                   "tcl/Exception.i": [("$function", "$action")]}
        env = os.environ.copy()
        configure = []
        if args.windows_toolchain:
            if os.name != "nt":
                parser.error("--windows-toolchain requires Windows")
            prefix = args.windows_toolchain.resolve() / "Library"
            bindir = prefix / "bin"
            env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
            env["TCL_LIBRARY"] = str(prefix / "lib/tcl8.6")
            patches["CMakeLists.txt"].append((
                "COMMAND etc/TclEncode.tcl", "COMMAND ${TCL_TCLSH} etc/TclEncode.tcl"))
            patches["tcl/Liberty.tcl"] = [
                ("set filename [file nativename $args]",
                 "set filename [file nativename [lindex $args 0]]")]
            patches["include/sta/Machine.hh"] = [
                ("  #include <stdarg.h>", "  #include <stdarg.h>\n  #include <stddef.h>"),
                ("  #define va_copy(d,s) ((d)=(s))",
                 "  #ifndef va_copy\n  #define va_copy(d,s) ((d)=(s))\n  #endif"),
                ("  #define strcasecmp _stricmp",
                 "  #ifndef __MINGW32__\n  #define strcasecmp _stricmp"),
                ("  #define strtoull _strtoui64", "  #define strtoull _strtoui64\n  #endif")]
            configure = ["-G", "Ninja",
                         "-DSTA_COMPILE_OPTIONS=-D_GNU_SOURCE",
                         f"-DCMAKE_CXX_COMPILER={(bindir / 'x86_64-w64-mingw32-g++.exe').as_posix()}",
                         f"-DFLEX_EXECUTABLE={(bindir / 'win_flex.exe').as_posix()}",
                         f"-DBISON_EXECUTABLE={(bindir / 'win_bison.exe').as_posix()}",
                         f"-DSWIG_EXECUTABLE={(bindir / 'swig.exe').as_posix()}",
                         f"-DTCL_TCLSH={(bindir / 'tclsh.exe').as_posix()}",
                         f"-DTCL_LIBRARY={(prefix / 'lib/tcl86t.lib').as_posix()}",
                         f"-DTCL_HEADER={(prefix / 'include/tcl.h').as_posix()}",
                         f"-DZLIB_ROOT={prefix.as_posix()}"]
        changed = subprocess.check_output(["git", "-C", str(repo), "diff", "HEAD", "--name-only"], text=True).splitlines()
        if set(changed) - patches.keys():
            raise ValueError("OpenSTA sources have unrelated edits")
        for name, replacements in patches.items():
            original = subprocess.check_output(["git", "-C", str(repo), "show", f"HEAD:{name}"], text=True)
            patched = original
            for before, after in replacements:
                patched = patched.replace(before, after)
            path = repo / name
            if path.read_text() not in (original, patched):
                raise ValueError(f"OpenSTA {name} has unrelated edits")
            if path.read_text() != patched:
                path.write_text(patched)
        build = args.root / "build/opensta"
        cmake = str(bindir / "cmake.exe") if args.windows_toolchain else "cmake"
        subprocess.run([cmake, "-S", str(repo), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5", *configure], check=True, env=env)
        subprocess.run([cmake, "--build", str(build), "-j", str(args.jobs)], check=True, env=env)
        executable = repo / ("app/sta.exe" if os.name == "nt" else "app/sta")
        subprocess.run([str(executable), "-version"], check=True, env=env)
        diff = subprocess.check_output(["git", "-C", str(repo), "diff", "HEAD"], text=True)
        (build / "source-patches.diff").write_text(diff)
        receipt = dict(upstream_commit=actual,
                       executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                       patch_diff_sha256=hashlib.sha256(diff.encode()).hexdigest(),
                       patched_files=list(patches), windows_toolchain=bool(args.windows_toolchain))
        if args.windows_toolchain:
            receipt["toolchain_packages"] = sorted(
                ({k: record[k] for k in ("name", "version", "build", "sha256")}
                 for file in (args.windows_toolchain / "conda-meta").glob("*.json")
                 for record in [json.loads(file.read_text())]), key=lambda item: item["name"])
        (build / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
