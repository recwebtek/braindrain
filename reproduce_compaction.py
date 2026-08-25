
import time
from braindrain.session import SessionSummary
from braindrain.session_compaction import build_compact_package

def reproduce_bottleneck():
    print("Reproducing build_compact_package bottleneck...")
    summary = SessionSummary(
        session_id="test-session-" + "x" * 100,
        start_time=time.time(),
        key_decisions=["Decision " + str(i) + " " + "d" * 500 for i in range(200)],
        files_modified=["file_" + str(i) + ".py" for i in range(200)],
        errors=["Error " + str(i) + " " + "e" * 500 for i in range(200)],
        open_todos=["Todo " + str(i) + " " + "t" * 500 for i in range(200)],
        tools_used={f"tool_{i}": i for i in range(200)}
    )

    start = time.perf_counter()
    for _ in range(100):
        package = build_compact_package(summary, max_bytes=1000)
    end = time.perf_counter()

    print(f"Time taken for 100 runs: {end - start:.4f}s")
    print(f"Result size: {package['bytes']} bytes")
    print(f"Truncated: {package['truncated']}")

def reproduce_infinite_loop():
    print("\nReproducing infinite loop...")
    summary = SessionSummary(
        session_id="x" * 2500,
        start_time=time.time(),
        key_decisions=["d" * 10],
    )

    print("This should not hang...")
    package = build_compact_package(summary, max_bytes=1000)
    print(f"Finished! Size: {package['bytes']}")

if __name__ == "__main__":
    reproduce_bottleneck()
    reproduce_infinite_loop()
