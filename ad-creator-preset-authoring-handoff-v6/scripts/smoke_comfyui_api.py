from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NODES = {
    "AD_GeminiProductAnalyze",
    "AD_ResolveSceneReference",
    "AD_ResolveReferenceSceneGraph",
    "AD_LoadMoodPackage",
    "AD_BuildGenerationRequest",
    "AD_BuildSceneGenerationRequest",
    "AD_FakeGenerate",
    "AD_FakeQualityRoute",
    "AD_HiggsfieldGenerate",
    "AD_OpenAIImageGenerate",
    "AD_GeminiQualityOnly",
    "AD_InstagramCrop",
    "AD_ApplyMoodGrade",
    "AD_SaveRunManifest",
}


def _resolve_workflow_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


async def _upload_image(
    session: aiohttp.ClientSession,
    server: str,
    image_path: Path,
    upload_filename: str,
) -> str:
    form = aiohttp.FormData()
    with image_path.open("rb") as handle:
        form.add_field(
            "image",
            handle,
            filename=upload_filename,
            content_type=mimetypes.guess_type(upload_filename)[0]
            or "application/octet-stream",
        )
        form.add_field("type", "input")
        form.add_field("overwrite", "true")
        async with session.post(f"{server}/upload/image", data=form) as response:
            payload = await response.json()
            if response.status >= 400:
                raise RuntimeError(f"Image upload failed: {payload}")
    return payload["name"]


async def run_smoke(
    server: str,
    input_image: Path,
    report_path: Path,
    workflow_path: Path,
    mood_package_path: str | None = None,
    reference_image: Path | None = None,
) -> dict:
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    class_types = {node.get("class_type") for node in workflow.values()}
    paid_nodes = sorted(
        {"AD_HiggsfieldGenerate", "AD_OpenAIImageGenerate"} & class_types
    )
    if paid_nodes:
        raise RuntimeError(
            "The zero-credit smoke runner refuses workflows containing "
            f"paid nodes: {paid_nodes}."
        )
    required_fake_nodes = {"AD_FakeGenerate", "AD_FakeQualityRoute"}
    missing_fake_nodes = sorted(required_fake_nodes - class_types)
    if missing_fake_nodes:
        raise RuntimeError(
            f"Zero-credit smoke workflow is missing fake nodes: {missing_fake_nodes}"
        )

    timeout = aiohttp.ClientTimeout(total=180)
    client_id = str(uuid.uuid4())
    parsed = urlparse(server)
    websocket_url = f"ws://{parsed.netloc}/ws?clientId={client_id}"
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{server}/object_info") as response:
            object_info = await response.json()
        missing = sorted(EXPECTED_NODES - set(object_info))
        if missing:
            raise RuntimeError(f"Custom nodes are not registered: {missing}")

        product_suffix = input_image.suffix.lower() or ".png"
        uploaded_name = await _upload_image(
            session,
            server,
            input_image,
            f"ad_creator_input_01{product_suffix}",
        )
        workflow["1"]["inputs"]["image"] = uploaded_name
        uploaded_reference = None
        if reference_image is not None:
            reference_suffix = reference_image.suffix.lower() or ".png"
            uploaded_reference = await _upload_image(
                session,
                server,
                reference_image,
                f"ad_creator_reference_smoke{reference_suffix}",
            )
            if workflow.get("3", {}).get("class_type") != "LoadImage":
                raise RuntimeError("Workflow node 3 must be the scene-reference LoadImage")
            workflow["3"]["inputs"]["image"] = uploaded_reference
        if mood_package_path:
            mood_node = next(
                node
                for node in workflow.values()
                if node["class_type"] == "AD_LoadMoodPackage"
            )
            mood_node["inputs"]["mood_package_path"] = mood_package_path
        for node in workflow.values():
            if node["class_type"] == "AD_FakeGenerate":
                fixture = node["inputs"]["fixture_image_path"].strip()
                if fixture:
                    node["inputs"]["fixture_image_path"] = str(
                        _resolve_workflow_path(fixture)
                    )

        message_types: list[str] = []
        async with session.ws_connect(websocket_url, heartbeat=20) as websocket:
            async with session.post(
                f"{server}/prompt",
                json={"prompt": workflow, "client_id": client_id},
            ) as response:
                submission = await response.json()
                if response.status >= 400 or "prompt_id" not in submission:
                    raise RuntimeError(f"Prompt submission failed: {submission}")
            prompt_id = submission["prompt_id"]

            while True:
                message = await asyncio.wait_for(websocket.receive(), timeout=120)
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
                if message_type in {"execution_error", "execution_interrupted"}:
                    raise RuntimeError(f"Workflow execution failed: {payload}")
                if message_type == "executing" and data.get("node") is None:
                    break
                if message_type == "execution_success":
                    break

        run = None
        for _ in range(20):
            async with session.get(f"{server}/history/{prompt_id}") as response:
                history = await response.json()
            run = history.get(prompt_id)
            if run is not None:
                break
            await asyncio.sleep(0.25)
        if run is None:
            raise RuntimeError(
                f"ComfyUI history did not publish completed prompt {prompt_id} within 5 seconds"
            )
        if run.get("status", {}).get("status_str") != "success":
            raise RuntimeError(f"History did not report success: {run.get('status')}")

        save_node_id = next(
            node_id for node_id, node in workflow.items() if node["class_type"] == "SaveImage"
        )
        manifest_node_id = next(
            node_id
            for node_id, node in workflow.items()
            if node["class_type"] == "AD_SaveRunManifest"
        )
        qa_node_id = next(
            node_id
            for node_id, node in workflow.items()
            if node["class_type"] == "AD_FakeQualityRoute"
        )
        image_record = run["outputs"][save_node_id]["images"][0]
        output_image = (
            ROOT
            / ".tools/ComfyUI/output"
            / image_record.get("subfolder", "")
            / image_record["filename"]
        ).resolve()
        with Image.open(output_image) as opened:
            output_size = list(opened.size)
        if output_size != [880, 1100]:
            raise RuntimeError(f"Unexpected output dimensions: {output_size}")

        manifest_ui = run["outputs"].get(manifest_node_id, {})
        manifest_path = Path(manifest_ui["text"][0]).resolve()
        manifest = json.loads(manifest_path.read_text())
        if manifest["cost"]["actual_credits"] != 0 or manifest["status"] != "completed":
            raise RuntimeError("Manifest did not record a completed zero-credit run")
        qa_ui = run["outputs"].get(qa_node_id, {})
        quality_status = qa_ui.get("text", [None])[0]
        if quality_status not in {"passed", "passed_with_warnings"}:
            raise RuntimeError(f"Unexpected fake QA route: {qa_ui}")
        repair_plan = json.loads(qa_ui.get("repair_plan", ["{}"])[0])
        if (
            repair_plan.get("decision") != "no_repair"
            or repair_plan.get("estimated_credits") != 0
        ):
            raise RuntimeError(f"Zero-credit smoke unexpectedly routed a repair: {repair_plan}")
        request = manifest["request"]
        scene_reference_contract = request.get("scene_reference_contract") or {}

        report = {
            "schema_version": "1.0.0",
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "server": server,
            "comfyui": {
                "commit": "ec0e8b3447d5aa5a91a5a846b7fd94c88318fef7",
                "custom_node_api": "comfy_api.v0_0_2",
                "registered_nodes": sorted(EXPECTED_NODES),
            },
            "workflow": str(workflow_path.relative_to(ROOT)),
            "mood_package_id": request.get("mood_package_id"),
            "lighting_sheet_id": request.get("lighting_sheet", {}).get("id"),
            "container_mode": request.get("identity_policy", {}).get("container"),
            "reference_asset_id": scene_reference_contract.get("asset_id"),
            "prompt_id": prompt_id,
            "websocket_message_types": message_types,
            "uploaded_input": uploaded_name,
            "uploaded_reference": uploaded_reference,
            "output_image": str(output_image),
            "output_size": output_size,
            "manifest": str(manifest_path),
            "request_hash": manifest["request_hash"],
            "actual_credits": manifest["cost"]["actual_credits"],
            "fake_quality_status": quality_status,
            "fake_repair_decision": repair_plan["decision"],
            "status": "passed",
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument(
        "--workflow",
        type=Path,
        default=ROOT / "workflows/01_preserve_source_local_fake_api.json",
    )
    parser.add_argument(
        "--input-image",
        type=Path,
        default=ROOT / ".tools/ComfyUI/input/다운로드.jpeg",
    )
    parser.add_argument(
        "--mood-package",
        help="Override the workflow's AD_LoadMoodPackage path.",
    )
    parser.add_argument(
        "--reference-image",
        type=Path,
        help="Optional scene/container reference to upload into workflow node 3.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "evals/comfyui" / f"{date.today().isoformat()}_local_smoke.json",
    )
    args = parser.parse_args()
    if not args.input_image.is_file():
        raise FileNotFoundError(f"Input image not found: {args.input_image}")
    if args.reference_image is not None and not args.reference_image.is_file():
        raise FileNotFoundError(f"Reference image not found: {args.reference_image}")
    workflow_path = args.workflow.resolve()
    if not workflow_path.is_file():
        raise FileNotFoundError(f"Workflow not found: {workflow_path}")
    report = asyncio.run(
        run_smoke(
            args.server.rstrip("/"),
            args.input_image,
            args.report,
            workflow_path,
            args.mood_package,
            args.reference_image,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
