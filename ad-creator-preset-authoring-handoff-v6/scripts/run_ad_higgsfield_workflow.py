from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import aiohttp


ROOT = Path(__file__).resolve().parents[1]


async def run(workflow_path: Path, report_path: Path, server: str, output_root: Path) -> None:
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    generators = [node for node in workflow.values() if node.get("class_type") == "AD_HiggsfieldGenerate"]
    if len(generators) != 1:
        raise ValueError("Exactly one AD_HiggsfieldGenerate node is required")
    if generators[0]["inputs"].get("repair_execution") != "manual":
        raise ValueError("Automatic paid repair is forbidden")
    if workflow["6"]["inputs"].get("auto_paid_repair") is not False:
        raise ValueError("auto_paid_repair must remain false")

    client_id = str(uuid.uuid4())
    parsed = urlparse(server)
    ws_url = f"ws://{parsed.netloc}/ws?clientId={client_id}"
    timeout = aiohttp.ClientTimeout(total=1300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(ws_url, heartbeat=20) as websocket:
            async with session.post(f"{server}/prompt", json={"prompt": workflow, "client_id": client_id}) as response:
                submission = await response.json()
                if response.status >= 400 or "prompt_id" not in submission:
                    raise RuntimeError(f"Prompt submission failed: {submission}")
            prompt_id = submission["prompt_id"]
            print(json.dumps({"event": "submitted", "prompt_id": prompt_id}), flush=True)
            while True:
                message = await asyncio.wait_for(websocket.receive(), timeout=1200)
                if message.type == aiohttp.WSMsgType.BINARY:
                    continue
                if message.type != aiohttp.WSMsgType.TEXT:
                    raise RuntimeError(f"Unexpected websocket state: {message.type}")
                payload = json.loads(message.data)
                data = payload.get("data", {})
                if data.get("prompt_id") not in {None, prompt_id}:
                    continue
                if payload.get("type") in {"execution_error", "execution_interrupted"}:
                    raise RuntimeError(json.dumps(payload, ensure_ascii=False))
                if payload.get("type") == "executing" and data.get("node") is not None:
                    print(json.dumps({"event": "executing", "node": data["node"]}), flush=True)
                if payload.get("type") == "execution_success" or (payload.get("type") == "executing" and data.get("node") is None):
                    break

        async with session.get(f"{server}/history/{prompt_id}") as response:
            history = await response.json()
    execution = history[prompt_id]
    if execution.get("status", {}).get("status_str") != "success":
        raise RuntimeError(f"Execution did not succeed: {execution.get('status')}")
    image_record = execution["outputs"]["10"]["images"][0]
    image_path = (output_root / image_record.get("subfolder", "") / image_record["filename"]).resolve()
    manifest_path = Path(execution["outputs"]["11"]["text"][0]).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = {
        "schema_version": "1.0.0", "status": "completed", "executed_at": datetime.now(timezone.utc).isoformat(),
        "workflow": str(workflow_path.relative_to(ROOT)), "prompt_id": prompt_id,
        "provider_job_id": manifest["provider"]["job_id"], "actual_credits": manifest["cost"]["actual_credits"],
        "output_image": str(image_path), "manifest": str(manifest_path), "automatic_retry": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--comfy-output", type=Path, default=Path(r"C:\Users\yoosy\Documents\ComfyUI\output"))
    args = parser.parse_args()
    asyncio.run(run(args.workflow.resolve(), args.report.resolve(), args.server.rstrip("/"), args.comfy_output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
