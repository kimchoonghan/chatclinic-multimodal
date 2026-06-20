# 로컬 실행 가이드 (Running ChatClinic locally)

이 문서는 ChatClinic-Multimodal을 로컬에서 띄울 때 매번 겪는 환경 문제를 피하기 위한 체크리스트입니다.
세 가지 프로세스를 띄워야 합니다: **백엔드(FastAPI)**, **프론트엔드(Next.js)**, 그리고 요약/LLM 도구를 쓰려면 **Ollama**.

> 핵심 함정 먼저
> - **node/npm은 기본 PATH에 없습니다.** conda env `chatclinic`에 들어 있습니다. `conda activate chatclinic` 후 사용하세요.
> - **이 프로젝트는 npm workspace**입니다. 의존성은 **최상위 `node_modules/`** 에 hoist됩니다. `webapp/`에서 `npm install` 하지 마세요. 최상위에서 `npm run dev:webapp`만 실행합니다.
> - **백엔드 포트는 8001**입니다 (프론트 `apiBase` 기본값 및 README/CONTRIBUTING과 일치).
> - **요약 도구(`@soap`, `@visit_summary`)는 Ollama가 떠 있어야** 동작합니다.

---

## 0. 사전 준비 (최초 1회)

| 구성 | 위치 / 명령 |
|------|-------------|
| 백엔드 Python | 프로젝트의 `.venv` (uvicorn, pysam 등 설치됨) |
| 프론트 node/npm | conda env **`chatclinic`** (`node -v` → v25.x) |
| 프론트 의존성 | 이미 최상위 `node_modules/`에 설치됨 (`node_modules/.bin/next` 확인) |
| Ollama | `~/.local/ollama/bin/ollama` (사용자 영역 설치, root 불필요) |
| LLM 모델 | `qwen3:14b` (`ollama pull qwen3:14b`, ~9GB, RTX 4090에서 100% GPU) |

`.venv`가 없다면:
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Ollama가 없다면 (root 불필요):
```bash
curl -L https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst -o /tmp/ollama.tar.zst
mkdir -p ~/.local/ollama && tar --zstd -xf /tmp/ollama.tar.zst -C ~/.local/ollama
```

---

## 1. Ollama (요약/LLM 도구용)

```bash
# 서버 기동 (백그라운드)
nohup ~/.local/ollama/bin/ollama serve > /tmp/ollama_serve.log 2>&1 &
# 모델 준비 (최초 1회)
~/.local/ollama/bin/ollama pull qwen3:14b
# 확인
curl -s http://127.0.0.1:11434/api/version
~/.local/ollama/bin/ollama list
```

도구는 환경변수로 모델/서버를 바꿀 수 있습니다: `OLLAMA_MODEL`(기본 `qwen3:14b`), `OLLAMA_HOST`(기본 `http://127.0.0.1:11434`).

## 2. 백엔드 (FastAPI, 포트 8001)

```bash
cd <repo>
OLLAMA_HOST=http://127.0.0.1:11434 OLLAMA_MODEL=qwen3:14b \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
# 확인: curl http://127.0.0.1:8001/health  →  {"status":"ok"}
```

## 3. 프론트엔드 (Next.js, 포트 3000)

```bash
conda activate chatclinic     # node/npm을 PATH에 올림
cd <repo>                     # webapp/ 가 아니라 repo 루트에서!
npm run dev:webapp            # workspace 스크립트 (= npm --workspace webapp run dev)
# 확인: 브라우저에서 http://localhost:3000
```

> `webapp/`에 들어가 `npm install`/`npm run dev`를 직접 하지 마세요. 워크스페이스라 의존성이 루트에 있어 불필요하고, conda 밖이면 `node: command not found`가 납니다.

---

## 4. 요약 도구 사용법 (UI)

1. 브라우저에서 `http://localhost:3000` 접속
2. 임상노트 `.txt` 업로드 (예: `sample_data/DIBA_demo_16correct/AD/SA02318/clinical_note.txt`) → **text 소스**로 자동 감지
3. Chat에 명령 입력:
   - `@soap` 또는 `@patient_soap_summary` → 환자 전체를 1개 SOAP 노트로 요약
   - `@visit_summary` 또는 `@visit` → 방문(visit)별 요약
4. 결과가 Chat에 표시됩니다. (노트 앞부분의 치매예측 지시문은 도구가 자동 제거)

도구는 백엔드 `/api/v1/tools/<alias>/run`을 호출하며, 프론트는 text 소스에 대해 등록된 도구를 일반 fallback으로 라우팅합니다.

---

## 빠른 점검 (헬스체크 한 줄)

```bash
curl -s http://127.0.0.1:11434/api/version   # ollama
curl -s http://127.0.0.1:8001/health         # backend
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000  # frontend
```

## 흔한 오류

| 증상 | 원인 / 해결 |
|------|-------------|
| `node: command not found` | conda env 미활성화 → `conda activate chatclinic` |
| 프론트는 뜨는데 API 호출 실패 | 백엔드가 8001이 아닌 포트로 떠 있음. apiBase(8001)와 맞추기 |
| `@soap` 실행 시 "Cannot reach Ollama" | `ollama serve` 미기동 또는 모델 미pull |
| `text_path is required` | text 소스 업로드 없이 도구 실행함. `.txt` 먼저 업로드 |
| `@summary`가 엉뚱한 도구 실행 | `summary`는 두 도구 공통 키워드 → `@soap` / `@visit_summary`처럼 명확히 사용 |
