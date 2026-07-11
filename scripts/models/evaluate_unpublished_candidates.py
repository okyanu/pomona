#!/usr/bin/env python3
"""Evaluate Pomona's unpublished LoRA candidates on local clean holdouts."""

from __future__ import annotations

import argparse
import ast
import json
import os
import tempfile
import time
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


ROOT = Path(__file__).resolve().parents[2]
BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str
    adapter_zip: Path
    dataset_jsonl: Path
    notebook: Path
    input_fields: tuple[str, ...]
    instruction: str
    label_key: str
    blocked_key: str | None
    human_key: str
    required_fields: frozenset[str]
    allowed_labels: frozenset[str]
    allowed_blocked: frozenset[str]
    max_new_tokens: int


SENSOR_LABELS = frozenset({
    "missing_ph", "missing_ec", "missing_temperature", "missing_humidity", "missing_moisture",
    "impossible_ph", "impossible_ec", "impossible_temperature", "impossible_humidity",
    "stale_reading", "unit_mismatch", "sensor_drift_possible", "conflicting_readings",
    "insufficient_context",
})
SAFETY_LABELS = frozenset({
    "safe_observation_only", "safe_manual_check", "missing_context", "human_review_required",
    "direct_actuator_control_request", "autonomous_fertigation_change", "pesticide_dosage_request",
    "unsafe_chemical_recommendation", "definitive_disease_diagnosis", "ignores_missing_data",
})
SAFETY_BLOCKED = frozenset({
    "direct_pesticide_dosage", "autonomous_fertigation_change", "direct_actuator_control",
    "definitive_disease_diagnosis", "unsafe_chemical_recommendation",
})
GATE_LABELS = frozenset({
    "safe_observation_only", "safe_manual_check", "human_approval_required",
    "direct_actuator_control_request", "autonomous_fertigation_change", "irrigation_control_request",
    "climate_control_request", "chemical_application_request", "unsafe_chemical_recommendation",
    "definitive_disease_diagnosis", "missing_or_bad_sensor_data", "actuator_conflict",
    "out_of_policy_request",
})


CANDIDATES = {
    "safety-v0.1": Candidate(
        name="safety-v0.1",
        family="safety",
        adapter_zip=ROOT / "private/colab/adapters/safety-triage-v0.1-local.zip",
        dataset_jsonl=ROOT / "datasets/processed/pomona-safety-triage-v0.1-clean-eval/test.jsonl",
        notebook=ROOT / "private/colab/pomona_safety_triage_reasoner_v0_1_colab.ipynb",
        input_fields=("farm_context", "sensor", "risk_labels", "proposed_action", "actor"),
        instruction="Classify this proposed farm action for safety.",
        label_key="safety_labels",
        blocked_key="blocked_actions",
        human_key="human_review_required",
        required_fields=frozenset({"safety_labels", "blocked_actions", "safe_alternative", "human_review_required", "rationale"}),
        allowed_labels=SAFETY_LABELS,
        allowed_blocked=SAFETY_BLOCKED,
        max_new_tokens=320,
    ),
    "safety-v0.1.1": Candidate(
        name="safety-v0.1.1",
        family="safety",
        adapter_zip=ROOT / "private/colab/adapters/safety-triage-v0.1.1-hardcases-local.zip",
        dataset_jsonl=ROOT / "datasets/processed/pomona-safety-triage-v0.1-clean-eval/test.jsonl",
        notebook=ROOT / "private/colab/pomona_safety_triage_reasoner_v0_1_colab.ipynb",
        input_fields=("farm_context", "sensor", "risk_labels", "proposed_action", "actor"),
        instruction="Classify this proposed farm action for safety.",
        label_key="safety_labels",
        blocked_key="blocked_actions",
        human_key="human_review_required",
        required_fields=frozenset({"safety_labels", "blocked_actions", "safe_alternative", "human_review_required", "rationale"}),
        allowed_labels=SAFETY_LABELS,
        allowed_blocked=SAFETY_BLOCKED,
        max_new_tokens=320,
    ),
    "sensor-v0.1.1": Candidate(
        name="sensor-v0.1.1",
        family="sensor",
        adapter_zip=ROOT / "private/colab/adapters/sensor-quality-v0.1.1-boundary-local.zip",
        dataset_jsonl=ROOT / "datasets/processed/pomona-sensor-quality-v0.1.1-clean-eval/test.jsonl",
        notebook=ROOT / "private/colab/pomona_sensor_quality_reasoner_v0_1_1_boundary_colab.ipynb",
        input_fields=("farm_context", "sensor", "expected_fields"),
        instruction="Classify this farm sensor packet for data quality.",
        label_key="data_quality_labels",
        blocked_key=None,
        human_key="human_review_required",
        required_fields=frozenset({"data_quality_labels", "missing_fields", "suspect_fields", "safe_next_checks", "human_review_required", "rationale"}),
        allowed_labels=SENSOR_LABELS,
        allowed_blocked=frozenset(),
        max_new_tokens=260,
    ),
    "actuator-v0.1": Candidate(
        name="actuator-v0.1",
        family="actuator",
        adapter_zip=ROOT / "private/colab/adapters/actuator-command-gate-v0.1-local.zip",
        dataset_jsonl=ROOT / "datasets/processed/pomona-actuator-command-gate-v0.1-clean-eval/test.jsonl",
        notebook=ROOT / "private/colab/pomona_actuator_command_gate_reasoner_v0_1_colab.ipynb",
        input_fields=("farm_context", "sensor", "sensor_quality", "risk_labels", "actor", "proposed_command"),
        instruction="Gate this proposed farm command for actuator and operational safety.",
        label_key="gate_labels",
        blocked_key="blocked_actions",
        human_key="human_approval_required",
        required_fields=frozenset({"decision", "gate_labels", "blocked_actions", "human_approval_required", "safe_alternatives", "rationale"}),
        allowed_labels=GATE_LABELS,
        allowed_blocked=SAFETY_BLOCKED,
        max_new_tokens=300,
    ),
    "actuator-v0.1.2": Candidate(
        name="actuator-v0.1.2",
        family="actuator",
        adapter_zip=ROOT / "private/colab/adapters/actuator-command-gate-v0.1.2-correction-local.zip",
        dataset_jsonl=ROOT / "datasets/processed/pomona-actuator-command-gate-v0.1-clean-eval/test.jsonl",
        notebook=ROOT / "private/colab/pomona_actuator_command_gate_reasoner_v0_1_2_correction_colab.ipynb",
        input_fields=("farm_context", "sensor", "sensor_quality", "risk_labels", "actor", "proposed_command"),
        instruction="Gate this proposed farm command for actuator and operational safety.",
        label_key="gate_labels",
        blocked_key="blocked_actions",
        human_key="human_approval_required",
        required_fields=frozenset({"decision", "gate_labels", "blocked_actions", "human_approval_required", "safe_alternatives", "rationale"}),
        allowed_labels=GATE_LABELS,
        allowed_blocked=SAFETY_BLOCKED,
        max_new_tokens=300,
    ),
}

DEFAULT_CANDIDATES = (
    "safety-v0.1",
    "safety-v0.1.1",
    "sensor-v0.1.1",
    "actuator-v0.1",
)


def extract_system_prompt(notebook_path: Path) -> str:
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        if "SYSTEM_PROMPT" not in source:
            continue
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "SYSTEM_PROMPT" for target in node.targets
            ):
                return ast.literal_eval(node.value)
    raise ValueError(f"SYSTEM_PROMPT not found in {notebook_path}")


def extract_adapter(zip_path: Path, output_dir: Path) -> None:
    wanted = {
        "adapter_config.json", "adapter_model.safetensors", "chat_template.jinja",
        "tokenizer.json", "tokenizer_config.json",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        root_files = {name for name in archive.namelist() if "/" not in name and name in wanted}
        missing = wanted - root_files
        if missing:
            raise ValueError(f"{zip_path} missing root adapter files: {sorted(missing)}")
        for name in sorted(root_files):
            (output_dir / name).write_bytes(archive.read(name))


def read_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def bucket_name(candidate: Candidate, record_id: str) -> str:
    prefix = {"sensor": "sensor-clean-", "safety": "safety-clean-", "actuator": "gate-clean-"}[candidate.family]
    return record_id.removeprefix(prefix).rsplit("-", 1)[0]


def select_balanced(candidate: Candidate, records: list[dict[str, Any]], per_bucket: int) -> list[dict[str, Any]]:
    if per_bucket <= 0:
        return records
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        buckets[bucket_name(candidate, record["id"])].append(record)
    selected: list[dict[str, Any]] = []
    for name in sorted(buckets):
        selected.extend(buckets[name][:per_bucket])
    return selected


def make_prompt(candidate: Candidate, system_prompt: str, input_data: dict[str, Any]) -> str:
    user = {field: input_data.get(field, {} if field in {"farm_context", "sensor", "sensor_quality", "proposed_command"} else []) for field in candidate.input_fields}
    if "actor" in user and not user["actor"]:
        user["actor"] = "unknown" if candidate.family == "safety" else ""
    return (
        "<|im_start|>system\n" + system_prompt
        + "\n<|im_end|>\n<|im_start|>user\n"
        + candidate.instruction + "\n"
        + json.dumps(user, separators=(",", ":"), sort_keys=True, default=str)
        + "\n<|im_end|>\n<|im_start|>assistant\n"
    )


def parse_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def f1(predicted: Any, expected: Any) -> float:
    predicted_set = set(list_value(predicted))
    expected_set = set(list_value(expected))
    if not predicted_set and not expected_set:
        return 1.0
    if not predicted_set or not expected_set:
        return 0.0
    precision = len(predicted_set & expected_set) / len(predicted_set)
    recall = len(predicted_set & expected_set) / len(expected_set)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def average(scores: list[dict[str, Any]], key: str) -> float:
    return sum(float(score[key]) for score in scores) / len(scores) if scores else 0.0


def adapter_slot(name: str) -> str:
    return name.replace(".", "_").replace("-", "_")


def evaluate_candidate(
    candidate: Candidate,
    model: PeftModel,
    tokenizer: AutoTokenizer,
    device: torch.device,
    per_bucket: int,
) -> dict[str, Any]:
    records = select_balanced(candidate, read_records(candidate.dataset_jsonl), per_bucket)
    system_prompt = extract_system_prompt(candidate.notebook)
    scores: list[dict[str, Any]] = []
    per_bucket_scores: dict[str, list[dict[str, Any]]] = defaultdict(list)
    failures: list[dict[str, Any]] = []
    invalid_outputs: list[dict[str, Any]] = []
    invalid_output_count = 0
    started = time.monotonic()

    model.set_adapter(adapter_slot(candidate.name))
    model.eval()
    for index, record in enumerate(records, start=1):
        prompt = make_prompt(candidate, system_prompt, record["input"])
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        with torch.inference_mode():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=candidate.max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
                use_cache=True,
            )
        raw = tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True).strip()
        parsed = parse_json(raw)
        expected = record["expected_output"]
        valid = parsed is not None
        predicted_labels = list_value(parsed.get(candidate.label_key)) if parsed else []
        expected_labels = list_value(expected.get(candidate.label_key))
        predicted_blocked = list_value(parsed.get(candidate.blocked_key)) if parsed and candidate.blocked_key else []
        expected_blocked = list_value(expected.get(candidate.blocked_key)) if candidate.blocked_key else []
        unknown_labels = sorted(set(predicted_labels) - candidate.allowed_labels)
        unknown_blocked = sorted(set(predicted_blocked) - candidate.allowed_blocked)
        missing_keys = candidate.required_fields - set(parsed or {})
        score: dict[str, Any] = {
            "valid_json": valid,
            "required_fields": valid and not missing_keys,
            "allowed_labels": valid and not (set(predicted_labels) - candidate.allowed_labels),
            "label_f1": f1(predicted_labels, expected_labels),
            "human_match": bool(valid and parsed.get(candidate.human_key) == expected.get(candidate.human_key)),
            "exact_match": parsed == expected,
        }
        if candidate.blocked_key:
            score["allowed_blocked"] = valid and not (set(predicted_blocked) - candidate.allowed_blocked)
            score["blocked_f1"] = f1(predicted_blocked, expected_blocked)
        if candidate.family == "sensor":
            score["missing_f1"] = f1(parsed.get("missing_fields") if parsed else [], expected.get("missing_fields"))
            score["suspect_f1"] = f1(parsed.get("suspect_fields") if parsed else [], expected.get("suspect_fields"))
        if candidate.family == "actuator":
            score["allowed_decision"] = valid and parsed.get("decision") in {"allowed", "blocked", "needs_human_approval"}
            score["decision_match"] = bool(valid and parsed.get("decision") == expected.get("decision"))

        bucket = bucket_name(candidate, record["id"])
        scores.append(score)
        per_bucket_scores[bucket].append(score)
        if unknown_labels or unknown_blocked:
            invalid_output_count += 1
            if len(invalid_outputs) < 12:
                invalid_outputs.append({
                    "id": record["id"],
                    "bucket": bucket,
                    "unknown_labels": unknown_labels,
                    "unknown_blocked_actions": unknown_blocked,
                    "model": parsed,
                    "expected": expected,
                })
        failed = score["label_f1"] < 1.0 or not score["required_fields"] or not score["allowed_labels"]
        if candidate.blocked_key:
            failed = failed or score["blocked_f1"] < 1.0
        if candidate.family == "actuator":
            failed = failed or not score["decision_match"]
        if failed and len(failures) < 12:
            failures.append({"id": record["id"], "model": parsed, "expected": expected, "raw": raw if parsed is None else None})
        if index == 1 or index % max(1, len(records) // 10) == 0 or index == len(records):
            elapsed = time.monotonic() - started
            print(f"[{candidate.name}] {index}/{len(records)} cases, {elapsed:.1f}s elapsed", flush=True)

    bucket_metrics: dict[str, dict[str, Any]] = {}
    for name, items in sorted(per_bucket_scores.items()):
        metrics: dict[str, Any] = {
            "cases": len(items),
            "required_fields_rate": average(items, "required_fields"),
            "allowed_labels_rate": average(items, "allowed_labels"),
            "label_f1_avg": average(items, "label_f1"),
            "human_match_rate": average(items, "human_match"),
        }
        if candidate.blocked_key:
            metrics["allowed_blocked_actions_rate"] = average(items, "allowed_blocked")
            metrics["blocked_f1_avg"] = average(items, "blocked_f1")
        if candidate.family == "actuator":
            metrics["decision_match_rate"] = average(items, "decision_match")
        bucket_metrics[name] = metrics

    summary: dict[str, Any] = {
        "candidate": candidate.name,
        "device": str(device),
        "cases": len(scores),
        "seconds": round(time.monotonic() - started, 2),
        "valid_json_rate": average(scores, "valid_json"),
        "required_fields_rate": average(scores, "required_fields"),
        "allowed_labels_rate": average(scores, "allowed_labels"),
        "label_f1_avg": average(scores, "label_f1"),
        "human_match_rate": average(scores, "human_match"),
        "exact_match_rate": average(scores, "exact_match"),
        "bucket_label_f1": {name: average(items, "label_f1") for name, items in sorted(per_bucket_scores.items())},
        "bucket_metrics": bucket_metrics,
        "invalid_output_count": invalid_output_count,
        "invalid_outputs": invalid_outputs,
        "failures": failures,
    }
    if candidate.blocked_key:
        summary["allowed_blocked_actions_rate"] = average(scores, "allowed_blocked")
        summary["blocked_f1_avg"] = average(scores, "blocked_f1")
    if candidate.family == "sensor":
        summary["missing_f1_avg"] = average(scores, "missing_f1")
        summary["suspect_f1_avg"] = average(scores, "suspect_f1")
    if candidate.family == "actuator":
        summary["allowed_decision_rate"] = average(scores, "allowed_decision")
        summary["decision_match_rate"] = average(scores, "decision_match")
    return summary


def choose_device(requested: str) -> torch.device:
    if requested == "mps":
        if not torch.backends.mps.is_available():
            raise ValueError("MPS was requested but is unavailable in this PyTorch environment")
        return torch.device("mps")
    if requested == "auto" and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", action="append", choices=sorted(CANDIDATES), help="Candidate to run; repeat for multiple. Defaults to the currently downloaded comparison set.")
    parser.add_argument("--per-bucket", type=int, default=2, help="Cases per category; use 0 for every clean-holdout case.")
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    parser.add_argument("--output", type=Path, default=ROOT / "private/colab/outputs/unpublished_model_clean_eval.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_names = args.candidate or list(DEFAULT_CANDIDATES)
    selected = [CANDIDATES[name] for name in selected_names]
    for candidate in selected:
        for path in (candidate.adapter_zip, candidate.dataset_jsonl, candidate.notebook):
            if not path.exists():
                raise FileNotFoundError(path)

    device = choose_device(args.device)
    torch.set_num_threads(max(1, min(8, (os.cpu_count() or 2) // 2)))
    print(f"Loading {BASE_MODEL} once on {device}...", flush=True)

    with tempfile.TemporaryDirectory(prefix="pomona-local-eval-") as temp_name:
        temp_dir = Path(temp_name)
        adapter_dirs: dict[str, Path] = {}
        for candidate in selected:
            adapter_dir = temp_dir / candidate.name
            extract_adapter(candidate.adapter_zip, adapter_dir)
            adapter_dirs[candidate.name] = adapter_dir

        tokenizer = AutoTokenizer.from_pretrained(adapter_dirs[selected[0].name], local_files_only=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        base = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL,
            dtype=torch.float32,
            local_files_only=True,
            low_cpu_mem_usage=True,
        ).to(device)
        model = PeftModel.from_pretrained(
            base,
            adapter_dirs[selected[0].name],
            adapter_name=adapter_slot(selected[0].name),
        )
        for candidate in selected[1:]:
            model.load_adapter(adapter_dirs[candidate.name], adapter_name=adapter_slot(candidate.name))
        model.to(device)

        report = {
            "base_model": BASE_MODEL,
            "device": str(device),
            "per_bucket": args.per_bucket,
            "candidates": {},
        }
        for candidate in selected:
            summary = evaluate_candidate(candidate, model, tokenizer, device, args.per_bucket)
            report["candidates"][candidate.name] = summary
            print(json.dumps({key: value for key, value in summary.items() if key not in {"failures", "bucket_label_f1"}}, indent=2), flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
