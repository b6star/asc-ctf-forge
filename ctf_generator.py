#!/usr/bin/env python3
"""Template-based CTF challenge generator.

This is intentionally small and dependency-free.  It creates toy challenges for
local, authorized CTF practice; generated services should not be exposed to an
untrusted network without additional isolation.
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import string
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


CATEGORIES = {"1": "web", "2": "pwn", "3": "crypto"}
DIFFICULTIES = {"1": "easy", "2": "medium", "3": "hard"}


@dataclass(frozen=True)
class Challenge:
    title: str
    description: str
    public_files: dict[str, str]
    deploy_files: dict[str, str]
    solution: str


def make_flag(category: str) -> str:
    token = secrets.token_hex(8)
    return f"ASC{{{category}_{token}}}"


def slugify(value: str) -> str:
    allowed = string.ascii_lowercase + string.digits + "-"
    value = value.strip().lower().replace(" ", "-")
    slug = "".join(ch for ch in value if ch in allowed).strip("-")
    return slug or "challenge"


def build_web(difficulty: str, flag: str) -> Challenge:
    admin_id = {"easy": 2, "medium": secrets.randbelow(80) + 20, "hard": secrets.randbelow(9000) + 1000}[difficulty]
    hints = {
        "easy": "주소의 id 값을 바꿔 다른 사용자의 메모를 확인해 보세요.",
        "medium": "모든 객체가 현재 사용자에게 허용된 객체인지 확인되고 있을까요?",
        "hard": "클라이언트가 보내는 객체 식별자를 서버가 그대로 신뢰하는지 살펴보세요.",
    }
    server = f'''\
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

USERS = {{
    1: {{"name": "guest", "note": "Welcome, guest!"}},
    {admin_id}: {{"name": "admin", "note": "{flag}"}},
}}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/profile":
            self.send_response(302)
            self.send_header("Location", "/profile?id=1")
            self.end_headers()
            return

        try:
            user_id = int(parse_qs(parsed.query).get("id", ["1"])[0])
        except ValueError:
            user_id = 1

        # 취약점: 로그인한 사용자(guest)가 요청한 객체를 소유하는지 검사하지 않는다.
        user = USERS.get(user_id, {{"name": "unknown", "note": "No such user"}})
        body = f"<h1>{{user['name']}}</h1><p>{{user['note']}}</p>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
'''
    return Challenge(
        title=f"Lost Profile ({difficulty})",
        description=f"게스트로 접속해 관리자의 비밀 메모를 찾으세요.\n\n힌트: {hints[difficulty]}",
        public_files={},
        deploy_files={
            "server.py": server,
            "Dockerfile": "FROM python:3.12-alpine\nWORKDIR /app\nCOPY server.py .\nEXPOSE 8000\nCMD [\"python\", \"server.py\"]\n",
        },
        solution=f"IDOR(Insecure Direct Object Reference) 취약점이다. `/profile?id={admin_id}`로 요청하면 권한 검사 없이 관리자 메모와 플래그가 노출된다.",
    )


def build_pwn(difficulty: str, flag: str) -> Challenge:
    buffer_size = {"easy": 32, "medium": 48, "hard": 64}[difficulty]
    hints = {
        "easy": "긴 문자열을 입력하고 스택의 인접한 값이 바뀌는지 확인하세요.",
        "medium": "컴파일 옵션과 check 함수의 지역 변수 배치를 살펴보세요.",
        "hard": "디버거로 스택 프레임과 입력 길이를 분석하세요.",
    }
    source = f'''\
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void win(void) {{
    FILE *fp = fopen("flag.txt", "r");
    char flag[128] = {{0}};
    if (!fp) exit(1);
    fgets(flag, sizeof(flag), fp);
    puts(flag);
    fclose(fp);
}}

void check(void) {{
    volatile unsigned int is_admin = 0;
    char name[{buffer_size}];
    puts("What is your name?");
    /* 교육용 취약점: 입력 길이를 검사하지 않는다. */
    gets(name);
    printf("Hello, %s!\\n", name);
    if (is_admin == 0x41414141) win();
}}

int main(void) {{
    setbuf(stdout, NULL);
    check();
    return 0;
}}
'''
    return Challenge(
        title=f"Overflow Me ({difficulty})",
        description=f"프로그램의 입력 처리를 분석해 플래그를 출력하세요.\n\n힌트: {hints[difficulty]}",
        public_files={"challenge.c": source},
        deploy_files={
            "challenge.c": source,
            "flag.txt": flag + "\n",
            "Dockerfile": "FROM alpine:3.20 AS build\nRUN apk add --no-cache gcc musl-dev\nWORKDIR /src\nCOPY challenge.c .\nRUN gcc -O0 -fno-stack-protector -no-pie -Wno-implicit-function-declaration -o challenge challenge.c\n\nFROM alpine:3.20\nWORKDIR /app\nCOPY --from=build /src/challenge .\nCOPY flag.txt .\nCMD [\"./challenge\"]\n",
        },
        solution=f"스택 버퍼 오버플로(Stack Buffer Overflow)를 이용한다. `{buffer_size}`바이트 버퍼를 넘는 입력으로 인접한 `is_admin` 값을 `0x41414141`로 덮으면 `win()`이 호출된다. 컴파일러와 환경에 따라 정확한 오프셋은 디버거로 확인한다.",
    )


def xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


def build_crypto(difficulty: str, flag: str) -> Challenge:
    if difficulty == "easy":
        shift = secrets.randbelow(20) + 3
        alphabet = string.ascii_letters + string.digits + "{}_"
        cipher = "".join(alphabet[(alphabet.index(ch) + shift) % len(alphabet)] for ch in flag)
        public = f"ciphertext = {cipher}\n"
        solution = f"사용된 문자는 고정 알파벳에서 {shift}칸 이동한 Caesar Cipher(시저 암호)다. 각 문자를 {shift}칸 반대로 이동하면 `{flag}`가 나온다."
    else:
        key_len = 1 if difficulty == "medium" else 4
        key = secrets.token_bytes(key_len)
        cipher = xor_bytes(flag.encode(), key).hex()
        clue = "키는 1바이트이다." if difficulty == "medium" else "플래그는 ASC{ 로 시작하며, 키는 4바이트 주기로 반복된다."
        public = f"ciphertext_hex = {cipher}\nclue = {clue}\n"
        solution = f"Repeated-key XOR(반복 키 배타적 논리합) 암호다. 알려진 플래그 형식과 반복 주기를 이용해 키 `{key.hex()}`를 복구하고 복호화하면 `{flag}`가 나온다."

    return Challenge(
        title=f"Secret Message ({difficulty})",
        description="암호문을 분석해 원래 플래그를 복구하세요.",
        public_files={"challenge.txt": public},
        deploy_files={},
        solution=solution,
    )


BUILDERS = {"web": build_web, "pwn": build_pwn, "crypto": build_crypto}


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def generate(category: str, difficulty: str, output: Path, name: str | None = None, force: bool = False) -> Path:
    flag = make_flag(category)
    challenge = BUILDERS[category](difficulty, flag)
    timestamp = datetime.now().strftime("%y%m%d%H%M%S")
    folder_name = slugify(name) if name else f"{category}-{difficulty}-{timestamp}"
    destination = output / folder_name

    if destination.exists():
        if not force:
            raise FileExistsError(f"이미 존재하는 폴더입니다: {destination} (`--force`로 덮어쓰기)")
        shutil.rmtree(destination)

    destination.mkdir(parents=True)
    public_readme = f"# {challenge.title}\n\n{challenge.description}\n\n플래그 형식: `ASC{{...}}`\n"
    organizer_readme = textwrap.dedent(
        f"""\
        # {challenge.title}

        - 분야: `{category}`
        - 난이도: `{difficulty}`
        - 생성 시각: `{datetime.now().isoformat(timespec='seconds')}`

        참가자에게는 `public/` 내용과 실행 중인 서비스의 주소만 제공합니다.
        `private/`는 정답을 포함하므로 공개하지 마세요.

        ## 로컬 실행

        서비스형 문제는 다음 명령으로 실행할 수 있습니다.

        ```bash
        cd deploy
        docker build -t generated-ctf .
        docker run --rm -p 8000:8000 generated-ctf
        ```
        """
    )
    write_text(destination / "README.md", organizer_readme)
    write_text(destination / "public" / "README.md", public_readme)
    for filename, content in challenge.public_files.items():
        write_text(destination / "public" / filename, content)
    for filename, content in challenge.deploy_files.items():
        write_text(destination / "deploy" / filename, content)
    write_text(destination / "private" / "flag.txt", flag + "\n")
    write_text(destination / "private" / "solution.md", f"# 풀이\n\n{challenge.solution}\n")
    metadata = {
        "title": challenge.title,
        "category": category,
        "difficulty": difficulty,
        "flag_format": "ASC{...}",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_text(destination / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return destination


def choose(prompt: str, choices: dict[str, str]) -> str:
    reverse = {value: value for value in choices.values()}
    while True:
        print(prompt)
        for number, value in choices.items():
            print(f"  {number}. {value}")
        answer = input("> ").strip().lower()
        if answer in choices:
            return choices[answer]
        if answer in reverse:
            return reverse[answer]
        print("올바른 번호 또는 이름을 입력하세요.\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="간단한 템플릿 기반 CTF 문제 생성기")
    parser.add_argument("--category", choices=tuple(CATEGORIES.values()), help="문제 분야")
    parser.add_argument("--difficulty", choices=tuple(DIFFICULTIES.values()), help="문제 난이도")
    parser.add_argument("--output", type=Path, default=Path("generated"), help="출력 폴더")
    parser.add_argument("--name", help="생성할 문제 폴더 이름")
    parser.add_argument("--force", action="store_true", help="같은 이름의 문제 폴더 덮어쓰기")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    category = args.category or choose("분야를 선택하세요.", CATEGORIES)
    difficulty = args.difficulty or choose("난이도를 선택하세요.", DIFFICULTIES)
    try:
        destination = generate(category, difficulty, args.output, args.name, args.force)
    except FileExistsError as error:
        print(f"오류: {error}")
        return 1
    print(f"\nCTF 문제가 생성되었습니다: {destination.resolve()}")
    print("참가자용: public/")
    print("운영자 전용: private/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
