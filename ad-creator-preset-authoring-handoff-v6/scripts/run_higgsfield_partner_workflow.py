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


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_paid_scope(workflow: dict) -> None:
    partner_nodes = [
        (node_id, node)
        for node_id, node in workflow.items()
        if node.get("class_type") == "HiggsfieldImageGenerate"
    ]
    forbidden = {
        "AD_HiggsfieldGenerate",
        "AD_OpenAIImageGenerate",
    }
    present_forbidden = sorted(
        forbidden & {node.get("class_type") for node in workflow.values()}
    )
    if present_forbidden:
        raise ValueError(f"Unexpected paid nodes: {present_forbidden}")
    if len(partner_nodes) != 1:
        raise ValueError("Workflow must contain exactly one HiggsfieldImageGenerate node")
    _node_id, node = partner_nodes[0]
    inputs = node["inputs"]
    if (
        inputs.get("model") != "GPT Image 2"
        or inputs.get("resolution") != "1k"
        or inputs.get("aspect_ratio") != "3:4"
    ):
        raise ValueError("Paid workflow must be GPT Image 2 medium, 1k, 3:4")
    if not isinstance(inputs.get("prompt"), list) or not isinstance(
        inputs.get("image"), list
    ):
        raise ValueError("Prompt and image must remain connected to the v6 compiler")
    save_count = sum(
        node.get("class_type") == "SaveImage" for node in workflow.values()
    )
    metadata_count = sum(
        node.get("class_type") == "SaveHiggsfieldMetadata"
        for node in workflow.values()
    )
    if save_count != 1 or metadata_count != 1:
        raise ValueError("Workflow must save exactly one image and one metadata record")


async def run_once(
    *,
    server: str,
    workflow_path: Path,
    report_path: Path,
    comfy_output: Path,
) -> dict:
    workflow = _load(workflow_path)
    _validate_paid_scope(workflow)
    client_id = str(uuid.uuid4())
    parsed = urlparse(server)
    websocket_url = f"ws://{parsed.netloc}/ws?clientId={client_id}"
    timeout = aiohttp.ClientTimeout(total=1300)
    message_types: list[str] = []
    prompt_id: str | None = None
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(websocket_url, heartbeat=20) as websocket:
            async with session.post(
                f"{server}/prompt",
                json={"prompt": workflow, "client_id": client_id},
            ) as response:
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
                    raise RuntimeError(f"Unexpected WebSocket state: {message.type}")
                payload = json.loads(message.data)
                message_type = payload.get("type", "unknown")
                if message_type not in message_types:
                    message_types.append(message_type)
                data = payload.get("data", {})
                if data.get("prompt_id") not in {None, prompt_id}:
                    continue
                if message_type == "executing" and data.get("node") is not None:
                    print(
                        json.dumps(
                            {"event": "executing", "node": data.get("node")}
                        ),
                        flush=True,
                    )
                if message_type in {"execution_error", "execution_interrupted"}:
                    raise RuntimeError(
                        "Workflow failed; no automatic retry is allowed: "
                        + json.dumps(payload, ensure_ascii=False)
                    )
                if message_type == "execution_success":
                    break
                if message_type == "executing" and data.get("node") is None:
                    break

        history = {}
        for _ in range(20):
            async with session.get(f"{server}/history/{prompt_id}") as response:
                history = await response.json()
            if prompt_id in history:
                break
            await asyncio.sleep(0.5)
        if prompt_id not in history:
            raise RuntimeError(f"History was not available after execution: {prompt_id}")
    run = history[prompt_id]
    if run.get("status", {}).get("status_str") != "success":
        raise RuntimeError(f"History did not report success: {run.get('status')}")

    save_node_id = next(
        node_id
        for node_id, node in workflow.items()
        if node.get("class_type") == "SaveImage"
    )
    metadata_node_id = next(
        node_id
        for node_id, node in workflow.items()
        if node.get("class_type") == "SaveHiggsfieldMetadata"
    )
    image_record = run["outputs"][save_node_id]["images"][0]
    image_path = (
        comfy_output
        / image_record.get("subfolder", "")
        / image_record["filename"]
    ).resolve()
    metadata_output = run["outputs"].get(metadata_node_id, {})
    metadata_path = Path(metadata_output["text"][0]).resolve()
    metadata = _load(metadata_path)
    report = {
        "schema_version": "1.0.0",
        "status": "completed",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "server": server,
        "workflow": str(workflow_path.relative_to(ROOT)),
        "prompt_id": prompt_id,
        "provider_job_id": metadata["job_id"],
        "display_model": metadata["display_model"],
        "job_type": metadata["job_type"],
        "quality": metadata["quality"],
        "resolution": metadata["resolution"],
        "output_image": str(image_path),
        "metadata": str(metadata_path),
        "width": metadata["width"],
        "height": metadata["height"],
        "message_types": message_types,
        "automatic_retry": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run exactly one prevalidated Higgsfield partner workflow without retry."
    )
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument(
        "--comfy-output",
        type=Path,
        default=Path(r"C:\Users\yoosy\Documents\ComfyUI\output"),
    )
    args = parser.parse_args()
    asyncio.run(
        run_once(
            server=args.server.rstrip("/"),
            workflow_path=args.workflow.resolve(),
            report_path=args.report.resolve(),
            comfy_output=args.comfy_output.resolve(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
