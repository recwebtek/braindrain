
import json
from pathlib import Path
from braindrain.telemetry import TelemetrySession
from braindrain.token_checkpoints import append_checkpoint

def test_repro_leak():
    log_file = Path("test_telemetry.jsonl")
    checkpoint_file = Path("test_checkpoints.jsonl")

    if log_file.exists(): log_file.unlink()
    if checkpoint_file.exists(): checkpoint_file.unlink()

    telemetry = TelemetrySession(log_file=log_file)

    # Sensitive info in note
    note = "Testing with secret password: hunter2 and path /Users/jules/secret"

    result = append_checkpoint(
        phase="start",
        task="test-task",
        note=note,
        telemetry=telemetry,
        path=checkpoint_file
    )

    content = checkpoint_file.read_text()
    print(f"Checkpoint file content: {content}")

    if "hunter2" in content or "jules" in content:
        print("RESULT: LEAK DETECTED in file!")
    else:
        print("RESULT: NO LEAK in file.")

    returned_note = result["checkpoint"]["note"]
    print(f"Returned note: {returned_note}")
    if "hunter2" in returned_note:
        print("RESULT: Original data preserved in return value.")
    else:
        print("RESULT: Data was redacted in return value.")

    if log_file.exists(): log_file.unlink()
    if checkpoint_file.exists(): checkpoint_file.unlink()

if __name__ == "__main__":
    test_repro_leak()
