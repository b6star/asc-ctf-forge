#!/usr/bin/env python3
"""GUI for template-based and Codex-powered ASC CTF generation."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from codex_generator import check_codex_login, generate_with_codex
from ctf_generator import generate, slugify


PROJECT_ROOT = Path(__file__).resolve().parent
ENGINE_LABELS = {"Codex (OpenAI)": "codex", "내장 틀(빠른 생성)": "template"}
CATEGORY_LABELS = {"web": "web", "pwn": "pwn", "crypto": "crypto"}
DIFFICULTY_LABELS = {"easy": "easy", "medium": "medium", "hard": "hard"}
CYBER_LABELS = {"데이브레이크 블루": "daybreak_blue", "데이브레이크 레드": "daybreak_red", "표준": "standard"}
MODEL_OPTIONS = {
    "GPT-5.6 Sol (데이브레이크 블루 · 권장)": {
        "id": "gpt-5.6-sol", "program": "daybreak_blue",
        "note": "현재 코덱스에서 선택된 빠르고 균형 잡힌 데이브레이크 블루 모델입니다.",
    },
    "GPT-6 Sol (데이브레이크 블루)": {
        "id": "gpt-6-sol", "program": "daybreak_blue",
        "note": "데이브레이크 블루 또는 레드 승인이 있는 계정에서 사용할 수 있습니다.",
    },
    "GPT-6.1 Sol (레드 승인 필요)": {
        "id": "gpt-6.1-sol", "program": "daybreak_blue",
        "note": "데이브레이크 레드 승인이 필요하지만 내부 요청 값은 daybreak_blue입니다.",
    },
    "GPT-6 Astra (레드 승인 필요)": {
        "id": "gpt-6-astra", "program": "daybreak_blue",
        "note": "데이브레이크 레드 승인이 필요한 고성능 모델이며 내부 요청 값은 daybreak_blue입니다.",
    },
    "데이브레이크 블루 최신 모델": {
        "id": "gpt-daybreak-blue-latest", "program": "daybreak_blue",
        "note": "OpenAI가 현재 데이브레이크 블루 모델로 연결하는 최신 별칭입니다.",
    },
    "GPT-5.6 Cyber (데이브레이크 레드)": {
        "id": "gpt-5.6-cyber", "program": "daybreak_red",
        "note": "데이브레이크 레드와 별도의 모델 승인이 필요한 사이버 전용 모델입니다.",
    },
    "데이브레이크 레드 최신 모델": {
        "id": "gpt-daybreak-red-latest", "program": "daybreak_red",
        "note": "데이브레이크 레드 승인 계정용 최신 사이버 모델 별칭입니다.",
    },
}
CATEGORY_HELP = {
    "web": "웹 취약점을 이용하는 문제를 생성합니다.",
    "pwn": "네이티브 프로그램 분석 및 시스템 해킹 문제를 생성합니다.",
    "crypto": "암호문과 알고리즘을 분석하는 문제를 생성합니다.",
}


class CTFGeneratorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("[ASC] CTF 문제 생성기 · 코덱스")
        self.geometry("860x920")
        self.minsize(760, 780)
        self.configure(bg="#f4f6fb")
        self.engine_var = tk.StringVar(value="Codex (OpenAI)")
        self.category_var = tk.StringVar(value="web")
        self.difficulty_var = tk.StringVar(value="easy")
        self.cyber_var = tk.StringVar(value="데이브레이크 블루")
        self.model_var = tk.StringVar(value="GPT-5.6 Sol (데이브레이크 블루 · 권장)")
        self.model_help_var = tk.StringVar(value=MODEL_OPTIONS[self.model_var.get()]["note"])
        self.name_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(PROJECT_ROOT / "generated"))
        self.status_var = tk.StringVar(value="코덱스 연결을 확인하는 중입니다...")
        self.help_var = tk.StringVar(value=CATEGORY_HELP["web"])
        self.last_created: Path | None = None
        self._configure_styles()
        self._build_ui()
        self._on_model_changed()
        self.cyber_box.configure(state="disabled")
        self.after(150, self._check_codex_connection)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6fb")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#f4f6fb", foreground="#172033", font=("맑은 고딕", 24, "bold"))
        style.configure("Subtitle.TLabel", background="#f4f6fb", foreground="#667085", font=("맑은 고딕", 10))
        style.configure("Section.TLabel", background="#ffffff", foreground="#172033", font=("맑은 고딕", 10, "bold"))
        style.configure("Body.TLabel", background="#ffffff", foreground="#475467", font=("맑은 고딕", 9))
        style.configure("Status.TLabel", background="#eaf2ff", foreground="#175cd3", font=("맑은 고딕", 9))
        style.configure("Accent.TButton", font=("맑은 고딕", 11, "bold"), padding=(18, 12), background="#2563eb", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#98a2b3")])
        style.configure("TButton", font=("맑은 고딕", 9), padding=(10, 7))
        style.configure("TRadiobutton", background="#ffffff", foreground="#344054", font=("맑은 고딕", 9))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=(34, 26))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="[ASC] CTF 문제 생성기", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="코덱스를 이용해 CTF 문제를 생성합니다.", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 18))
        card = ttk.Frame(outer, style="Card.TFrame", padding=22)
        card.pack(fill="both", expand=True)
        card.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(card, text="생성 엔진", style="Section.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 18), pady=(0, 13))
        self.engine_box = ttk.Combobox(card, textvariable=self.engine_var, values=tuple(ENGINE_LABELS), state="readonly")
        self.engine_box.grid(row=row, column=1, sticky="ew", pady=(0, 13))
        self.engine_box.bind("<<ComboboxSelected>>", self._on_engine_changed)

        row += 1
        ttk.Label(card, text="사이버 접근(자동)", style="Section.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 18), pady=(0, 13))
        cyber_frame = ttk.Frame(card, style="Card.TFrame")
        cyber_frame.grid(row=row, column=1, sticky="ew", pady=(0, 13))
        cyber_frame.columnconfigure(0, weight=1)
        self.cyber_box = ttk.Combobox(cyber_frame, textvariable=self.cyber_var, values=tuple(CYBER_LABELS), state="readonly")
        self.cyber_box.grid(row=0, column=0, sticky="ew")
        self.connection_button = ttk.Button(cyber_frame, text="연결 확인", command=self._check_codex_connection)
        self.connection_button.grid(row=0, column=1, padx=(8, 0))

        row += 1
        ttk.Label(card, text="데이브레이크 모델", style="Section.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 18), pady=(0, 8))
        self.model_box = ttk.Combobox(card, textvariable=self.model_var, values=tuple(MODEL_OPTIONS), state="readonly")
        self.model_box.grid(row=row, column=1, sticky="ew", pady=(0, 8))
        self.model_box.bind("<<ComboboxSelected>>", self._on_model_changed)
        row += 1
        ttk.Label(card, textvariable=self.model_help_var, style="Body.TLabel", wraplength=520).grid(row=row, column=1, sticky="w", pady=(0, 14))

        row += 1
        ttk.Separator(card).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        row += 1
        ttk.Label(card, text="문제 분야", style="Section.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 18), pady=(0, 8))
        category_box = ttk.Combobox(card, textvariable=self.category_var, values=tuple(CATEGORY_LABELS), state="readonly")
        category_box.grid(row=row, column=1, sticky="ew", pady=(0, 8))
        category_box.bind("<<ComboboxSelected>>", self._on_category_changed)
        row += 1
        ttk.Label(card, textvariable=self.help_var, style="Body.TLabel", wraplength=520).grid(row=row, column=1, sticky="w", pady=(0, 16))

        row += 1
        ttk.Label(card, text="난이도", style="Section.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 18), pady=(0, 16))
        difficulties = ttk.Frame(card, style="Card.TFrame")
        difficulties.grid(row=row, column=1, sticky="w", pady=(0, 16))
        for index, label in enumerate(DIFFICULTY_LABELS):
            ttk.Radiobutton(difficulties, text=label, value=label, variable=self.difficulty_var).grid(row=0, column=index, padx=(0, 18))

        row += 1
        ttk.Label(card, text="문제 이름", style="Section.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 18), pady=(0, 14))
        ttk.Entry(card, textvariable=self.name_var).grid(row=row, column=1, sticky="ew", pady=(0, 14))
        row += 1
        ttk.Label(card, text="저장 위치", style="Section.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 18), pady=(0, 18))
        output_frame = ttk.Frame(card, style="Card.TFrame")
        output_frame.grid(row=row, column=1, sticky="ew", pady=(0, 18))
        output_frame.columnconfigure(0, weight=1)
        ttk.Entry(output_frame, textvariable=self.output_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(output_frame, text="찾아보기", command=self._browse_output).grid(row=0, column=1, padx=(8, 0))

        row += 1
        self.generate_button = ttk.Button(card, text="Generate", style="Accent.TButton", command=self._create_challenge)
        self.generate_button.grid(row=row, column=0, columnspan=2, sticky="ew")
        row += 1
        self.open_button = ttk.Button(card, text="생성된 폴더 열기", command=self._open_created_folder, state="disabled")
        self.open_button.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        log_frame = ttk.LabelFrame(outer, text="코덱스 실시간 작업 기록", padding=(10, 8))
        log_frame.pack(fill="both", expand=True, pady=(14, 0))
        self.log_text = ScrolledText(
            log_frame, height=10, state="disabled", wrap="word", bg="#101828", fg="#d0d5dd",
            insertbackground="#ffffff", font=("Consolas", 9), relief="flat", padx=10, pady=8,
        )
        self.log_text.pack(fill="both", expand=True)
        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel", padding=(14, 10), wraplength=760).pack(fill="x", pady=(10, 0))

    def _on_engine_changed(self, _event: object = None) -> None:
        is_codex = ENGINE_LABELS[self.engine_var.get()] == "codex"
        self.cyber_box.configure(state="disabled")
        self.model_box.configure(state="readonly" if is_codex else "disabled")
        self.connection_button.configure(state="normal" if is_codex else "disabled")
        self.generate_button.configure(text="코덱스로 새 CTF 생성" if is_codex else "내장 틀로 CTF 생성")
        self.status_var.set("코덱스는 생성할 때마다 새 변형을 설계합니다." if is_codex else "내장 틀은 오프라인에서 즉시 생성됩니다.")

    def _on_category_changed(self, _event: object = None) -> None:
        self.help_var.set(CATEGORY_HELP[CATEGORY_LABELS[self.category_var.get()]])

    def _on_model_changed(self, _event: object = None) -> None:
        option = MODEL_OPTIONS[self.model_var.get()]
        program_label = next(label for label, value in CYBER_LABELS.items() if value == option["program"])
        self.cyber_var.set(program_label)
        self.model_help_var.set(option["note"])
        self.status_var.set(f"선택 모델: {option['id']} · {program_label}")

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _queue_log(self, message: str) -> None:
        def deliver() -> None:
            self._append_log(message)
            self.status_var.set(message)
        self.after(0, deliver)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _check_codex_connection(self) -> None:
        self.connection_button.configure(state="disabled")
        self.status_var.set("코덱스 명령줄 도구와 로그인 상태를 확인하는 중입니다...")
        def worker() -> None:
            ok, message = check_codex_login()
            self.after(0, lambda: self._finish_connection_check(ok, message))
        threading.Thread(target=worker, daemon=True).start()

    def _finish_connection_check(self, ok: bool, message: str) -> None:
        self.connection_button.configure(state="normal")
        self.status_var.set(("코덱스 연결됨: " if ok else "코덱스 연결 필요: ") + message)

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(title="CTF 문제 저장 폴더 선택", initialdir=self.output_var.get() or str(PROJECT_ROOT))
        if selected:
            self.output_var.set(selected)

    def _create_challenge(self) -> None:
        output_text = self.output_var.get().strip()
        if not output_text:
            messagebox.showwarning("저장 위치 필요", "문제를 저장할 폴더를 선택하세요.")
            return
        category = CATEGORY_LABELS[self.category_var.get()]
        difficulty = DIFFICULTY_LABELS[self.difficulty_var.get()]
        output = Path(output_text).expanduser()
        name = self.name_var.get().strip() or None
        engine = ENGINE_LABELS[self.engine_var.get()]
        force = False
        if name:
            candidate = output / slugify(name)
            if candidate.exists():
                force = messagebox.askyesno("기존 문제 덮어쓰기", f"이미 같은 이름의 폴더가 있습니다.\n\n{candidate}\n\n기존 내용을 지우고 새로 생성할까요?", icon="warning")
                if not force:
                    self.status_var.set("생성을 취소했습니다. 다른 문제 이름을 입력하세요.")
                    return

        model_option = MODEL_OPTIONS[self.model_var.get()]
        cyber_program = model_option["program"]
        model = model_option["id"]
        self._clear_log()
        self._append_log(f"생성 요청: {category} · {difficulty} · {model}")
        self.generate_button.configure(state="disabled", text="코덱스가 문제를 설계하는 중..." if engine == "codex" else "생성 중...")
        self.open_button.configure(state="disabled")
        self.status_var.set("코덱스 응답을 기다리는 중입니다. 복잡한 문제는 몇 분 걸릴 수 있습니다." if engine == "codex" else "내장 틀로 문제를 생성하는 중입니다.")

        def worker() -> None:
            try:
                if engine == "codex":
                    destination = generate_with_codex(category, difficulty, output, name, force, cyber_program, model, self._queue_log)
                else:
                    self._queue_log("내장 틀을 이용해 문제 파일을 생성하고 있습니다.")
                    destination = generate(category, difficulty, output, name, force)
                    self._queue_log("내장 틀 문제 파일 저장을 완료했습니다.")
            except Exception as error:
                self.after(0, lambda error=error: self._finish_generation(None, error))
            else:
                self.after(0, lambda: self._finish_generation(destination, None))
        threading.Thread(target=worker, daemon=True).start()

    def _finish_generation(self, destination: Path | None, error: Exception | None) -> None:
        label = "Generate"
        self.generate_button.configure(state="normal", text=label)
        if error:
            self._append_log(f"생성 실패: {error}")
            self.status_var.set("문제를 생성하지 못했습니다.")
            messagebox.showerror("생성 실패", str(error))
            return
        assert destination is not None
        self.last_created = destination.resolve()
        self._append_log("모든 생성 작업이 완료되었습니다.")
        self.open_button.configure(state="normal")
        self.status_var.set(f"생성 완료: {self.last_created}")
        messagebox.showinfo("생성 완료", f"CTF 문제가 생성되었습니다.\n\n위치: {self.last_created}\n\npublic 폴더만 참가자에게 제공하세요. private 폴더에는 정답이 들어 있습니다.")

    def _open_created_folder(self) -> None:
        if not self.last_created or not self.last_created.exists():
            messagebox.showwarning("폴더 없음", "생성된 문제 폴더를 찾을 수 없습니다.")
            return
        if os.name == "nt":
            os.startfile(self.last_created)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(self.last_created)])
        else:
            subprocess.Popen(["xdg-open", str(self.last_created)])


def main() -> None:
    CTFGeneratorApp().mainloop()


if __name__ == "__main__":
    main()
