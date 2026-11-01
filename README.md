# ASC CTF 문제 생성기

분야와 난이도를 선택하면 연습용 CTF(Capture The Flag) 문제 파일을 생성하는 Python GUI(Graphical User Interface) 프로그램입니다. 기본 생성 엔진은 로컬 Codex CLI(Command-Line Interface)이며, 저장된 ChatGPT 로그인을 재사용하므로 별도의 GPT API 키가 필요하지 않습니다.

## 지원 분야와 난이도

- 분야: `web`, `pwn`, `crypto`
- 난이도: `easy`, `medium`, `hard`

생성되는 문제는 교육용 템플릿입니다. 반드시 격리된 로컬 또는 허가받은 실습 환경에서만 실행하세요.

## GUI 실행 방법

Python 3.10 이상에서 외부 패키지 없이 실행됩니다.

Codex AI 생성 기능을 사용하려면 Codex CLI가 설치되어 있고 ChatGPT 계정으로 로그인되어 있어야 합니다.

```powershell
codex login status
```

Windows 탐색기에서 `CTF-Generator-GUI.bat`를 더블클릭합니다. 또는 PowerShell에서 실행합니다.

```powershell
python .\ctf_gui.py
```

GUI에서 다음 항목을 선택하고 **코덱스로 새 CTF 생성** 버튼을 누릅니다.

- 생성 엔진: 코덱스 인공지능 또는 오프라인 내장 틀
- 데이브레이크 모델: GPT-5.6 Sol, GPT-6 Sol, GPT-6.1 Sol, GPT-6 Astra, GPT-5.6 Cyber 또는 블루/레드 최신 별칭
- 사이버 접근: 선택한 모델에 맞춰 데이브레이크 블루 또는 레드 자동 설정
- 문제 분야, 난이도, 문제 이름, 저장 위치

코덱스는 매 요청에 무작위 변형 시드를 받아 새로운 문제를 설계합니다. 작업은 **1단계 문제 설계 → 2단계 문제 파일 생성 → 3단계 검증 및 저장**으로 나뉩니다. 1단계가 끝나면 제목, 이야기, 핵심 개념, 풀이 단계, 난이도 근거, 파일 계획이 GUI에 표시됩니다. 응답을 기다리는 동안에는 30초마다 경과 시간이 갱신됩니다.

두 차례의 코덱스 요청을 사용하므로 단일 요청 방식보다 전체 시간과 사용량이 늘어날 수 있습니다. 코덱스는 읽기 전용 샌드박스에서 구조화된 JSON만 반환하며, 프로그램이 경로와 크기를 검증한 후 문제 파일을 저장합니다.

Daybreak 선택은 접근 권한을 새로 부여하지 않습니다. 로그인한 계정과 조직에 해당 Daybreak 프로그램 및 모델 권한이 있어야 합니다.

## CLI 실행 방법

자동화나 테스트에는 CLI(Command-Line Interface)도 사용할 수 있습니다.

```powershell
python .\ctf_generator.py
```

명령줄 옵션으로 한 번에 생성할 수도 있습니다.

```powershell
python .\ctf_generator.py --category web --difficulty easy --name first-web
```

## 생성 결과

```text
generated/first-web/
├── README.md          # 운영자 안내
├── metadata.json
├── public/            # 참가자에게 제공
├── deploy/            # Docker 실행 파일(서비스형 문제)
└── private/           # 플래그와 풀이, 절대 비공개
```

서비스형 문제의 실행 방법은 각 문제의 `README.md`에 포함됩니다. `pwn` 템플릿은 입출력형 기본 예제이므로 Docker 실행 시 별도의 TCP 래퍼 없이 컨테이너 터미널에서 확인합니다.
