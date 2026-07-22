import base64
import binascii
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import ssl
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageOps


COMFYUI_PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRESET_REGISTRY = COMFYUI_PACKAGE_ROOT / "presets" / "registry.json"
MAX_RESPONSE_IMAGE_BYTES = 50 * 1024 * 1024
MAX_RESPONSE_JSON_BYTES = 72 * 1024 * 1024
MAX_INPUT_IMAGE_BYTES = 50 * 1024 * 1024
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class OpenAIImageExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        request_id: str | None = None,
        client_request_id: str | None = None,
    ):
        self.code = code
        self.request_id = request_id
        self.client_request_id = client_request_id
        trace = ""
        if request_id:
            trace += f" request_id={request_id[:128]}"
        if client_request_id:
            trace += f" client_request_id={client_request_id[:128]}"
        super().__init__(f"[{code}] {message}{trace}")


@dataclass(frozen=True)
class OpenAIHTTPResponse:
    payload: dict[str, Any]
    request_id: str | None = None


Transport = Callable[
    [str, dict[str, str], bytes, float],
    OpenAIHTTPResponse | dict[str, Any],
]


@dataclass(frozen=True)
class PublishedPreset:
    slot_id: str
    preset_id: str
    prompt: str
    provider_profile: dict[str, Any]
    provider_image_paths: tuple[Path, ...]
    provider_image_roles: tuple[str, ...]
    aspect_ratio: str
    aspect_status: str
    delivery_width: int
    delivery_height: int
    bbox_qa: dict[str, Any]
    bundle_sha256: str
    prompt_sha256: str
    provider_profile_sha256: str


def published_preset_slots(
    *,
    registry_path: str | Path = DEFAULT_PRESET_REGISTRY,
) -> tuple[str, ...]:
    """Return the enabled, published service slots in registry order."""
    registry = _read_json(Path(registry_path).resolve())
    if registry.get("schema_version") != 1:
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset registry schema_version must be 1."
        )
    slots = registry.get("slots")
    if not isinstance(slots, dict):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset registry slots must be an object."
        )
    published = tuple(
        slot_id
        for slot_id, value in slots.items()
        if isinstance(value, dict)
        and value.get("enabled") is True
        and value.get("status") == "published"
    )
    if not published:
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset registry has no published slots."
        )
    return published


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", f"Cannot read JSON: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", f"JSON must be an object: {path.name}"
        )
    return value


def _safe_path(root: Path, base: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or Path(relative_path).is_absolute():
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset paths must be non-empty and relative."
        )
    candidate = (base / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset path escapes the published asset root."
        ) from exc
    if not candidate.is_file():
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", f"Published asset is missing: {candidate.name}"
        )
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _verified_asset(
    *, preset_root: Path, bundle_dir: Path, binding: dict[str, Any], label: str
) -> Path:
    path = _safe_path(preset_root, bundle_dir, str(binding.get("path") or ""))
    expected = binding.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64 or _sha256(path) != expected:
        raise OpenAIImageExecutionError(
            "PRESET_ASSET_HASH_MISMATCH", f"Published {label} changed: {path.name}"
        )
    return path


def _compact(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _lighting_prompt(sheet: dict[str, Any]) -> str:
    key = sheet.get("key_light") if isinstance(sheet.get("key_light"), dict) else {}
    shadow = (
        sheet.get("shadow_contract")
        if isinstance(sheet.get("shadow_contract"), dict)
        else {}
    )
    capture = (
        sheet.get("capture_contract")
        if isinstance(sheet.get("capture_contract"), dict)
        else {}
    )
    forbidden = sheet.get("forbidden") if isinstance(sheet.get("forbidden"), list) else []
    required = (
        sheet.get("lighting_sheet_id"),
        sheet.get("mood"),
        key.get("source"),
        key.get("direction"),
        key.get("relative_size"),
        shadow.get("edge"),
        capture.get("white_balance"),
    )
    if any(not isinstance(item, str) or not item.strip() for item in required):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Lighting sheet is missing an authoritative field."
        )
    return (
        f"Sheet={_compact(sheet['lighting_sheet_id'], 100)}. "
        f"Mood={_compact(sheet['mood'])}. "
        f"Key={_compact(key['source'])}; direction={_compact(key['direction'])}; "
        f"apparent size={_compact(key['relative_size'])}. "
        f"Ambient={_compact(sheet.get('ambient_fill'))}. "
        f"Shadow edge={_compact(shadow['edge'])}; attachment={_compact(shadow.get('attachment'))}. "
        f"White balance={_compact(capture['white_balance'])}; "
        f"texture={_compact(capture.get('texture'))}. "
        f"Reject={'; '.join(_compact(item, 90) for item in forbidden[:8])}."
    )


def _provider_profile(
    registry: dict[str, Any], registry_path: Path, aspect_ratio: str
) -> dict[str, Any]:
    package_root = registry_path.parent.parent.resolve()
    profile_path = _safe_path(
        package_root,
        registry_path.parent,
        str(registry.get("provider_profile") or ""),
    )
    profile = _read_json(profile_path)
    required = {
        "provider": "openai_images_api",
        "model": "gpt-image-2",
        "quality": "low",
        "endpoint": "https://api.openai.com/v1/images/edits",
        "output_format": "png",
        "automatic_retries": 0,
    }
    for field, expected in required.items():
        if profile.get(field) != expected:
            raise OpenAIImageExecutionError(
                "INVALID_PROVIDER_PROFILE",
                f"OpenAI pilot requires {field}={expected!r}.",
            )
    if profile.get("default_aspect_ratio") != "4:5":
        raise OpenAIImageExecutionError(
            "INVALID_PROVIDER_PROFILE", "OpenAI pilot default aspect ratio must be 4:5."
        )
    if "input_fidelity" in profile:
        raise OpenAIImageExecutionError(
            "INVALID_PROVIDER_PROFILE",
            "gpt-image-2 always uses high-fidelity inputs; input_fidelity must be omitted.",
        )
    aspect_ratios = profile.get("aspect_ratios")
    if not isinstance(aspect_ratios, dict) or set(aspect_ratios) != {"4:5", "1:1"}:
        raise OpenAIImageExecutionError(
            "INVALID_PROVIDER_PROFILE", "Provider aspect-ratio settings are invalid."
        )
    if aspect_ratio not in aspect_ratios:
        raise OpenAIImageExecutionError(
            "UNSUPPORTED_ASPECT_RATIO", f"Unsupported aspect ratio: {aspect_ratio}"
        )
    expected_aspects = {
        "4:5": {
            "status": "published",
            "size": "1024x1280",
            "delivery_size": [880, 1100],
            "safe_crop": "none_exact_4x5",
        },
        "1:1": {
            "status": "prepared_pending_visual_qa",
            "size": "1024x1024",
            "delivery_size": [1024, 1024],
            "safe_crop": "none_exact_1x1",
        },
    }
    for ratio, expected in expected_aspects.items():
        contract = aspect_ratios.get(ratio)
        if not isinstance(contract, dict) or any(
            contract.get(field) != value for field, value in expected.items()
        ):
            raise OpenAIImageExecutionError(
                "INVALID_PROVIDER_PROFILE", f"Provider {ratio} contract is invalid."
            )
    preprocessing = profile.get("source_preprocessing")
    expected_preprocessing = {
        "default_max_long_edge": 1536,
        "comparison_max_long_edges": [1536, 3072],
        "upscale_small_inputs": False,
        "strip_metadata": True,
        "normalized_format": "jpeg",
        "jpeg_quality": 95,
    }
    if not isinstance(preprocessing, dict) or any(
        preprocessing.get(field) != value
        for field, value in expected_preprocessing.items()
    ):
        raise OpenAIImageExecutionError(
            "INVALID_PROVIDER_PROFILE", "Provider source preprocessing is invalid."
        )
    if profile.get("moderation") != "auto" or profile.get("maximum_input_images") != 16:
        raise OpenAIImageExecutionError(
            "INVALID_PROVIDER_PROFILE",
            "Pilot moderation and maximum image-input settings are invalid.",
        )
    selected = dict(profile)
    selected_contract = aspect_ratios[aspect_ratio]
    selected.update(
        {
            "aspect_ratio": aspect_ratio,
            "aspect_status": selected_contract["status"],
            "size": selected_contract["size"],
            "delivery_size": selected_contract["delivery_size"],
            "safe_crop": selected_contract["safe_crop"],
        }
    )
    return selected


def load_published_preset(
    slot_id: str,
    *,
    aspect_ratio: str = "4:5",
    registry_path: str | Path = DEFAULT_PRESET_REGISTRY,
) -> PublishedPreset:
    registry_path = Path(registry_path).resolve()
    registry = _read_json(registry_path)
    if registry.get("schema_version") != 1:
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset registry schema_version must be 1."
        )
    slots = registry.get("slots")
    if not isinstance(slots, dict) or slot_id not in slots:
        raise OpenAIImageExecutionError("UNKNOWN_PRESET", f"Unknown preset slot: {slot_id}")
    slot = slots[slot_id]
    if not isinstance(slot, dict) or not slot.get("enabled") or slot.get("status") != "published":
        raise OpenAIImageExecutionError("PRESET_NOT_READY", f"Preset is not published: {slot_id}")

    preset_root = registry_path.parent.resolve()
    bundle_path = _safe_path(
        preset_root, preset_root, str(slot.get("bundle") or "")
    )
    bundle = _read_json(bundle_path)
    if (
        bundle.get("schema_version") != 1
        or bundle.get("slot_id") != slot_id
        or bundle.get("preset_id") != slot.get("preset_id")
        or bundle.get("family") != slot.get("family")
        or bundle.get("composition") != slot.get("composition")
        or bundle.get("status") != "published"
        or bundle.get("source_review_status") != "passed_by_user_review"
    ):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset registry and bundle do not match."
        )
    bundle_dir = bundle_path.parent
    prompt_binding = bundle.get("prompt_template")
    lighting_binding = bundle.get("lighting_sheet")
    grade_binding = bundle.get("grade_profile")
    if not all(isinstance(value, dict) for value in (prompt_binding, lighting_binding, grade_binding)):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset bundle is missing prompt, lighting, or grade."
        )
    prompt_path = _verified_asset(
        preset_root=preset_root,
        bundle_dir=bundle_dir,
        binding=prompt_binding,
        label="prompt template",
    )
    lighting_path = _verified_asset(
        preset_root=preset_root,
        bundle_dir=bundle_dir,
        binding=lighting_binding,
        label="lighting sheet",
    )
    _verified_asset(
        preset_root=preset_root,
        bundle_dir=bundle_dir,
        binding=grade_binding,
        label="grade profile",
    )
    if grade_binding.get("apply_in_pilot") is not False:
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION",
            "Pilot grade profile must remain review-only.",
        )

    hint_bindings = bundle.get("hint_images")
    if not isinstance(hint_bindings, list):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset hint_images must be a list."
        )
    provider_paths: list[Path] = []
    provider_roles: list[str] = []
    all_hint_roles: list[tuple[str, bool]] = []
    for item in hint_bindings:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise OpenAIImageExecutionError(
                "INVALID_PRESET_CONFIGURATION", "Preset hint binding is invalid."
            )
        hint_path = _verified_asset(
            preset_root=preset_root,
            bundle_dir=bundle_dir,
            binding=item,
            label="hint image",
        )
        if not isinstance(item.get("send_to_provider"), bool):
            raise OpenAIImageExecutionError(
                "INVALID_PRESET_CONFIGURATION",
                "Hint image must declare send_to_provider as a boolean.",
            )
        try:
            with Image.open(hint_path) as hint_image:
                dimensions = [hint_image.width, hint_image.height]
                hint_image.verify()
        except (OSError, Image.DecompressionBombError) as exc:
            raise OpenAIImageExecutionError(
                "INVALID_PRESET_CONFIGURATION", "Published hint image is invalid."
            ) from exc
        if dimensions != [item.get("width"), item.get("height")]:
            raise OpenAIImageExecutionError(
                "PRESET_ASSET_DIMENSION_MISMATCH",
                f"Published hint dimensions changed: {hint_path.name}",
            )
        sent = item.get("send_to_provider") is True
        all_hint_roles.append((item["role"], sent))
        if sent:
            provider_paths.append(hint_path)
            provider_roles.append(item["role"])

    input_lines = [
        "Image 1 is the exact user product source and the only product-identity authority."
    ]
    for index, role in enumerate(provider_roles, start=2):
        input_lines.append(f"Image {index} is the published {role.replace('_', ' ')}.")
    offline_roles = [role for role, sent in all_hint_roles if not sent]
    if offline_roles:
        input_lines.append(
            "The following checked-in assets are authoring or review evidence only and are not sent: "
            + ", ".join(role.replace("_", " ") for role in offline_roles)
            + "."
        )

    try:
        template = prompt_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Cannot read preset prompt template."
        ) from exc
    if (
        template.count("{{INPUT_ROLES}}") != 1
        or template.count("{{LIGHTING_CONTRACT}}") != 1
        or template.count("{{ASPECT_CONTRACT}}") != 1
    ):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Prompt template placeholders are invalid."
        )
    aspect_contracts = bundle.get("aspect_ratio_contracts")
    if not isinstance(aspect_contracts, dict) or set(aspect_contracts) != {"4:5", "1:1"}:
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset aspect-ratio contracts are invalid."
        )
    aspect_contract = aspect_contracts.get(aspect_ratio)
    if not isinstance(aspect_contract, dict):
        raise OpenAIImageExecutionError(
            "UNSUPPORTED_ASPECT_RATIO", f"Unsupported aspect ratio: {aspect_ratio}"
        )
    prompt_addendum = aspect_contract.get("prompt_addendum")
    bbox_qa = aspect_contract.get("bbox_qa")
    if (
        not isinstance(prompt_addendum, str)
        or not prompt_addendum.strip()
        or not isinstance(bbox_qa, dict)
        or bbox_qa.get("crop_allowed") is not False
    ):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset aspect prompt or bbox QA is invalid."
        )
    prompt = (
        template.replace("{{INPUT_ROLES}}", "\n".join(input_lines))
        .replace("{{LIGHTING_CONTRACT}}", _lighting_prompt(_read_json(lighting_path)))
        .replace("{{ASPECT_CONTRACT}}", prompt_addendum.strip())
    )
    if "{{" in prompt or "}}" in prompt:
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Prompt template has unresolved placeholders."
        )

    profile = _provider_profile(registry, registry_path, aspect_ratio)
    delivery = aspect_contract
    expected_delivery = {
        "status": profile["aspect_status"],
        "generation_size": profile["size"],
        "safe_crop": profile["safe_crop"],
        "width": profile["delivery_size"][0],
        "height": profile["delivery_size"][1],
        "format": profile["output_format"],
    }
    if not isinstance(delivery, dict) or any(
        delivery.get(field) != expected for field, expected in expected_delivery.items()
    ):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset delivery contract is invalid."
        )
    if len(provider_paths) + 1 > int(profile.get("maximum_input_images", 0)):
        raise OpenAIImageExecutionError(
            "INVALID_PRESET_CONFIGURATION", "Preset exceeds the provider image-input limit."
        )
    bundle_hash = _canonical_json_sha256(bundle)
    return PublishedPreset(
        slot_id=slot_id,
        preset_id=str(bundle["preset_id"]),
        prompt=prompt,
        provider_profile=profile,
        provider_image_paths=tuple(provider_paths),
        provider_image_roles=tuple(provider_roles),
        aspect_ratio=aspect_ratio,
        aspect_status=str(aspect_contract.get("status") or ""),
        delivery_width=int(delivery["width"]),
        delivery_height=int(delivery["height"]),
        bbox_qa=dict(bbox_qa),
        bundle_sha256=bundle_hash,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        provider_profile_sha256=_canonical_json_sha256(profile),
    )


def _mime_type(path: Path) -> str:
    try:
        with Image.open(path) as image:
            image_format = str(image.format or "").upper()
            image.verify()
    except (OSError, Image.DecompressionBombError) as exc:
        raise OpenAIImageExecutionError("INVALID_IMAGE", f"Invalid image: {path.name}") from exc
    known = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
    if image_format in known:
        return known[image_format]
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed in {"image/jpeg", "image/png", "image/webp"}:
        return str(guessed)
    raise OpenAIImageExecutionError("INVALID_IMAGE", f"Unsupported image: {path.name}")


def _multipart_body(
    *, fields: tuple[tuple[str, str], ...], image_paths: tuple[Path, ...]
) -> tuple[bytes, str]:
    """Build the documented repeated-image multipart request without leaking filenames."""
    boundary = f"ad-creator-{secrets.token_hex(24)}"
    boundary_bytes = boundary.encode("ascii")
    chunks: list[bytes] = []

    for name, value in fields:
        chunks.extend(
            (
                b"--" + boundary_bytes + b"\r\n",
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(
                    "ascii"
                ),
                value.encode("utf-8"),
                b"\r\n",
            )
        )

    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    for index, path in enumerate(image_paths, start=1):
        try:
            image_size = path.stat().st_size
        except OSError as exc:
            raise OpenAIImageExecutionError(
                "INVALID_IMAGE", "An image input could not be read."
            ) from exc
        if image_size >= MAX_INPUT_IMAGE_BYTES:
            raise OpenAIImageExecutionError(
                "IMAGE_TOO_LARGE", "Each OpenAI image input must be 50 MiB or smaller."
            )
        mime_type = _mime_type(path)
        filename = f"image-{index}{extensions[mime_type]}"
        chunks.extend(
            (
                b"--" + boundary_bytes + b"\r\n",
                (
                    'Content-Disposition: form-data; name="image[]"; '
                    f'filename="{filename}"\r\n'
                ).encode("ascii"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("ascii"),
                path.read_bytes(),
                b"\r\n",
            )
        )
    chunks.append(b"--" + boundary_bytes + b"--\r\n")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _safe_error(body: bytes) -> tuple[str, str]:
    try:
        value = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return "OPENAI_HTTP_ERROR", "OpenAI returned an unreadable error response."
    error = value.get("error") if isinstance(value, dict) else None
    if not isinstance(error, dict):
        return "OPENAI_HTTP_ERROR", "OpenAI returned an error response."
    raw_code = str(error.get("code") or "OPENAI_HTTP_ERROR")[:80]
    code = "".join(
        character
        for character in raw_code
        if character.isascii() and (character.isalnum() or character in "._-")
    ) or "OPENAI_HTTP_ERROR"
    messages = {
        "moderation_blocked": "OpenAI blocked the request during image safety review.",
        "rate_limit_exceeded": "OpenAI image generation is temporarily rate limited.",
        "invalid_api_key": "OpenAI rejected the configured API credential.",
        "billing_hard_limit_reached": "OpenAI billing is not available for this request.",
    }
    return code, messages.get(code, "OpenAI rejected the image generation request.")


def _post(
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout_seconds: float,
) -> OpenAIHTTPResponse:
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        context = ssl.create_default_context()
        with urllib.request.urlopen(request, timeout=timeout_seconds, context=context) as response:
            raw = response.read(MAX_RESPONSE_JSON_BYTES + 1)
            request_id = response.headers.get("x-request-id")
    except urllib.error.HTTPError as exc:
        code, message = _safe_error(exc.read())
        raise OpenAIImageExecutionError(
            code,
            message,
            request_id=exc.headers.get("x-request-id"),
            client_request_id=headers.get("X-Client-Request-Id"),
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OpenAIImageExecutionError(
            "OPENAI_REQUEST_FAILED",
            "OpenAI request failed before a response was saved.",
            client_request_id=headers.get("X-Client-Request-Id"),
        ) from exc
    if len(raw) > MAX_RESPONSE_JSON_BYTES:
        raise OpenAIImageExecutionError(
            "INVALID_OPENAI_RESPONSE", "OpenAI response exceeds the configured limit."
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenAIImageExecutionError("INVALID_OPENAI_RESPONSE", "OpenAI returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise OpenAIImageExecutionError("INVALID_OPENAI_RESPONSE", "OpenAI returned a non-object response.")
    return OpenAIHTTPResponse(payload=value, request_id=request_id)


def _usage_counts(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            result[key] = item
        elif isinstance(item, dict):
            nested = _usage_counts(item)
            if nested:
                result[key] = nested
    return result


def _delivery_image(raw: bytes, width: int, height: int) -> Image.Image:
    if len(raw) > MAX_RESPONSE_IMAGE_BYTES:
        raise OpenAIImageExecutionError("INVALID_OPENAI_RESPONSE", "OpenAI image exceeds 50 MiB.")
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            image = opened.convert("RGB")
    except (OSError, Image.DecompressionBombError) as exc:
        raise OpenAIImageExecutionError("INVALID_OPENAI_RESPONSE", "OpenAI returned an invalid image.") from exc

    return image.resize((width, height), Image.Resampling.LANCZOS)


def _run_id(value: str | None) -> str:
    candidate = (value or "").strip() or str(uuid.uuid4())
    if RUN_ID_PATTERN.fullmatch(candidate) is None:
        raise OpenAIImageExecutionError(
            "INVALID_RUN_ID", "run_id must be 1 to 128 safe ASCII characters."
        )
    return candidate


def _write_audit_artifacts(
    *, directory: str | Path, raw_image: bytes, metadata: dict[str, Any]
) -> dict[str, Any]:
    audit_dir = Path(directory).expanduser().resolve()
    stem = f"{metadata['run_id']}.{metadata['client_request_id']}"
    raw_name = f"{stem}.provider.png"
    manifest_name = f"{stem}.manifest.json"
    raw_path = audit_dir / raw_name
    manifest_path = audit_dir / manifest_name
    result = dict(metadata)
    result["audit"] = {
        "raw_provider_filename": raw_name,
        "manifest_filename": manifest_name,
    }
    manifest_bytes = json.dumps(
        result, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"

    try:
        with raw_path.open("xb") as file:
            file.write(raw_image)
        try:
            with manifest_path.open("xb") as file:
                file.write(manifest_bytes)
        except Exception:
            raw_path.unlink(missing_ok=True)
            raise
    except OSError as exc:
        raise OpenAIImageExecutionError(
            "AUDIT_STORAGE_UNAVAILABLE", "OpenAI audit artifacts could not be saved."
        ) from exc
    return result


def _prepare_audit_directory(directory: str | Path) -> Path:
    audit_dir = Path(directory).expanduser().resolve()
    probe = audit_dir / f".write-probe-{uuid.uuid4()}"
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        with probe.open("xb") as file:
            file.write(b"audit-ready\n")
        probe.unlink()
    except OSError as exc:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        raise OpenAIImageExecutionError(
            "AUDIT_STORAGE_UNAVAILABLE",
            "OpenAI audit storage is not writable; provider call was not started.",
        ) from exc
    return audit_dir


def _source_max_edge(profile: dict[str, Any]) -> int:
    preprocessing = profile["source_preprocessing"]
    default = int(preprocessing["default_max_long_edge"])
    allowed = tuple(int(value) for value in preprocessing["comparison_max_long_edges"])
    raw = os.environ.get("AD_CREATOR_OPENAI_SOURCE_MAX_EDGE", "").strip()
    if not raw:
        return default
    try:
        selected = int(raw)
    except ValueError as exc:
        raise OpenAIImageExecutionError(
            "INVALID_CONFIGURATION",
            "AD_CREATOR_OPENAI_SOURCE_MAX_EDGE must be 1536 or 3072.",
        ) from exc
    if selected not in allowed:
        raise OpenAIImageExecutionError(
            "INVALID_CONFIGURATION",
            "AD_CREATOR_OPENAI_SOURCE_MAX_EDGE must be 1536 or 3072.",
        )
    return selected


def _input_image_descriptor(role: str, path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as opened:
            dimensions = [opened.width, opened.height]
            image_format = str(opened.format or "").upper()
            opened.verify()
    except (OSError, Image.DecompressionBombError) as exc:
        raise OpenAIImageExecutionError("INVALID_IMAGE", "Invalid image input.") from exc
    return {
        "role": role,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "dimensions": dimensions,
        "format": image_format,
    }


@contextmanager
def _normalized_product_source(source: Path, profile: dict[str, Any]):
    max_edge = _source_max_edge(profile)
    preprocessing = profile["source_preprocessing"]
    temporary_path: Path | None = None
    try:
        try:
            with Image.open(source) as opened:
                original_format = str(opened.format or "").upper()
                normalized = ImageOps.exif_transpose(opened).convert("RGB")
                original_dimensions = [normalized.width, normalized.height]
                if max(normalized.size) > max_edge:
                    normalized.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                uploaded_dimensions = [normalized.width, normalized.height]
        except (OSError, Image.DecompressionBombError) as exc:
            raise OpenAIImageExecutionError("INVALID_IMAGE", "Invalid product source image.") from exc

        with tempfile.NamedTemporaryFile(
            prefix="ad_creator_openai_source_", suffix=".jpg", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        normalized.save(
            temporary_path,
            format="JPEG",
            quality=int(preprocessing["jpeg_quality"]),
            subsampling=0,
            optimize=True,
        )
        yield temporary_path, {
            "original_dimensions": original_dimensions,
            "uploaded_dimensions": uploaded_dimensions,
            "original_format": original_format,
            "uploaded_format": "JPEG",
            "max_long_edge": max_edge,
            "resized": uploaded_dimensions != original_dimensions,
            "upscaled": False,
            "metadata_stripped": True,
        }
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def run_openai_image(
    *,
    image_path: str | Path,
    preset_slot_id: str,
    aspect_ratio: str = "4:5",
    api_key: str | None = None,
    timeout_seconds: float = 1200.0,
    registry_path: str | Path = DEFAULT_PRESET_REGISTRY,
    transport: Transport | None = None,
    run_id: str | None = None,
    audit_dir: str | Path | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    source = Path(image_path).resolve()
    if not source.is_file():
        raise OpenAIImageExecutionError("INVALID_IMAGE", "Product source image does not exist.")
    _mime_type(source)
    preset = load_published_preset(
        preset_slot_id,
        aspect_ratio=aspect_ratio,
        registry_path=registry_path,
    )
    with _normalized_product_source(source, preset.provider_profile) as (
        normalized_source,
        source_preprocessing,
    ):
        return _run_openai_image_prepared(
            source=normalized_source,
            preset=preset,
            source_preprocessing=source_preprocessing,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            transport=transport,
            run_id=run_id,
            audit_dir=audit_dir,
        )


def _run_openai_image_prepared(
    *,
    source: Path,
    preset: PublishedPreset,
    source_preprocessing: dict[str, Any],
    api_key: str | None,
    timeout_seconds: float,
    transport: Transport | None,
    run_id: str | None,
    audit_dir: str | Path | None,
) -> tuple[Image.Image, dict[str, Any]]:
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise OpenAIImageExecutionError(
            "OPENAI_API_KEY_MISSING", "OPENAI_API_KEY is not configured for the ComfyUI worker."
        )
    if timeout_seconds <= 0:
        raise OpenAIImageExecutionError("INVALID_CONFIGURATION", "OpenAI timeout must be positive.")

    profile = preset.provider_profile
    image_paths = (source, *preset.provider_image_paths)
    roles = ("product_source", *preset.provider_image_roles)
    input_images = [
        _input_image_descriptor(role, path)
        for role, path in zip(roles, image_paths, strict=True)
    ]
    input_images[0]["preprocessing"] = dict(source_preprocessing)
    request_hash = _canonical_json_sha256(
        {
            "bundle_sha256": preset.bundle_sha256,
            "input_images": input_images,
            "preset_id": preset.preset_id,
            "preset_slot_id": preset.slot_id,
            "aspect_ratio": preset.aspect_ratio,
            "prompt_sha256": preset.prompt_sha256,
            "provider_profile_sha256": preset.provider_profile_sha256,
        }
    )
    resolved_run_id = _run_id(run_id)
    client_request_id = str(uuid.uuid4())
    prepared_audit_dir = (
        _prepare_audit_directory(audit_dir) if audit_dir is not None else None
    )
    body, content_type = _multipart_body(
        fields=(
            ("model", str(profile["model"])),
            ("prompt", preset.prompt),
            ("quality", str(profile["quality"])),
            ("size", str(profile["size"])),
            ("output_format", str(profile["output_format"])),
            ("moderation", str(profile["moderation"])),
            ("n", "1"),
        ),
        image_paths=image_paths,
    )
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type,
        "User-Agent": "ad-creator-comfyui/1.0",
        "X-Client-Request-Id": client_request_id,
    }
    started_at = time.monotonic()
    response = (transport or _post)(
        str(profile["endpoint"]), headers, body, float(timeout_seconds)
    )
    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    if isinstance(response, dict):
        response = OpenAIHTTPResponse(payload=response)
    if not isinstance(response, OpenAIHTTPResponse):
        raise OpenAIImageExecutionError(
            "INVALID_OPENAI_RESPONSE", "OpenAI transport returned an invalid response."
        )
    data = response.payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise OpenAIImageExecutionError("INVALID_OPENAI_RESPONSE", "OpenAI returned no image.")
    encoded = data[0].get("b64_json")
    if not isinstance(encoded, str) or not encoded:
        raise OpenAIImageExecutionError("INVALID_OPENAI_RESPONSE", "OpenAI returned no base64 image.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OpenAIImageExecutionError(
            "INVALID_OPENAI_RESPONSE", "OpenAI returned invalid base64 image data."
        ) from exc
    if len(raw) >= MAX_RESPONSE_IMAGE_BYTES:
        raise OpenAIImageExecutionError(
            "INVALID_OPENAI_RESPONSE", "OpenAI image must be smaller than 50 MiB."
        )
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            raw_dimensions = [opened.width, opened.height]
            raw_format = str(opened.format or "").upper()
            opened.verify()
    except (OSError, Image.DecompressionBombError) as exc:
        raise OpenAIImageExecutionError(
            "INVALID_OPENAI_RESPONSE", "OpenAI returned an invalid image."
        ) from exc
    expected_dimensions = [int(value) for value in str(profile["size"]).split("x", 1)]
    if raw_format != "PNG" or raw_dimensions != expected_dimensions:
        raise OpenAIImageExecutionError(
            "INVALID_OPENAI_RESPONSE",
            "OpenAI returned an unexpected format or canvas size; no crop was applied.",
        )
    delivery = _delivery_image(raw, preset.delivery_width, preset.delivery_height)
    metadata = {
        "provider": profile["provider"],
        "model": profile["model"],
        "quality": profile["quality"],
        "preset_slot_id": preset.slot_id,
        "preset_id": preset.preset_id,
        "aspect_ratio": preset.aspect_ratio,
        "aspect_status": preset.aspect_status,
        "run_id": resolved_run_id,
        "request_hash": request_hash,
        "request_id": response.request_id,
        "client_request_id": client_request_id,
        "image_roles": list(roles),
        "input_images": input_images,
        "source_preprocessing": dict(source_preprocessing),
        "bbox_qa_contract": dict(preset.bbox_qa),
        "bundle_sha256": preset.bundle_sha256,
        "prompt_sha256": preset.prompt_sha256,
        "provider_profile_sha256": preset.provider_profile_sha256,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "delivery_pixel_sha256": hashlib.sha256(delivery.tobytes()).hexdigest(),
        "raw_dimensions": raw_dimensions,
        "delivery_dimensions": [delivery.width, delivery.height],
        "elapsed_ms": elapsed_ms,
        "usage": _usage_counts(response.payload.get("usage")),
        "automatic_retries": 0,
        "common_qa_status": "pending",
    }
    if prepared_audit_dir is not None:
        metadata = _write_audit_artifacts(
            directory=prepared_audit_dir,
            raw_image=raw,
            metadata=metadata,
        )
    return delivery, metadata
