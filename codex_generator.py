#!/usr/bin/env python3
"""Generate original CTF challenges through the locally authenticated Codex CLI."""

from __future__ import annotations

import json
import os
import queue
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from ctf_generator import slugify, write_text


CODEX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"}, "description": {"type": "string"},
        "flag": {"type": "string"}, "solution": {"type": "string"},
        "run_instructions": {"type": "string"},
        "concepts": {"type": "array", "items": {"type": "string"}},
        "files": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "area": {"type": "string", "enum": ["public", "deploy"]},
                "path": {"type": "string"}, "content": {"type": "string"},
            },
            "required": ["area", "path", "content"], "additionalProperties": False,
        }},
    },
    "required": ["title", "description", "flag", "solution", "run_instructions", "concepts", "files"],
    "additionalProperties": False,
}

DESIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "story": {"type": "string"},
        "core_concept": {"type": "string"},
        "intended_steps": {"type": "array", "items": {"type": "string"}},
        "difficulty_reason": {"type": "string"},
        "artifact_plan": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "story", "core_concept", "intended_steps", "difficulty_reason", "artifact_plan"],
    "additionalProperties": False,
}


class CodexGenerationError(RuntimeError):
    pass


def find_codex() -> str | None:
    return shutil.which("codex")


def check_codex_login(timeout: int = 15) -> tuple[bool, str]:
    executable = find_codex()
    if not executable:
        return False, "코덱스 명령줄 도구를 찾을 수 없습니다. 먼저 코덱스 명령줄 도구를 설치하세요."
    try:
        result = subprocess.run(
            [executable, "login", "status"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"코덱스 상태 확인 실패: {error}"
    message = (result.stdout or result.stderr).strip()
    return result.returncode == 0, message or "코덱스 로그인 상태를 확인하지 못했습니다."


def build_prompt(category: str, difficulty: str, variation_seed: str) -> str:
    category_rules = {
        "web": "Create a small HTTP web challenge. Include all source and a Dockerfile in deploy/. Prefer a self-contained Python service.",
        "pwn": "Create a native binary exploitation challenge. Include C source, build settings, and a Dockerfile in deploy/, plus player attachments in public/.",
        "crypto": "Create a self-contained cryptography challenge with ciphertext/data and any intended player script in public/.",
    }
    difficulty_rules = {
        "easy": "The intended path should teach one core idea and include one clear hint.",
        "medium": "Use two linked observations and only a conceptual hint.",
        "hard": "Require careful multi-step analysis, but remain realistically solvable from the supplied artifacts.",
    }
    return f"""Generate one original educational CTF challenge for an authorized, isolated local lab.

Category: {category}
Difficulty: {difficulty}
Variation seed: {variation_seed}

Uniqueness requirements:
- Invent a fresh narrative, parameters, identifiers, secrets, and intended solution path for this seed.
- Do not fall back to generic IDOR-only, gets()-only, Caesar-only, or one-byte-XOR-only exercises unless an original twist materially changes the solution.
- The challenge must be internally consistent and actually solvable.

Category requirement: {category_rules[category]}
Difficulty requirement: {difficulty_rules[difficulty]}

Output requirements:
- Return only data matching the provided JSON schema.
- Write all titles, descriptions, hints, instructions, and solution prose in Korean. Keep only technical terms, commands, code, filenames, and identifiers in their original language.
- The unique flag must have the exact form ASC{{...}}.
- `files` contains relative paths for only `public` or `deploy`; never use absolute paths or `..`.
- `public` is safe to give players. Never put the flag or official solution there.
- `deploy` contains complete organizer runtime/build files. A service binds to 0.0.0.0 and documents its port.
- `solution` explains the reasoning, commands, and defensive mitigation where applicable.
- `run_instructions` gives concrete Windows-friendly organizer instructions, including Docker commands when used.
- Keep total generated source concise, preferably under 40 KB.
- Do not access networks, attack external targets, or depend on real credentials.
"""


def build_design_prompt(category: str, difficulty: str, variation_seed: str) -> str:
    return f"""교육용 CTF 문제의 설계안만 작성하세요. 아직 코드나 최종 문제 파일은 만들지 마세요.

분야: {category}
난이도: {difficulty}
변형 시드: {variation_seed}

요구 사항:
- 기존의 흔한 단일 취약점 예제를 그대로 반복하지 말고 이 시드만의 이야기와 풀이 구조를 만드세요.
- 의도한 풀이 단계를 참가자가 실제로 수행할 수 있도록 구체적으로 설계하세요.
- 난이도가 왜 {difficulty}인지 설명하세요.
- 참가자용 자료와 실행 환경에 필요한 파일 계획을 정하세요.
- 제목, 이야기, 개념, 설명은 기술 용어를 제외하고 한글로 작성하세요.
- 제공된 JSON 스키마에 맞는 데이터만 반환하세요.
"""


def _parse_result(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        stripped = "\n".join(lines)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise CodexGenerationError(f"코덱스가 올바른 JSON을 반환하지 않았습니다: {error}") from error
    if not isinstance(data, dict):
        raise CodexGenerationError("코덱스 결과가 JSON 객체가 아닙니다.")
    return data


def validate_spec(spec: dict[str, Any]) -> None:
    for field in ("title", "description", "flag", "solution", "run_instructions"):
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            raise CodexGenerationError(f"코덱스 결과의 `{field}` 값이 비어 있습니다.")
    if not spec["flag"].startswith("ASC{") or not spec["flag"].endswith("}") or len(spec["flag"]) > 200:
        raise CodexGenerationError("플래그 형식이 ASC{...}가 아닙니다.")
    if not isinstance(spec.get("concepts"), list) or not all(isinstance(item, str) for item in spec["concepts"]):
        raise CodexGenerationError("`concepts`가 문자열 배열이 아닙니다.")
    if not isinstance(spec.get("files"), list) or not spec["files"]:
        raise CodexGenerationError("생성된 문제 파일이 없습니다.")
    seen: set[tuple[str, str]] = set()
    total_size = 0
    for item in spec["files"]:
        if not isinstance(item, dict) or item.get("area") not in {"public", "deploy"}:
            raise CodexGenerationError("파일 영역은 public 또는 deploy여야 합니다.")
        raw_path, content = item.get("path"), item.get("content")
        if not isinstance(raw_path, str) or not isinstance(content, str):
            raise CodexGenerationError("파일 경로와 내용은 문자열이어야 합니다.")
        normalized = raw_path.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise CodexGenerationError(f"안전하지 않은 파일 경로입니다: {raw_path}")
        key = (item["area"], normalized.lower())
        if key in seen:
            raise CodexGenerationError(f"중복된 파일 경로입니다: {item['area']}/{raw_path}")
        seen.add(key)
        total_size += len(content.encode("utf-8"))
    if total_size > 1_000_000:
        raise CodexGenerationError("생성 결과가 1MB를 초과해 저장을 중단했습니다.")


def format_codex_event(event: dict[str, Any]) -> str | None:
    """Convert one Codex JSONL event into a concise Korean progress message."""
    event_type = event.get("type", "")
    if event_type == "thread.started":
        return "코덱스 작업을 시작했습니다."
    if event_type == "turn.started":
        return "선택한 조건을 분석하고 문제 구조를 설계하고 있습니다."
    if event_type == "turn.completed":
        usage = event.get("usage") or {}
        output_tokens = usage.get("output_tokens")
        suffix = f" (출력 토큰: {output_tokens})" if isinstance(output_tokens, int) else ""
        return "코덱스 문제 설계가 완료되었습니다." + suffix
    if event_type == "turn.failed":
        return "코덱스 작업이 실패했습니다. 오류 내용을 확인하세요."
    if event_type == "error":
        message = event.get("message") or event.get("error") or "알 수 없는 오류"
        return f"오류: {str(message)[:500]}"
    if not event_type.startswith("item."):
        return None

    item = event.get("item") or {}
    item_type = item.get("type", "")
    finished = event_type == "item.completed"
    if item_type == "reasoning":
        return "문제의 풀이 가능성과 난이도를 검토했습니다." if finished else "문제의 풀이 경로와 난이도를 검토하고 있습니다."
    if item_type == "agent_message":
        return "최종 문제 자료를 구성했습니다." if finished else "최종 문제 자료를 구성하고 있습니다."
    if item_type == "command_execution":
        command = str(item.get("command", "명령"))[:300]
        return f"명령 실행 완료: {command}" if finished else f"명령 실행: {command}"
    if item_type == "web_search":
        query = str(item.get("query", "관련 자료"))[:300]
        return f"자료 검색 완료: {query}" if finished else f"자료 검색: {query}"
    if item_type == "mcp_tool_call":
        tool = str(item.get("tool", item.get("name", "도구")))[:200]
        return f"도구 사용 완료: {tool}" if finished else f"도구 사용: {tool}"
    if item_type == "file_change":
        return "파일 변경 내용을 정리했습니다." if finished else "파일 변경 내용을 준비하고 있습니다."
    if item_type == "plan_update":
        return "작업 계획을 갱신했습니다."
    return None


def _run_codex_stream(
    command: list[str],
    prompt: str,
    cwd: Path,
    environment: dict[str, str],
    timeout: int,
    progress: Callable[[str], None] | None,
    heartbeat_label: str = "코덱스가 응답을 생성하고 있습니다",
) -> tuple[int, str]:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=environment,
        )
    except OSError as error:
        raise CodexGenerationError(f"코덱스 명령줄 도구 실행 실패: {error}") from error

    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(prompt)
    process.stdin.close()

    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read_output, daemon=True).start()
    started_at = time.monotonic()
    deadline = started_at + timeout
    last_heartbeat = started_at
    captured: list[str] = []
    while True:
        if time.monotonic() >= deadline:
            process.kill()
            process.wait()
            raise CodexGenerationError(f"코덱스 생성 시간이 {timeout}초를 초과했습니다.")
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            now = time.monotonic()
            if progress and now - last_heartbeat >= 30:
                progress(f"{heartbeat_label} ({int(now - started_at)}초 경과)")
                last_heartbeat = now
            continue
        if line is None:
            break
        captured.append(line)
        stripped = line.strip()
        if not stripped or progress is None:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            # Codex may emit plugin/runtime diagnostics alongside the JSONL stream.
            # Keep them for error reporting, but do not clutter the user-facing log.
            continue
        else:
            if isinstance(event, dict):
                message = format_codex_event(event)
                if message:
                    progress(message)
    return process.wait(), "".join(captured)


def _request_structured(
    executable: str,
    temp: Path,
    file_prefix: str,
    schema: dict[str, Any],
    prompt: str,
    cyber_program: str,
    model: str | None,
    timeout: int,
    progress: Callable[[str], None] | None,
    phase: str,
) -> dict[str, Any]:
    schema_path = temp / f"{file_prefix}-schema.json"
    result_path = temp / f"{file_prefix}-result.json"
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    command = [
        executable, "exec", "--json", "--sandbox", "read-only", "--ephemeral",
        "--skip-git-repo-check", "--color", "never", "--cyber-access-program", cyber_program,
        "--output-schema", str(schema_path), "--output-last-message", str(result_path),
    ]
    if model and model.strip():
        command.extend(["--model", model.strip()])
    command.append("-")
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"

    phase_progress = None
    if progress:
        phase_progress = lambda message: progress(f"[{phase}] {message}")
        progress(f"[{phase}] 모델 {model or '기본 모델'}에 요청을 보냈습니다.")
    return_code, output = _run_codex_stream(
        command, prompt, Path(__file__).resolve().parent, environment, timeout,
        phase_progress, "코덱스가 응답을 생성하고 있습니다",
    )
    if return_code != 0:
        detail = output.strip()[-4000:]
        raise CodexGenerationError(f"코덱스가 {phase} 작업을 완료하지 못했습니다.\n\n{detail}")
    if not result_path.is_file():
        raise CodexGenerationError(f"{phase} 결과 파일이 생성되지 않았습니다.")
    return _parse_result(result_path.read_text(encoding="utf-8"))


def request_challenge(
    category: str,
    difficulty: str,
    cyber_program: str = "daybreak_blue",
    model: str | None = None,
    timeout: int = 900,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], str]:
    executable = find_codex()
    if not executable:
        raise CodexGenerationError("코덱스 명령줄 도구를 찾을 수 없습니다. `codex`를 설치하고 ChatGPT로 로그인하세요.")
    if cyber_program not in {"standard", "daybreak_blue", "daybreak_red"}:
        raise ValueError(f"지원하지 않는 사이버 프로그램입니다: {cyber_program}")
    variation_seed = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="asc-ctf-codex-") as temp_dir:
        temp = Path(temp_dir)
        design = _request_structured(
            executable, temp, "design", DESIGN_SCHEMA,
            build_design_prompt(category, difficulty, variation_seed), cyber_program, model,
            timeout, progress, "1단계: 문제 설계",
        )
        if progress:
            progress(f"[설계안] 제목: {design['title']}")
            progress(f"[설계안] 이야기: {design['story']}")
            progress(f"[설계안] 핵심 개념: {design['core_concept']}")
            for index, step in enumerate(design["intended_steps"], 1):
                progress(f"[설계안] 풀이 {index}: {step}")
            progress(f"[설계안] 난이도 근거: {design['difficulty_reason']}")
            for artifact in design["artifact_plan"]:
                progress(f"[설계안] 파일 계획: {artifact}")

        final_prompt = build_prompt(category, difficulty, variation_seed) + (
            "\n아래에서 확정된 설계안을 그대로 구현하되, 모순이나 풀이 불가능성이 없도록 검증하세요.\n"
            + json.dumps(design, ensure_ascii=False, indent=2)
        )
        spec = _request_structured(
            executable, temp, "challenge", CODEX_SCHEMA, final_prompt, cyber_program,
            model, timeout, progress, "2단계: 문제 파일 생성",
        )
        if progress:
            progress("[3단계: 검증] 반환된 문제 구조와 파일 경로를 검사하고 있습니다.")
        validate_spec(spec)
        if progress:
            progress("[3단계: 검증] 문제 구조 검사를 통과했습니다.")
        return spec, variation_seed


def save_challenge(spec: dict[str, Any], category: str, difficulty: str, output: Path, variation_seed: str, cyber_program: str, model: str | None = None, name: str | None = None, force: bool = False) -> Path:
    validate_spec(spec)
    timestamp = datetime.now().strftime("%y%m%d%H%M%S")
    folder_name = slugify(name) if name else f"{category}-{difficulty}-{timestamp}"
    destination = output / folder_name
    if destination.exists():
        if not force:
            raise FileExistsError(f"이미 존재하는 폴더입니다: {destination}")
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    organizer_readme = (
        f"# {spec['title']}\n\n{spec['description']}\n\n- 분야: `{category}`\n- 난이도: `{difficulty}`\n"
        f"- 생성 엔진: `Codex`\n- 사이버 프로그램: `{cyber_program}`\n- 모델: `{model or 'Codex 기본값'}`\n"
        f"- 변형 시드: `{variation_seed}`\n\n## 실행 방법\n\n{spec['run_instructions']}\n\n"
        "## 공개 범위\n\n참가자에게는 `public/` 내용과 실행 중인 서비스 주소만 제공합니다. `private/`는 공개하지 마세요.\n"
    )
    write_text(destination / "README.md", organizer_readme)
    write_text(destination / "public" / "README.md", f"# {spec['title']}\n\n{spec['description']}\n\n플래그 형식: `ASC{{...}}`\n")
    for item in spec["files"]:
        relative = Path(*PurePosixPath(item["path"].replace("\\", "/")).parts)
        write_text(destination / item["area"] / relative, item["content"])
    write_text(destination / "private" / "flag.txt", spec["flag"].strip() + "\n")
    concepts = "\n".join(f"- {concept}" for concept in spec["concepts"])
    write_text(destination / "private" / "solution.md", f"# 공식 풀이\n\n## 핵심 개념\n\n{concepts}\n\n## 풀이 과정\n\n{spec['solution']}\n")
    metadata = {"title": spec["title"], "category": category, "difficulty": difficulty, "engine": "codex", "model": model or "default", "cyber_program": cyber_program, "variation_seed": variation_seed, "generated_at": datetime.now().isoformat(timespec="seconds")}
    write_text(destination / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return destination


def generate_with_codex(category: str, difficulty: str, output: Path, name: str | None = None, force: bool = False, cyber_program: str = "daybreak_blue", model: str | None = None, progress: Callable[[str], None] | None = None) -> Path:
    spec, variation_seed = request_challenge(category, difficulty, cyber_program, model, progress=progress)
    if progress:
        progress("검증된 문제 파일을 저장하고 있습니다.")
    destination = save_challenge(spec, category, difficulty, output, variation_seed, cyber_program, model, name, force)
    if progress:
        progress(f"문제 파일 저장을 완료했습니다: {destination}")
    return destination
