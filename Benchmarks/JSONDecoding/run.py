#!/usr/bin/env python3
"""Compare JSON decoding at two pinned Git revisions without changing a checkout."""
import argparse
import hashlib
import json
import platform
import shlex
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BASE = "main"
HEAD = "testJSON"
SOURCES = [
    "Sources/SwiftCompilerPluginMessageHandling/JSON/JSON.swift",
    "Sources/SwiftCompilerPluginMessageHandling/JSON/JSONDecoding.swift",
    "Sources/SwiftCompilerPluginMessageHandling/JSON/JSONEncoding.swift",
    "Sources/SwiftCompilerPluginMessageHandling/JSON/CodingUtilities.swift",
    "Sources/SwiftCompilerPluginMessageHandling/PluginMessages.swift",
]


def command(args, **kwargs):
    return subprocess.check_output(args, cwd=ROOT, **kwargs)


def build(label, revision, reuse=False):
    directory = HERE / ".build" / label
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    snapshots = {}
    for source in SOURCES:
        target = directory / Path(source).name
        snapshots[target] = command(["git", "show", f"{revision}:{source}"]) if revision else (ROOT / source).read_bytes()
        files.append(str(target))
    # Snapshot the C import headers from the same revision as the decoder.
    headers = directory / "shims"
    headers.mkdir(exist_ok=True)
    prefix = "Sources/_SwiftSyntaxCShims/include/"
    for source in command(["git", "ls-tree", "-r", "--name-only", revision or BASE, prefix], text=True).splitlines():
        snapshots[headers / Path(source).name] = command(["git", "show", f"{revision}:{source}"]) if revision else (ROOT / source).read_bytes()
    flags = ["-O", "-whole-module-optimization", "-swift-version", "5"]
    library = directory / "libJSONBenchmarkSupport.dylib"
    executable = directory / "benchmark"
    driver = HERE / "Benchmark.swift"
    fingerprint = hashlib.sha256(driver.read_bytes() + command(["swift", "--version"])
                                 + " ".join(flags).encode()
                                 + b"".join(snapshots.values())).hexdigest()
    fingerprint_path = directory / "build-fingerprint.txt"
    if reuse and executable.exists() and fingerprint_path.exists() and fingerprint_path.read_text() == fingerprint:
        return executable
    for path, content in snapshots.items():
        path.write_bytes(content)
    command(["swiftc", *flags, "-emit-library", "-emit-module", "-module-name", "JSONBenchmarkSupport",
             "-I", str(headers), *files, "-o", str(library),
             "-emit-module-path", str(directory / "JSONBenchmarkSupport.swiftmodule")])
    command(["swiftc", *flags, "-I", str(headers), "-I", str(directory), "-L", str(directory),
             "-lJSONBenchmarkSupport", "-Xlinker", "-rpath", "-Xlinker", str(directory),
             str(HERE / "Benchmark.swift"), "-o", str(executable)])
    fingerprint_path.write_text(fingerprint)
    return executable


def summarize(raw):
    rows = []
    names = [item["name"] for item in raw["samples"][0]["measurements"]]
    for name in names:
        groups = {label: [] for label in ["base", "pr"]}
        sample_by_round = {}
        byte_count = None
        for sample in raw["samples"]:
            item = next(item for item in sample["measurements"] if item["name"] == name)
            byte_count = item["bytes"]
            duration = item["elapsedNS"] / item["iterations"]
            groups[sample["variant"]].append(duration)
            sample_by_round.setdefault(sample["round"], {})[sample["variant"]] = duration
        baseline, changed = (statistics.median(groups[label]) for label in ["base", "pr"])
        paired = [(values["pr"] / values["base"] - 1) * 100 for values in sample_by_round.values()]
        rows.append({"name": name, "bytes": byte_count, "base_us": baseline / 1000,
                     "pr_us": changed / 1000, "regression_percent": (changed / baseline - 1) * 100,
                     "paired_min_percent": min(paired), "paired_max_percent": max(paired)})
    return rows


def main():
    global BASE, HEAD
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=9)
    parser.add_argument("--seconds", type=float, default=0.08, help="Target baseline seconds per case per round")
    parser.add_argument("--output", help="Output prefix (default: comparison, or working-tree for --working-tree)")
    parser.add_argument("--case", action="append", default=[], help="Measure only this case; repeat for multiple cases")
    parser.add_argument("--working-tree", action="store_true", help="Compare baseline against current uncommitted source files")
    parser.add_argument("--reuse-build", action="store_true", help="Reuse binaries only if all source inputs and flags match")
    parser.add_argument("--base-ref", default=BASE, help="Baseline Git ref, resolved and pinned before building")
    parser.add_argument("--candidate-ref", default=HEAD, help="Candidate Git ref, resolved and pinned before building")
    arguments = parser.parse_args()
    BASE = command(["git", "rev-parse", arguments.base_ref], text=True).strip()
    HEAD = command(["git", "rev-parse", arguments.candidate_ref], text=True).strip()
    arguments.output = arguments.output or ("working-tree" if arguments.working_tree else "comparison")
    if arguments.rounds < 3 or arguments.seconds <= 0:
        parser.error("Use at least three rounds and a positive duration")
    # Confirm no code other than JSONDecoding.swift differs in the compiled sources.
    for source in SOURCES:
        if not source.endswith("JSONDecoding.swift"):
            candidate = (ROOT / source).read_bytes() if arguments.working_tree else command(["git", "show", f"{HEAD}:{source}"])
            assert command(["git", "show", f"{BASE}:{source}"]) == candidate
    print("Building baseline and candidate decoder modules with -O -whole-module-optimization", flush=True)
    executables = {"base": build("base", BASE, arguments.reuse_build),
                   "pr": build("working" if arguments.working_tree else "pr",
                               None if arguments.working_tree else HEAD, arguments.reuse_build)}
    metadata = {
        "date": datetime.now().astimezone().isoformat(), "base": BASE,
        "head": "working-tree" if arguments.working_tree else HEAD,
        "candidate_sources_sha256": {source: hashlib.sha256((HERE / '.build' / ('working' if arguments.working_tree else 'pr')
                                                            / Path(source).name).read_bytes()).hexdigest()
                                     for source in SOURCES},
        "candidate_build_fingerprint": (HERE / '.build' / ('working' if arguments.working_tree else 'pr')
                                        / 'build-fingerprint.txt').read_text(),
        "swift": command(["swift", "--version"], text=True).strip(),
        "os": command(["sw_vers"], text=True).strip(),
        "cpu": command(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip(),
        "memory_bytes": int(command(["sysctl", "-n", "hw.memsize"], text=True)),
        "architecture": platform.machine(), "flags": "-O -whole-module-optimization -swift-version 5",
        "rounds": arguments.rounds, "baseline_target_seconds": arguments.seconds,
    }
    print("Calibrating fixed iteration counts on the baseline", flush=True)
    plan = json.loads(command([str(executables["base"]), "calibrate", str(arguments.seconds)], text=True))
    if arguments.case:
        available = {entry["name"] for entry in plan}
        if set(arguments.case) - available:
            parser.error(f"Unknown cases: {sorted(set(arguments.case) - available)}")
        plan = [entry for entry in plan if entry["name"] in arguments.case]
    plan_path = HERE / ".build" / "plan.json"
    plan_path.write_text(json.dumps(plan))
    raw = {"metadata": metadata, "plan": plan, "samples": []}
    output = HERE / f"{arguments.output}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    for round_number in range(arguments.rounds):
        # Alternate AB/BA to reduce bias from temperature and background work.
        order = ["base", "pr"] if round_number % 2 == 0 else ["pr", "base"]
        for label in order:
            args = [str(executables[label]), "sample", str(plan_path)]
            if round_number % 2:
                args.append("reverse")
            measurements = json.loads(command(args, text=True))
            raw["samples"].append({"round": round_number + 1, "variant": label, "measurements": measurements})
            output.write_text(json.dumps(raw, indent=2) + "\n")
            print(f"Round {round_number + 1}/{arguments.rounds}: {label} complete ({len(measurements)} cases)", flush=True)
    # Same input sizes, iteration counts, and output checksums in every paired round.
    for number in range(1, arguments.rounds + 1):
        pair = [sample for sample in raw["samples"] if sample["round"] == number]
        keyed = [{item["name"]: (item["bytes"], item["iterations"], item["checksum"])
                  for item in sample["measurements"]} for sample in pair]
        assert keyed[0] == keyed[1]
    rows = summarize(raw)
    (HERE / f"{arguments.output}-summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    candidate_label = "Working tree" if arguments.working_tree else "PR"
    source_origin = "the base Git revision and the uncommitted working tree" if arguments.working_tree else "each Git revision"
    lines = ["# JSON decoding performance: main vs candidate", "", f"Measured: {metadata['date']}", "",
             f"Baseline: `{BASE}`; candidate: `{metadata['head']}`.", "",
             f"Environment: {metadata['cpu']}, {metadata['memory_bytes'] // 2**30} GiB RAM, "
             f"macOS {command(['sw_vers', '-productVersion'], text=True).strip()}, "
             f"{metadata['swift'].splitlines()[0]}, {metadata['architecture']}.", "",
             "## Method", "",
             "- Decoder-only benchmark: all four JSON source files and the actual "
             f"PluginMessages.swift types are copied directly from {source_origin}. Only JSONDecoding.swift "
             "differs among compiled Swift files. The C shim headers are copied from each source version as well. "
             "The raw data records a fingerprint of all candidate build inputs, flags, and compiler version.",
             "- Both libraries and the separate driver use `-O -whole-module-optimization -swift-version 5`. "
             "The driver calls the public SPI JSON.decode API across a module boundary. This isolates the decoder "
             "without building all SwiftSyntax dependencies.",
             "- JSON bytes are prepared/encoded before timing, retained in memory, and decoded repeatedly. "
             "Input preparation, Foundation reference checks, and console output are outside the timer. "
             "Timed work includes decoder output consumption, destruction, and small driver overhead.",
             f"- Baseline calibration chooses fixed iteration counts targeting {arguments.seconds:.2f} seconds "
             f"per case. Both versions use the same counts. Each case has {arguments.rounds} measured rounds; "
             "version order alternates AB/BA, and case order alternates forward/reverse. Each sample is warmed up "
             "with up to 128 decodes. Calibration itself is not included in the reported medians.",
             "- Timed loops accumulate a checksum from every decoded result. Paired byte counts, iteration counts, "
             "and checksums match. Scalar String results are also compared exactly with Foundation.JSONDecoder "
             "before timing. All cases use valid JSON; CJK/emoji cases contain literal UTF-8 bytes.",
             "- Medians below are microseconds per decode. Change = (candidate median / baseline median - 1) × 100; "
             "positive means slower. Paired range shows the minimum/maximum slowdown across corresponding rounds.",
             "", "## Results", "",
             f"| Case | JSON bytes | Base µs | {candidate_label} µs | Change | Paired range |",
             "|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f"| {row['name']} | {row['bytes']} | {row['base_us']:.3f} | {row['pr_us']:.3f} | "
                     f"{row['regression_percent']:+.1f}% | {row['paired_min_percent']:+.1f}% … "
                     f"{row['paired_max_percent']:+.1f}% |")
    lines += ["", "## Scope and reproduction", "",
              "These are synthetic, cached, in-process decoder workloads on one machine. Request/response cases "
              "use the repository's real HostToPluginMessage/PluginToHostMessage types but synthetic source text. "
              "They do not measure pipe I/O, macro expansion, parsing, full compiler throughput, or real-world "
              "message frequency. Single-machine wall-clock timings have noise; interpret small changes cautiously.",
              "", "The original mixed pattern contains quotes and takes the escaped-string path; mixed-no-escapes "
              "is an additional unescaped mixed-text case. Request/response source strings contain newlines, "
              "which JSON.encode escapes. Sparse CJK is ASCII with one trailing Chinese character; Unicode escapes "
              "contain only ASCII JSON bytes. Ignored cases decode an object to an empty type.", "",
              "```sh", shlex.join(["python3", "Benchmarks/JSONDecoding/run.py", *sys.argv[1:]]), "```", "",
              f"Raw samples: `{arguments.output}.json`. Summary: `{arguments.output}-summary.json`. "
              "Sources/binaries and the iteration plan are under the ignored `.build/` directory. "
              "The harness does not switch branches, modify production sources, or commit.", ""]
    report = HERE / f"{arguments.output}.md"
    report.write_text("\n".join(lines))
    print(f"Report written: {report}", flush=True)
    for row in rows:
        print(f"{row['name']:38s} {row['base_us']:10.3f} -> {row['pr_us']:10.3f} us "
              f"({row['regression_percent']:+.1f}%)", flush=True)


if __name__ == "__main__":
    main()
