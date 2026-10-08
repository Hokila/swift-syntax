//===----------------------------------------------------------------------===//
//
// This source file is part of the Swift.org open source project
//
// Copyright (c) 2026 The Swift project authors
// Licensed under Apache License v2.0 with Runtime Library Exception
//
// See https://swift.org/LICENSE.txt for license information
// See https://swift.org/CONTRIBUTORS.txt for the list of Swift project authors
//
//===----------------------------------------------------------------------===//

import Dispatch
import Foundation
@_spi(PluginMessage) import JSONBenchmarkSupport

// JSON input creation, encoding, and correctness checks are outside the timer.
// Compile this driver separately from the decoder to prevent cross-module
// specialization from turning it into a benchmark of a different code path.
struct Empty: Decodable {}

struct Workload {
  let name: String
  let bytes: [UInt8]
  let expectedChecksum: Int
  let decode: (UnsafeBufferPointer<UInt8>) throws -> Int
}

@inline(never)
func decodeString(_ bytes: UnsafeBufferPointer<UInt8>) throws -> Int {
  try JSON.decode(String.self, from: bytes).utf8.count
}

@inline(never)
func decodeArray(_ bytes: UnsafeBufferPointer<UInt8>) throws -> Int {
  try JSON.decode([String].self, from: bytes).reduce(0) { $0 + $1.utf8.count }
}

@inline(never)
func decodeIgnored(_ bytes: UnsafeBufferPointer<UInt8>) throws -> Int {
  _ = try JSON.decode(Empty.self, from: bytes)
  return 1
}

@inline(never)
func decodeRequest(_ bytes: UnsafeBufferPointer<UInt8>) throws -> Int {
  let message = try JSON.decode(HostToPluginMessage.self, from: bytes)
  guard case .expandFreestandingMacro(_, _, _, let syntax, _, _) = message else {
    fatalError("Unexpected message")
  }
  return syntax.source.utf8.count
}

@inline(never)
func decodeResponse(_ bytes: UnsafeBufferPointer<UInt8>) throws -> Int {
  let message = try JSON.decode(PluginToHostMessage.self, from: bytes)
  guard case .expandMacroResult(let source, _) = message else {
    fatalError("Unexpected message")
  }
  return source!.utf8.count
}

func repeated(_ unit: String, atLeastUTF8Bytes size: Int) -> String {
  String(repeating: unit, count: (size + unit.utf8.count - 1) / unit.utf8.count)
}

func workloads() throws -> [Workload] {
  var result: [Workload] = []
  let patterns = [
    ("ascii", "let value = identifier + 123; "),
    ("cjk", "中文測試日本語かなカナ"),
    ("emoji", "😀🚀🛑🌍"),
    ("mixed", "let 名稱 = \"hello 世界 🌍\"; "),
  ]
  for size in [64, 4096, 65536] {
    for (name, unit) in patterns {
      let value = repeated(unit, atLeastUTF8Bytes: size)
      let bytes = try JSON.encode(value)
      result.append(
        Workload(
          name: "string/\(name)/\(size)",
          bytes: bytes,
          expectedChecksum: value.utf8.count,
          decode: decodeString
        )
      )
    }
    let value = String(repeating: "a", count: size - 3) + "中"
    result.append(
      Workload(
        name: "string/sparse-cjk/\(size)",
        bytes: try JSON.encode(value),
        expectedChecksum: value.utf8.count,
        decode: decodeString
      )
    )
  }
  // Same mixed text without JSON escapes; contrasts with mixed above, whose
  // embedded double quotes take the escaped-string decoding path.
  let unescapedMixed = repeated("let 名稱 = hello 世界 🌍; ", atLeastUTF8Bytes: 4096)
  result.append(
    Workload(
      name: "string/mixed-no-escapes/4096",
      bytes: try JSON.encode(unescapedMixed),
      expectedChecksum: unescapedMixed.utf8.count,
      decode: decodeString
    )
  )
  // ASCII JSON bytes even though the resulting Swift String contains Unicode.
  let escapeBytes = Array(("\"" + String(repeating: #"\u4E2D\u6587"#, count: 342) + "\"").utf8)
  result.append(
    Workload(
      name: "string/unicode-escapes/4096",
      bytes: escapeBytes,
      expectedChecksum: 342 * 6,
      decode: decodeString
    )
  )
  for (name, unit) in patterns {
    let values = (0..<128).map { index in "\(index):" + repeated(unit, atLeastUTF8Bytes: 64) }
    result.append(
      Workload(
        name: "array/\(name)/128x64",
        bytes: try JSON.encode(values),
        expectedChecksum: values.reduce(0) { $0 + $1.utf8.count },
        decode: decodeArray
      )
    )
  }
  for (name, unit) in [patterns[0], patterns[1]] {
    let value = repeated(unit, atLeastUTF8Bytes: 65536)
    result.append(
      Workload(
        name: "ignored/\(name)/65536",
        bytes: try JSON.encode(["ignored": value]),
        expectedChecksum: 1,
        decode: decodeIgnored
      )
    )
  }
  // Use the actual repository message types, not an approximation of their schema.
  for size in [4096, 65536] {
    for (name, unit) in [patterns[0], patterns[3]] {
      let source = repeated(unit + "\n", atLeastUTF8Bytes: size)
      let location = PluginMessage.SourceLocation(
        fileID: "Test/input.swift",
        fileName: "/tmp/input.swift",
        offset: 0,
        line: 1,
        column: 1
      )
      let syntax = PluginMessage.Syntax(kind: .expression, source: source, location: location)
      let request = HostToPluginMessage.expandFreestandingMacro(
        macro: .init(moduleName: "TestMacros", typeName: "TestMacro", name: "test"),
        macroRole: .expression,
        discriminator: "benchmark",
        syntax: syntax
      )
      result.append(
        Workload(
          name: "request/\(name)/\(size)",
          bytes: try JSON.encode(request),
          expectedChecksum: source.utf8.count,
          decode: decodeRequest
        )
      )
      let response = PluginToHostMessage.expandMacroResult(expandedSource: source, diagnostics: [])
      result.append(
        Workload(
          name: "response/\(name)/\(size)",
          bytes: try JSON.encode(response),
          expectedChecksum: source.utf8.count,
          decode: decodeResponse
        )
      )
    }
  }
  // Assert exact String contents (not just counts) before any measurement.
  for item in result {
    try item.bytes.withUnsafeBufferPointer { bytes in
      let checksum = try item.decode(bytes)
      precondition(checksum == item.expectedChecksum, item.name)
      if item.name.hasPrefix("string/") {
        let reference = try Foundation.JSONDecoder().decode(String.self, from: Data(item.bytes))
        let decoded = try JSON.decode(String.self, from: bytes)
        precondition(decoded == reference, item.name)
      }
    }
  }
  return result
}

struct Plan: Codable { let name: String; let iterations: Int }
struct Measurement: Codable {
  let name: String
  let bytes: Int
  let iterations: Int
  let elapsedNS: UInt64
  let checksum: Int
}

@inline(never)
func measure(_ workload: Workload, iterations: Int) throws -> Measurement {
  try workload.bytes.withUnsafeBufferPointer { bytes in
    var checksum = 0
    let start = DispatchTime.now().uptimeNanoseconds
    for _ in 0..<iterations { checksum &+= try workload.decode(bytes) }
    let elapsed = DispatchTime.now().uptimeNanoseconds - start
    precondition(checksum == workload.expectedChecksum * iterations, workload.name)
    return Measurement(
      name: workload.name,
      bytes: bytes.count,
      iterations: iterations,
      elapsedNS: elapsed,
      checksum: checksum
    )
  }
}

let cases = try workloads()
let arguments = CommandLine.arguments
if arguments[1] == "calibrate" {
  let targetNS = Double(arguments[2])! * 1_000_000_000
  var plan: [Plan] = []
  for item in cases {
    _ = try measure(item, iterations: 128)
    var iterations = 1
    var sample = try measure(item, iterations: iterations)
    while sample.elapsedNS < 30_000_000 {
      iterations *= 2
      sample = try measure(item, iterations: iterations)
    }
    let count = max(1, Int(Double(iterations) * targetNS / Double(sample.elapsedNS)))
    plan.append(Plan(name: item.name, iterations: count))
  }
  print(String(decoding: try Foundation.JSONEncoder().encode(plan), as: UTF8.self))
} else {
  let plan = try Foundation.JSONDecoder().decode(
    [Plan].self,
    from: Data(contentsOf: URL(fileURLWithPath: arguments[2]))
  )
  let selected = arguments.count > 3 ? Array(plan.reversed()) : plan
  var measurements: [Measurement] = []
  for entry in selected {
    let item = cases.first { $0.name == entry.name }!
    _ = try measure(item, iterations: min(entry.iterations, 128))
    measurements.append(try measure(item, iterations: entry.iterations))
  }
  print(String(decoding: try Foundation.JSONEncoder().encode(measurements), as: UTF8.self))
}
