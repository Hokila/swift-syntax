# JSON decoding benchmarks

Measurement evidence for the JSON string-validation and scanning changes on `testJSON`. The implementation PR uses `testJSON`; this directory is committed separately on `JSONBenchmark`.

## Recorded comparison

- Baseline (`main`): `0a52cc4afa724ba5fdbac7b1359be05f673e4792`
- Candidate (`testJSON`): `d000dff207acdba2f83203bcec97daeb8cb9d91d`
- Date: 2026-10-08 (Asia/Taipei). Apple M3, 16 GiB RAM, macOS 26.6.2, Apple Swift 6.4, arm64.
- Release flags: `-O -whole-module-optimization -swift-version 5`.
- 31 valid-JSON workloads, nine measured rounds per revision. Median microseconds per decode; negative changes mean less time.

| Workload | main µs | testJSON µs | Time change |
|---|---:|---:|---:|
| ASCII string (~64 KiB) | 32.421 | 12.748 | -60.7% |
| CJK string (~64 KiB) | 67.415 | 51.921 | -23.0% |
| Emoji string (~64 KiB) | 71.405 | 63.806 | -10.6% |
| ASCII macro request (~4 KiB source) | 9.306 | 8.410 | -9.6% |
| Mixed macro request (~64 KiB source) | 198.330 | 148.225 | -25.3% |
| Mixed macro response (~64 KiB source) | 196.276 | 145.569 | -25.8% |

Macro request/response cases improve by approximately 9.6–25.8%. Some small-string medians are slightly positive (up to ~1.2%), so this is not a claim that every case is faster.

## Reproduce

Requires macOS, Git, Python 3, and a Swift compiler. No Python packages are needed. The runner currently uses macOS dynamic-library linking and system-information commands.
Run from the repository root. The exact commits below are ancestors of this benchmark branch and remain reproducible after the implementation PR is merged or branch names change.

```sh
python3 Benchmarks/JSONDecoding/run.py --base-ref 0a52cc4afa724ba5fdbac7b1359be05f673e4792 --candidate-ref d000dff207acdba2f83203bcec97daeb8cb9d91d --rounds 9 --seconds 0.15 --output results/reproduced-main-vs-testJSON
```

For the current local branch tips:

```sh
python3 Benchmarks/JSONDecoding/run.py --base-ref main --candidate-ref testJSON --rounds 9 --seconds 0.15 --output results/new-main-vs-testJSON
```

References are resolved to commit SHAs before building. `--reuse-build` can reuse artifacts only when the source, driver, compiler version, and build flags match. `--case <name>` selects specific workloads; names are listed in the report.

## Method and limits

- All four JSON implementation files, the actual `PluginMessages.swift` types, and C shim headers are extracted directly from each Git revision. Only `JSONDecoding.swift` differs among the compiled Swift files in this comparison.
- Baseline and candidate libraries are compiled separately. An independently compiled Swift driver calls the public SPI `JSON.decode` API across a module boundary.
- JSON generation/encoding and reference checking are outside timing. Prepared byte buffers are decoded repeatedly; timing includes output consumption, destruction, and small driver overhead.
- Baseline calibration targets 0.15 seconds per case and chooses shared fixed iteration counts. Samples are warmed up; version order alternates AB/BA, and case order alternates forward/reverse.
- Every result contributes to a checksum. Paired byte counts, iteration counts, and output checksums match across all 558 case samples. Scalar strings are also checked against Foundation JSONDecoder before measurement.
- Payloads cover literal CJK/emoji UTF-8, sparse Unicode, JSON escapes, small-string arrays, ignored fields, and actual macro message types with synthetic Swift source text. Macro sizes describe source text; complete JSON includes additional schema and escapes.
- These are cached, in-process, synthetic decoder workloads on one machine. Pipe I/O, macro expansion, total compiler throughput, real-world message frequency, other hardware, and other toolchains are not measured. Interpret small wall-clock differences cautiously.

## Files

- [Swift benchmark driver](Benchmark.swift)
- [Build, measure, and summarize runner](run.py)
- [Full 31-case report and paired ranges](results/2026-10-08-main-vs-testJSON.md)
- [Raw samples, iteration plan, environment, pinned SHAs and source fingerprints](results/2026-10-08-main-vs-testJSON.json)
- [Computed medians and changes](results/2026-10-08-main-vs-testJSON-summary.json)

The `.build/` directory contains extracted source snapshots, libraries, executables, and calibration plans. It is ignored by Git. The runner does not change branches, production sources, or commits. Raw timing data and generated reports under `results/` are intentionally tracked.
