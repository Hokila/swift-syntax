# JSON decoding performance: main vs candidate

Measured: 2026-10-08T14:12:44.534133+08:00

Baseline: `0a52cc4afa724ba5fdbac7b1359be05f673e4792`; candidate: `d000dff207acdba2f83203bcec97daeb8cb9d91d`.

Environment: Apple M3, 16 GiB RAM, macOS 26.6.2, Apple Swift version 6.4 (swift-6.4-RELEASE), arm64.

## Method

- Decoder-only benchmark: all four JSON source files and the actual PluginMessages.swift types are copied directly from each Git revision. Only JSONDecoding.swift differs among compiled Swift files. The C shim headers are copied from each source version as well. The raw data records a fingerprint of all candidate build inputs, flags, and compiler version.
- Both libraries and the separate driver use `-O -whole-module-optimization -swift-version 5`. The driver calls the public SPI JSON.decode API across a module boundary. This isolates the decoder without building all SwiftSyntax dependencies.
- JSON bytes are prepared/encoded before timing, retained in memory, and decoded repeatedly. Input preparation, Foundation reference checks, and console output are outside the timer. Timed work includes decoder output consumption, destruction, and small driver overhead.
- Baseline calibration chooses fixed iteration counts targeting 0.15 seconds per case. Both versions use the same counts. Each case has 9 measured rounds; version order alternates AB/BA, and case order alternates forward/reverse. Each sample is warmed up with up to 128 decodes. Calibration itself is not included in the reported medians.
- Timed loops accumulate a checksum from every decoded result. Paired byte counts, iteration counts, and checksums match. Scalar String results are also compared exactly with Foundation.JSONDecoder before timing. All cases use valid JSON; CJK/emoji cases contain literal UTF-8 bytes.
- Medians below are microseconds per decode. Change = (candidate median / baseline median - 1) × 100; positive means slower. Paired range shows the minimum/maximum slowdown across corresponding rounds.

## Results

| Case | JSON bytes | Base µs | PR µs | Change | Paired range |
|---|---:|---:|---:|---:|---:|
| string/ascii/64 | 92 | 0.165 | 0.167 | +1.1% | -5.5% … +78.7% |
| string/cjk/64 | 68 | 0.188 | 0.182 | -2.9% | -6.6% … +0.6% |
| string/emoji/64 | 66 | 0.191 | 0.190 | -0.5% | -5.8% … +2.3% |
| string/mixed/64 | 74 | 0.308 | 0.267 | -13.3% | -14.7% … -3.6% |
| string/sparse-cjk/64 | 66 | 0.167 | 0.169 | +1.2% | -2.9% … +6.7% |
| string/ascii/4096 | 4112 | 2.154 | 0.902 | -58.1% | -59.4% … -55.5% |
| string/cjk/4096 | 4127 | 4.361 | 3.389 | -22.3% | -23.6% … -20.6% |
| string/emoji/4096 | 4098 | 4.595 | 4.100 | -10.8% | -11.2% … -8.5% |
| string/mixed/4096 | 4358 | 10.368 | 8.009 | -22.8% | -25.7% … -21.0% |
| string/sparse-cjk/4096 | 4098 | 3.112 | 2.016 | -35.2% | -36.2% … -32.8% |
| string/ascii/65536 | 65552 | 32.421 | 12.748 | -60.7% | -61.8% … -59.1% |
| string/cjk/65536 | 65540 | 67.415 | 51.921 | -23.0% | -25.0% … -21.4% |
| string/emoji/65536 | 65538 | 71.405 | 63.806 | -10.6% | -11.6% … -10.2% |
| string/mixed/65536 | 69410 | 162.650 | 125.848 | -22.6% | -23.7% … -21.4% |
| string/sparse-cjk/65536 | 65538 | 47.587 | 34.696 | -27.1% | -27.4% … -23.6% |
| string/mixed-no-escapes/4096 | 4098 | 4.282 | 4.149 | -3.1% | -4.8% … -1.2% |
| string/unicode-escapes/4096 | 4106 | 29.128 | 11.148 | -61.7% | -62.7% … -60.8% |
| array/ascii/128x64 | 12307 | 25.532 | 23.225 | -9.0% | -12.5% … -6.5% |
| array/cjk/128x64 | 9235 | 28.770 | 26.888 | -6.5% | -18.3% … -4.2% |
| array/emoji/128x64 | 8979 | 29.195 | 28.463 | -2.5% | -13.9% … -0.2% |
| array/mixed/128x64 | 10003 | 42.966 | 37.650 | -12.4% | -12.9% … -9.5% |
| ignored/ascii/65536 | 65564 | 30.515 | 11.994 | -60.7% | -65.1% … -39.2% |
| ignored/cjk/65536 | 65552 | 30.533 | 15.023 | -50.8% | -51.4% … -49.9% |
| request/ascii/4096 | 4556 | 9.306 | 8.410 | -9.6% | -11.7% … -3.7% |
| response/ascii/4096 | 4316 | 7.194 | 6.205 | -13.7% | -14.5% … -9.8% |
| request/mixed/4096 | 4784 | 15.612 | 12.439 | -20.3% | -21.8% … -19.7% |
| response/mixed/4096 | 4544 | 13.445 | 10.306 | -23.3% | -24.8% … -22.3% |
| request/ascii/65536 | 67980 | 98.494 | 80.438 | -18.3% | -20.1% … -17.1% |
| response/ascii/65536 | 67740 | 95.554 | 78.609 | -17.7% | -21.8% … -14.3% |
| request/mixed/65536 | 71474 | 198.330 | 148.225 | -25.3% | -27.1% … -23.6% |
| response/mixed/65536 | 71234 | 196.276 | 145.569 | -25.8% | -27.4% … -23.1% |

## Scope and reproduction

These are synthetic, cached, in-process decoder workloads on one machine. Request/response cases use the repository's real HostToPluginMessage/PluginToHostMessage types but synthetic source text. They do not measure pipe I/O, macro expansion, parsing, full compiler throughput, or real-world message frequency. Single-machine wall-clock timings have noise; interpret small changes cautiously.

The original mixed pattern contains quotes and takes the escaped-string path; mixed-no-escapes is an additional unescaped mixed-text case. Request/response source strings contain newlines, which JSON.encode escapes. Sparse CJK is ASCII with one trailing Chinese character; Unicode escapes contain only ASCII JSON bytes. Ignored cases decode an object to an empty type.

```sh
python3 Benchmarks/JSONDecoding/run.py --base-ref 0a52cc4afa724ba5fdbac7b1359be05f673e4792 --candidate-ref d000dff20 --rounds 9 --seconds 0.15 --output results/2026-10-08-main-vs-testJSON
```

Raw samples: `results/2026-10-08-main-vs-testJSON.json`. Summary: `results/2026-10-08-main-vs-testJSON-summary.json`. Sources/binaries and the iteration plan are under the ignored `.build/` directory. The harness does not switch branches, modify production sources, or commit.
