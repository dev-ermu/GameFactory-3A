"""验证game-cg-director JSON file（不需要调用LLM）"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = SKILL_DIR / "schemas" / "output.schema.json"
MACHINE_BLOCK = re.compile(
    r"```json machine-checks\s*(\{.*?\})\s*```", re.DOTALL
)
PROVIDER_TERMS = (
    "game-cg-director",
    "minimax",
    "bytedance",
    "defaults_applied",
    "元数据",
    "字节跳动",
    "稀宇科技",
)
BASE_SECTIONS = (
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
)
REF_SECTIONS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)
SHOT_RE = re.compile(
    r"\[Shot (?P<number>[1-9]\d*)\](?: At (?P<time>\d{2}:\d{2}\.\d{3}),)?"
)
REFERENCE_RE = re.compile(r"<(?P<kind>Subject|Picture|Video|Audio) (?P<number>[1-9]\d*)>")
SPEAKER_RE = re.compile(r"\(S(?P<first>[1-9]\d*)(?P<rest>(?:,S[1-9]\d*)*)\)")
DIALOGUE_RE = re.compile(r"<d>\[(?P<language>[^\[\]\r\n]+)\] (?P<text>.*?)</d>", re.DOTALL)
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
UNTAGGED_SPEECH_RE = re.compile(
    r"\b(?:say(?:s|ing)?|shout(?:s|ing)?|yell(?:s|ing)?|whisper(?:s|ing)?|"
    r"repl(?:y|ies|ying)|ask(?:s|ing)?|call(?:s|ing)? out|chant(?:s|ing)?|sing(?:s|ing)?)\b"
    r"[^.!?\n]{0,140}[\"“][^\"”\n]+[\"”]",
    re.IGNORECASE,
)
DEFINITION_RE = re.compile(
    r"^(<(?P<kind>Subject|Picture|Video|Audio) [1-9]\d*>)\s+.+$", re.MULTILINE
)
RETENTION_RE = re.compile(
    r"^(<(?P<kind>Subject|Picture|Video|Audio) [1-9]\d*>)(?:\s+\([^)]*\))?:\s+"
    r"(?P<marker>[a-z_]+)\s+-\s+.+$",
    re.MULTILINE,
)
SUMMARY_TYPES = {
    "keyframe completion",
    "reference generation",
    "video editing",
    "video continuation",
    "audio reuse",
    "audio reference",
}
VISUAL_RETENTION = {
    "fully_preserved",
    "partially_preserved",
    "attribute_transfer",
    "weak_reference",
}
AUDIO_RETENTION = {"fully_copy", "partially_copy", "reference", "weak_reference"}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def load_model_checks(model: str) -> dict[str, Any]:
    profile_path = SKILL_DIR / "models" / f"{model}.md"
    if not profile_path.is_file():
        raise ValueError(f"model profile not found: models/{model}.md")
    match = MACHINE_BLOCK.search(profile_path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"model profile has no machine-checks block: {profile_path.name}")
    try:
        checks = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid machine-checks JSON in {profile_path.name}: {exc.msg}"
        ) from exc
    if checks.get("model") != model:
        raise ValueError(
            f"model profile mismatch: expected {model!r}, got {checks.get('model')!r}"
        )
    return checks


def resolve_pointer(root: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("#/"):
        raise ValueError(f"unsupported schema reference: {pointer}")
    value: Any = root
    for raw_part in pointer[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        value = value[part]
    return value


def matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return True


def schema_errors(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any],
    location: str = "$",
) -> list[str]:
    """评估该SKILL所使用的JSON Schema关键字。"""

    if "$ref" in schema:
        return schema_errors(value, resolve_pointer(root, schema["$ref"]), root, location)

    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not matches_type(value, expected_type):
        return [f"schema {location}: expected {expected_type}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"schema {location}: {value!r} is not in {schema['enum']!r}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"schema {location}: expected constant {schema['const']!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"schema {location}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value:
                errors.extend(
                    schema_errors(value[key], child_schema, root, f"{location}.{key}")
                )
        if schema.get("additionalProperties") is False:
            for key in sorted(set(value) - set(properties)):
                errors.append(f"schema {location}: unexpected property {key!r}")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"schema {location}: expected at least {min_items} item(s)")
        if schema.get("uniqueItems"):
            encoded = [
                json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value
            ]
            if len(encoded) != len(set(encoded)):
                errors.append(f"schema {location}: array items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(
                    schema_errors(item, item_schema, root, f"{location}[{index}]")
                )

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            errors.append(f"schema {location}: string is shorter than {min_length}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"schema {location}: string does not match required pattern")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"schema {location}: value is below minimum {minimum}")
        if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
            errors.append(
                f"schema {location}: value must be greater than {exclusive_minimum}"
            )

    for child_schema in schema.get("allOf", []):
        errors.extend(schema_errors(value, child_schema, root, location))
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        if not any(not schema_errors(value, candidate, root, location) for candidate in any_of):
            errors.append(f"schema {location}: no anyOf branch matched")
    not_schema = schema.get("not")
    if isinstance(not_schema, dict) and not schema_errors(value, not_schema, root, location):
        errors.append(f"schema {location}: matched a forbidden shape")
    if_schema = schema.get("if")
    then_schema = schema.get("then")
    if isinstance(if_schema, dict) and isinstance(then_schema, dict):
        if not schema_errors(value, if_schema, root, location):
            errors.extend(schema_errors(value, then_schema, root, location))
    return errors


def prompt_policy_errors(data: dict[str, Any]) -> list[str]:
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return []
    errors: list[str] = []
    lowered = prompt.casefold()
    if re.search(r"\bmeta\b", lowered):
        errors.append("prompt contains metadata term: meta")
    for term in PROVIDER_TERMS:
        if term.casefold() in lowered:
            errors.append(f"prompt contains provider or metadata term: {term}")
    return errors


def split_h3_sections(prompt: str, names: tuple[str, ...]) -> tuple[dict[str, str], list[str]]:
    header_re = re.compile(r"(?m)^(" + "|".join(map(re.escape, names)) + r"):\s*")
    matches = list(header_re.finditer(prompt))
    if [match.group(1) for match in matches] != list(names):
        return {}, [f"H3 prompt must contain exactly these sections in order: {', '.join(names)}"]
    if not matches or matches[0].start() != 0:
        return {}, [f"H3 section body must begin with {names[0]}:"]
    sections: dict[str, str] = {}
    errors: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt)
        value = prompt[match.end() : end].strip()
        if not value:
            errors.append(f"H3 section {match.group(1)} must not be empty")
        sections[match.group(1)] = value
    return sections, errors


def seconds_from_timecode(value: str) -> float:
    minutes, seconds = value.split(":")
    if float(seconds) >= 60:
        raise ValueError("timecode seconds must be below 60")
    return int(minutes) * 60 + float(seconds)


def timeline_errors(text: str, duration: float) -> list[str]:
    matches = list(SHOT_RE.finditer(text))
    if not matches:
        return ["H3 timeline must contain [Shot 1]"]
    if text.count("[Shot ") != len(matches):
        return ["H3 timeline contains a malformed shot header"]
    numbers = [int(match.group("number")) for match in matches]
    errors: list[str] = []
    if numbers != list(range(1, len(numbers) + 1)):
        errors.append("H3 shot numbers must start at 1 and be sequential")
    if matches[0].group("time") is not None:
        errors.append("[Shot 1] must not have a timecode")
    previous = -1.0
    for match in matches[1:]:
        value = match.group("time")
        if value is None:
            errors.append(f"[Shot {match.group('number')}] requires 'At MM:SS.mmm,'")
            continue
        try:
            current = seconds_from_timecode(value)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if current <= previous:
            errors.append("H3 shot timecodes must be strictly increasing")
        if current >= duration:
            errors.append(f"H3 shot timecode {value} must be below duration_sec {duration:g}")
        previous = current
    return errors


def dialogue_errors(text: str) -> list[str]:
    errors: list[str] = []
    if text.count("<d>") != text.count("</d>"):
        errors.append("H3 dialogue tags must be balanced")
    dialogues = list(DIALOGUE_RE.finditer(text))
    if len(dialogues) != text.count("<d>"):
        errors.append("H3 dialogue must use <d>[Language] exact text</d>")
    for dialogue in dialogues:
        if not dialogue.group("text").strip():
            errors.append("H3 dialogue text must not be empty")
        if REFERENCE_RE.search(dialogue.group(0)):
            errors.append("H3 reference labels must remain outside dialogue tags")
        prefix = text[max(0, dialogue.start() - 240) : dialogue.start()]
        if not SPEAKER_RE.search(prefix):
            errors.append("every H3 dialogue block requires a nearby stable speaker ID such as (S1)")
    without_dialogue = DIALOGUE_RE.sub("", text)
    if re.search(r"<scenetrans>|<cutoff>", without_dialogue):
        errors.append("<scenetrans> and <cutoff> must appear inside dialogue tags")
    if UNTAGGED_SPEECH_RE.search(without_dialogue):
        errors.append("spoken words must use <d>[Language] exact text</d>")
    speakers: list[int] = []
    for match in SPEAKER_RE.finditer(text):
        speakers.append(int(match.group("first")))
        speakers.extend(int(item[1:]) for item in match.group("rest").split(",") if item)
    if speakers and sorted(set(speakers)) != list(range(1, max(speakers) + 1)):
        errors.append("H3 speaker IDs must be contiguous from S1")
    return errors


def english_section_errors(sections: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for name, value in sections.items():
        check = DIALOGUE_RE.sub("", value)
        check = re.sub(r'"[^"\r\n]*"|“[^”\r\n]*”', "", check)
        if CJK_RE.search(check):
            errors.append(
                f"H3 section {name} must be English; preserve Chinese only in dialogue, lyrics, or quoted visible text"
            )
    return errors


def reference_numbering_errors(text: str) -> list[str]:
    by_kind: dict[str, set[int]] = {}
    for match in REFERENCE_RE.finditer(text):
        by_kind.setdefault(match.group("kind"), set()).add(int(match.group("number")))
    errors: list[str] = []
    for kind, numbers in by_kind.items():
        if sorted(numbers) != list(range(1, max(numbers) + 1)):
            errors.append(f"H3 {kind} labels must be contiguous from 1")
    return errors


def base_h3_errors(data: dict[str, Any], prompt: str) -> list[str]:
    mode = data.get("mode")
    duration = float(data["duration_sec"])
    body = prompt
    errors: list[str] = []
    if mode == "first_frame_to_video":
        instruction = (
            "For the target video, at 0.00 seconds into the target video, "
            "<Picture 1> (from [Shot 1]) is fully referenced."
        )
        prefix = instruction + "\n\n"
        if not prompt.startswith(prefix):
            errors.append("I2VA prompt must begin with the exact H3 first-frame instruction and one blank line")
        else:
            body = prompt[len(prefix) :]
    elif mode == "first_last_frame_to_video":
        alignment = re.match(
            r"^How the reference pictures align with the target video — Picture 1 "
            r"\(from Shot 1\) aligns with the 0\.00-second mark of the target video; "
            r"Picture 2 \(from Shot (?P<shot>[1-9]\d*)\) aligns with the "
            r"(?P<duration>\d+\.\d{2})-second mark of the target video\.\n\n",
            prompt,
        )
        if not alignment:
            errors.append("FL2VA prompt must begin with the exact H3 frame-alignment instruction and one blank line")
        else:
            body = prompt[alignment.end() :]
    sections, section_errors = split_h3_sections(body, BASE_SECTIONS)
    errors.extend(section_errors)
    if not sections:
        return errors
    timeline = sections["integrated_multimodal_description"]
    if not timeline.startswith("[Shot 1]"):
        errors.append("H3 base timeline must begin with [Shot 1]")
    errors.extend(timeline_errors(timeline, duration))
    errors.extend(dialogue_errors(timeline))
    errors.extend(english_section_errors(sections))
    errors.extend(reference_numbering_errors(prompt))
    labels = {match.group(0) for match in REFERENCE_RE.finditer(timeline)}
    if mode == "text_to_video" and labels:
        errors.append("text_to_video timeline must not contain H3 reference labels")
    if mode == "first_frame_to_video" and labels not in (set(), {"<Picture 1>"}):
        errors.append("first_frame_to_video timeline may only repeat <Picture 1>")
    if mode == "first_last_frame_to_video":
        expected = {"<Picture 1>", "<Picture 2>"}
        if labels != expected:
            errors.append(f"first_last_frame_to_video requires exactly these H3 picture labels: {sorted(expected)}")
    if mode == "first_last_frame_to_video" and 'alignment' in locals() and alignment:
        shot_count = len(list(SHOT_RE.finditer(timeline)))
        if int(alignment.group("shot")) != shot_count:
            errors.append("FL2VA alignment instruction must name the actual final shot")
        if alignment.group("duration") != f"{duration:.2f}":
            errors.append("FL2VA alignment duration must equal duration_sec to two decimals")
    if "<d>" in sections["overall_soundscape"] or "<d>" in sections["non_diegetic_music"]:
        errors.append("H3 dialogue belongs only in integrated_multimodal_description")
    return errors


def ref_h3_errors(data: dict[str, Any], prompt: str) -> list[str]:
    duration = float(data["duration_sec"])
    sections, errors = split_h3_sections(prompt, REF_SECTIONS)
    if not sections:
        return errors
    errors.extend(timeline_errors(sections["detailed_description"], duration))
    errors.extend(dialogue_errors(sections["detailed_description"]))
    errors.extend(english_section_errors(sections))
    errors.extend(reference_numbering_errors(prompt))

    summary_match = re.match(r"^\[([^\[\]\r\n]+)\]\s+\S", sections["summary"])
    if not summary_match:
        errors.append("Ref2VA summary must begin with a bracketed H3 task-type prefix")
    else:
        task_types = summary_match.group(1).split(" + ")
        if len(task_types) != len(set(task_types)) or not set(task_types) <= SUMMARY_TYPES:
            errors.append("Ref2VA summary contains duplicate or unsupported task types")

    definitions = list(DEFINITION_RE.finditer(sections["subject_definitions"]))
    definition_lines = [line for line in sections["subject_definitions"].splitlines() if line.strip()]
    if not definitions or len(definitions) != len(definition_lines):
        errors.append("every Ref2VA subject_definitions line must begin with one reference label")
    primary = {match.group(1) for match in definitions}
    known = {match.group(0) for match in REFERENCE_RE.finditer(sections["subject_definitions"])}
    other = "\n".join(value for key, value in sections.items() if key != "subject_definitions")
    undefined = {match.group(0) for match in REFERENCE_RE.finditer(other)} - known
    if undefined:
        errors.append(f"Ref2VA uses undefined reference labels: {sorted(undefined)}")

    retention = list(RETENTION_RE.finditer(sections["retention_analysis"]))
    retention_lines = [line for line in sections["retention_analysis"].splitlines() if line.strip()]
    if len(retention) != len(retention_lines):
        errors.append("every Ref2VA retention_analysis line must use a labeled retention marker")
    retained = {match.group(1) for match in retention}
    if retained != primary or len(retention) != len(retained):
        errors.append("Ref2VA retention_analysis requires exactly one entry per primary definition")
    for match in retention:
        allowed = AUDIO_RETENTION if match.group("kind") == "Audio" else VISUAL_RETENTION
        if match.group("marker") not in allowed:
            errors.append(
                f"invalid Ref2VA marker {match.group('marker')!r} for {match.group('kind')}"
            )

    audio_definitions = [
        line for line in definition_lines if line.startswith("<Audio ")
    ]
    external_audio = len(data.get("reference_audio_paths", []))
    reference_videos = len(data.get("reference_video_paths", []))
    if len(audio_definitions) > external_audio:
        synchronized = [
            line
            for line in audio_definitions
            if re.search(r"synchronized audio track of <Video [1-9]\d*>", line, re.IGNORECASE)
        ]
        required_synchronized = len(audio_definitions) - external_audio
        if required_synchronized > reference_videos:
            errors.append("Ref2VA defines more audio sources than external audio files and reference-video tracks")
        elif len(synchronized) < required_synchronized:
            errors.append("Ref2VA extra audio labels must identify their reference-video synchronized-track provenance")
    if "<d>" in sections["overall_soundscape"] or "<d>" in sections["non_diegetic_music"]:
        errors.append("H3 dialogue belongs only in detailed_description")
    return errors


def h3_prompt_errors(data: dict[str, Any]) -> list[str]:
    prompt = data.get("prompt")
    if data.get("model") != "h3" or not isinstance(prompt, str):
        return []
    if data.get("mode") == "reference_to_video":
        return ref_h3_errors(data, prompt)
    return base_h3_errors(data, prompt)


def model_policy_errors(data: dict[str, Any], checks: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    duration = data.get("duration_sec")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        minimum = checks.get("min_duration_sec")
        maximum = checks.get("max_duration_sec")
        if isinstance(minimum, (int, float)) and duration < minimum:
            errors.append(f"duration_sec {duration} is below {data['model']} minimum {minimum}")
        if isinstance(maximum, (int, float)) and duration > maximum:
            errors.append(f"duration_sec {duration} exceeds {data['model']} maximum {maximum}")

    if data.get("mode") == "reference_to_video":
        counts = {
            "reference_image_paths": len(data.get("reference_image_paths", [])),
            "reference_video_paths": len(data.get("reference_video_paths", [])),
            "reference_audio_paths": len(data.get("reference_audio_paths", [])),
        }
        total = sum(counts.values())
        limits = {
            "reference_image_paths": checks.get("max_reference_images"),
            "reference_video_paths": checks.get("max_reference_videos"),
            "reference_audio_paths": checks.get("max_reference_audio"),
        }
        for field, limit in limits.items():
            if isinstance(limit, int) and counts[field] > limit:
                errors.append(f"{field} has {counts[field]} items; model maximum is {limit}")
        max_files = checks.get("max_reference_files")
        if isinstance(max_files, int) and total > max_files:
            errors.append(f"reference file count {total} exceeds model maximum {max_files}")
    return errors


def validate(path: Path) -> list[str]:
    try:
        data = load_json(path)
        schema = load_json(SCHEMA_PATH)
    except ValueError as exc:
        return [str(exc)]

    errors = schema_errors(data, schema, schema)
    if errors or not isinstance(data, dict):
        return errors

    try:
        checks = load_model_checks(data["model"])
    except ValueError as exc:
        return [str(exc)]
    errors.extend(prompt_policy_errors(data))
    errors.extend(h3_prompt_errors(data))
    errors.extend(model_policy_errors(data, checks))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_file", type=Path, help="JSON output file to validate")
    args = parser.parse_args()

    errors = validate(args.json_file)
    if errors:
        print(f"FAIL: {args.json_file}")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"PASS: {args.json_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
