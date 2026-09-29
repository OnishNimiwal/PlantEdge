# MRPL Local AI — Sovereign On-Premise AI Workbench

A private, fully on-premise AI workbench for an industrial environment. Users chat with local
large language models, ask questions about documents and scanned reports, analyse images, and
generate code. **All AI inference runs on local hardware through [Ollama](https://ollama.com);
no prompt, document or image is ever sent to an external or cloud AI service.**

| | |
|---|---|
| **Frontend** | React 18 + Vite 5 single-page app (chat, Document Assistant, Dashboard) |
| **Backend** | Django 6.1 + Django REST Framework 3.18 (Python 3.12) |
| **Inference** | Ollama 0.33 serving three local models: `qwen3:8b`, `qwen2.5-coder:7b`, `qwen2.5vl:7b` |
| **OCR** | PaddleOCR 3.7 (PaddlePaddle 3.3, CPU) for scanned PDFs and images |
| **Storage** | SQLite (metadata, conversations, usage records) + local `media/` folder (uploads) |
| **Target hardware** | One workstation/server with an 8 GB NVIDIA GPU, 16 GB RAM, serving LAN clients |
| **Tests** | 138 automated backend tests + live browser verification |

> **Status:** working prototype, tested end to end on the development machine. Authentication,
> production deployment hardening and retrieval-augmented generation (RAG) are **not implemented
> yet** — see [Limitations & roadmap](#20-limitations--roadmap).

---

## Table of contents

1. [What it does](#1-what-it-does)
2. [Development phases](#2-development-phases)
3. [Architecture](#3-architecture)
4. [Technology stack](#4-technology-stack)
5. [Local AI models](#5-local-ai-models)
6. [Resource requirements — server](#6-resource-requirements--server)
7. [Resource requirements — client](#7-resource-requirements--client)
8. [Installation & setup](#8-installation--setup)
9. [Configuration reference](#9-configuration-reference)
10. [Using the workbench](#10-using-the-workbench)
11. [API reference](#11-api-reference)
12. [Model routing](#12-model-routing)
13. [Conversation context](#13-conversation-context)
14. [Documents & OCR pipeline](#14-documents--ocr-pipeline)
15. [Response reliability (hallucination reduction)](#15-response-reliability-hallucination-reduction)
16. [Monitoring: usage dashboard, system status & model health](#16-monitoring-usage-dashboard-system-status--model-health)
17. [Security & privacy](#17-security--privacy)
18. [Testing](#18-testing)
19. [Research & experimental findings](#19-research--experimental-findings)
20. [Limitations & roadmap](#20-limitations--roadmap)
21. [Operations & troubleshooting](#21-operations--troubleshooting)
22. [Repository structure](#22-repository-structure)
23. [References](#23-references)

---

## 1. What it does

### General Chat
- ChatGPT/Claude-style interface: sidebar with conversation history, search, rename, delete,
  collapsible sidebar (top-left toggle, `Ctrl/⌘+Shift+S`), light/dark/system theme.
- **Automatic model routing** — a deterministic router picks the right local model per request
  (general reasoning → Qwen3, coding → Qwen2.5-Coder, images → Qwen2.5-VL). Manual model
  selection is also available.
- **Streaming answers** (token by token), Markdown rendering (headings, lists, tables, quotes),
  code blocks with syntax highlighting and a *Copy* button, *Copy* / *Regenerate* per answer.
- **Images:** attach up to 3 PNG/JPEG images per message; click to enlarge. Follow-up questions
  can refer to earlier images ("Which component is the largest?").
- **OCR in chat:** an image of a document with a text task ("summarise this report") is read with
  local OCR and answered by the text model; visual questions go to the vision model; mixed
  requests send both the image and its OCR text to the vision model.
- Backend-held conversation history — the browser only remembers which conversation is open.

### Document Assistant
- Upload **PDF, TXT, PNG, JPG** (max 15 MB). Digital PDFs use their text layer; scanned pages
  and images are read with **local PaddleOCR** (page-orientation correction, optional OCR
  language, table/multi-column layout warning).
- Ask questions (with conversation history, streaming, regenerate), generate an executive
  summary, export a Word (`.docx`) report.
- Visual questions about a PDF ("what does the drawing on page 3 show?") send the named pages
  (max 2) to the vision model.
- Limits (characters, pages, OCR pages) are configurable and reported in the UI.

### Dashboard
- **Usage dashboard** — total/successful/failed/today's queries, usage per model, routing
  distribution (General / Coding / Vision). Real database counts, never sample values.
- **System status** — Django backend, Ollama, OCR engine.
- **Model health** — each model Ready/Unavailable, capability, size, whether it is currently in
  GPU memory, last successful use. Checks are lightweight: **no model is loaded and no inference
  is run.**

### Reliability layer
- Central reliability instructions for every model (general / document / OCR text / vision /
  coding modes).
- Each answer shows what it was based on — *Based on uploaded document · file.pdf*, *Based on
  provided image*, *General AI response*, *Generated code — not executed*, or a warning such as
  *Not found in the provided document*. **This indicates the source of the answer, not that it is
  correct.**

---

## 2. Development phases

| Phase | Scope | Key commit |
|---|---|---|
| Phase 1 | Local chat: React → Django → Ollama (single model) | `71cfd92` |
| Phase 2 | Document Assistant: PDF/TXT upload, Q&A, summary, DOCX export | `71cfd92` |
| Step 7 | Multi-model layer: model registry, model manager, manual model selector | `361bb23` |
| Step 8 | Deterministic model routing; execution abstraction; local-only endpoint guard | `dcbb071` |
| Step 9 | Multimodal image input to Qwen2.5-VL | `361bb23` / `dcbb071` |
| Step 10 | Local OCR (PaddleOCR) for scanned PDFs and images | `dcbb071` |
| Phase A | Stability & safety: image limits, 8k context window, LAN allowlist, limits, cleanup | `4d8c1ab` |
| Phase B | Routing rules: phrases, negatives, visual targets, priorities | `d6aa671` |
| Phase C | Backend conversation context for chat and document Q&A | `8c11698` |
| Phase D | OCR profiles, orientation correction, languages, layout warnings, benchmark | `c157789` |
| Phase E | OCR vs vision decision for chat images; multi-page PDF vision | `c5398f3` |
| UI 1 | Modern assistant UI: sidebar, Markdown, code blocks, message actions | `03dce2e` |
| UI 2 | Streaming, dark mode, search, upload progress, bundle splitting, accessibility | `248e08d` |
| UI 3 | Collapsible sidebar with top-left toggle | `27c67d3` |
| Reliability & monitoring | Usage dashboard, system status + model health, reliability layer | `8e576f2` |

---

## 3. Architecture

### 3.1 System context

```mermaid
flowchart LR
    subgraph LAN["Company LAN (no internet access needed at runtime)"]
        U1["User browser<br/>(any LAN PC)"]
        subgraph SRV["AI server / workstation"]
            V["Vite dev server :5173<br/>(or static build)"]
            D["Django + DRF :8000"]
            DB[("SQLite<br/>db.sqlite3")]
            M[("media/<br/>uploads & chat images")]
            O["Ollama :11434<br/>(loopback only)"]
            G["GPU 8 GB<br/>one model at a time"]
            P["PaddleOCR<br/>(CPU, in Django process)"]
        end
    end
    U1 -- "HTTP (UI, /api, /media)" --> V
    V -- "proxy /api, /media" --> D
    D --> DB
    D --> M
    D -- "HTTP, local-only check" --> O
    O --> G
    D --> P
    X["External / cloud AI APIs"]
    D -. "never called" .-> X
```

### 3.2 Backend layers

The backend keeps **model selection**, **model execution**, **context**, **document processing**,
**reliability** and **monitoring** in separate modules so each can be replaced independently.

```mermaid
flowchart TB
    subgraph API["API layer (Django REST Framework views)"]
        CV["chat/views.py<br/>/api/chat, /stream, /conversations"]
        DV["documents/views.py<br/>/api/documents/..."]
        MV["monitoring/views.py<br/>/api/dashboard/..."]
    end
    CTX["chat/context.py<br/>Context manager<br/>(bounded history, earlier images)"]
    RT["chat/router.py + routing_rules.py<br/>Model router (deterministic rules)"]
    REL["chat/reliability.py<br/>Reliability instructions + answer basis"]
    PROC["documents/processing.py<br/>Document processor"]
    OCR["documents/ocr.py<br/>PaddleOCR (CPU)"]
    EXT["documents/extractors.py<br/>PyMuPDF text layer / TXT"]
    MM["chat/model_manager.py<br/>Execution layer (only code that calls Ollama)"]
    REG["chat/model_registry.py<br/>Model registry"]
    IMG["chat/images.py<br/>Image safety (resize, limits)"]
    USE["monitoring/usage.py<br/>Usage records"]
    HLTH["monitoring/health.py<br/>Health checks (metadata only)"]
    OL["Ollama"]

    CV --> CTX --> RT
    CV --> REL
    CV --> PROC --> OCR
    DV --> EXT --> OCR
    DV --> RT
    DV --> REL
    DV --> PROC
    CV --> MM
    DV --> MM
    CV -. validate .-> IMG
    RT --> REG
    MM --> REG
    MM --> USE
    MM --> OL
    MV --> USE
    MV --> HLTH --> OL
```

| Module | Responsibility | Never does |
|---|---|---|
| `chat/router.py`, `routing_rules.py` | Decide **which** model (rules are data in `routing_rules.py`) | HTTP, Ollama calls |
| `chat/model_manager.py` | **How** to call Ollama: payload, `num_ctx`, thinking flag, streaming, timeouts, local-only check, errors, usage recording | Routing decisions |
| `chat/context.py` | Conversation history within the context-window budget; re-send the latest images to the vision model only | Model calls |
| `chat/reliability.py` | Reliability instructions per mode; answer basis indicator | Routing, model calls |
| `documents/ocr.py` | Images/PDF pages → text (PaddleOCR on CPU) | Any model/Ollama logic |
| `documents/processing.py` | OCR for chat images, PDF page rendering, page selection | Model selection |
| `monitoring/*` | Usage aggregation, health checks | Inference, model loading |

### 3.3 Chat request flow (streaming)

```mermaid
sequenceDiagram
    participant B as Browser (React)
    participant V as ChatStreamAPIView
    participant C as Context manager
    participant R as Router
    participant P as Document processor / OCR
    participant L as Reliability layer
    participant M as Model manager
    participant O as Ollama
    B->>V: POST /api/chat/stream/ {message, images?, conversation_id?}
    V->>V: validate, resize images (chat/images.py)
    V->>C: load conversation, context signals (earlier image? last route?)
    V->>R: route_model(message, has_images, context)
    alt visual request without any image
        V-->>B: JSON {needs_image: true} (no model called)
    end
    opt ocr_text / vision_ocr route
        V->>P: OCR attached images (local PaddleOCR)
    end
    V->>L: system prompt for mode (general/coding/vision/image_text)
    V->>C: build bounded message history (+ reused image for VL)
    V->>M: chat_stream(model, messages, usage)
    M->>O: POST /api/chat (stream=true, num_ctx=8192)
    Note over M,O: connection / missing-model / GPU OOM errors<br/>return plain JSON errors before streaming starts
    M-->>B: NDJSON start → thinking → delta … delta
    M->>M: record usage (success / failure / disconnect)
    V->>C: store user turn (+images, OCR text) and answer (+basis)
    V-->>B: NDJSON done {response, model, routing, basis, context, ...}
```

The non-streaming endpoint `POST /api/chat/` uses the same preparation (`prepare_turn`) and
persistence (`finish_turn`) steps and returns one JSON object.

### 3.4 Document pipeline

```mermaid
flowchart TD
    UP["Upload PDF / TXT / PNG / JPG"] --> VAL["Validate type, signature, size (15 MB)"]
    VAL --> T{File type}
    T -- TXT --> TXT["Decode UTF-8 / Latin-1"]
    T -- PNG/JPG --> OCRI["PaddleOCR image<br/>(orientation correction)"]
    T -- PDF --> PG{"Each page:<br/>text layer ≥ 20 chars?"}
    PG -- yes --> TL["PyMuPDF text"]
    PG -- no --> RND["Render page 200 dpi"] --> OCRP["PaddleOCR page<br/>(max OCR_MAX_PDF_PAGES)"]
    TXT & OCRI & TL & OCRP --> JOIN["Combine (page markers when OCR used)<br/>layout check · confidence · limits"]
    JOIN --> STORE[("Document row + file in media/")]
    STORE --> Q["Question"] --> RQ["Router (image available = PDF/image doc)"]
    RQ -- "text question" --> TXTQ["qwen3 · document text fitted to context window<br/>+ document reliability mode"]
    RQ -- "visual question" --> VIS["qwen2.5vl · named pages rendered ≤1024 px (max 2)<br/>+ vision reliability mode"]
    RQ -- "coding question" --> COD["qwen2.5-coder · document text"]
```

### 3.5 Data model

```mermaid
erDiagram
    Document ||--o{ Conversation : "Q&A conversations"
    Conversation ||--o{ ChatMessage : contains
    ChatMessage ||--o{ ChatAttachment : "user images"
    Document {
        int id
        file file
        string original_name
        string file_type "PDF/TXT/PNG/JPG"
        text extracted_text
        string extraction_method "text/ocr/text+ocr"
        int page_count
        int ocr_pages
        int ocr_pages_skipped
        float ocr_confidence
        string ocr_lang
        bool complex_layout
        bool truncated
        int original_chars
    }
    Conversation {
        uuid id
        string title
        fk document "null for chat"
        datetime updated_at
    }
    ChatMessage {
        string role "user/assistant"
        text content
        string model
        string routing_reason
        text extra_context "OCR text, model-only"
        string basis "document/image/image_text/general/code"
        string basis_detail
        bool basis_undetermined
    }
    ChatAttachment {
        file file
        int width
        int height
    }
    UsageRecord {
        string model
        string category "general/coding/vision"
        string reason
        string source "chat/document/summary"
        bool success
        string error_type
        int duration_ms
        bool streamed
        datetime created_at
    }
```

`UsageRecord` is deliberately **not linked** to conversations and stores **no content**.

---

## 4. Technology stack

### 4.1 Backend (Python 3.12)

| Component | Version | Purpose |
|---|---|---|
| Django | 6.1.1 | Web framework, ORM, migrations, admin, management commands, system checks |
| Django REST Framework | 3.18.1 | REST API views, serializers, validation |
| django-cors-headers | 4.9.0 | CORS for LAN clients |
| python-dotenv | 1.2.3 | `.env` configuration |
| requests | 2.34.2 | HTTP client to Ollama (proxy env vars ignored, redirects refused) |
| PyMuPDF (`pymupdf`) | 1.28.2 | PDF text extraction, page rendering, image decoding |
| PaddleOCR | 3.7.0 | OCR pipeline (text detection + recognition + orientation) |
| PaddlePaddle (CPU) | 3.3.1 | Inference runtime for PaddleOCR (oneDNN disabled, see §19) |
| NumPy | 2.3.5 | Image arrays for OCR, layout heuristic |
| Pillow | 12.3.0 | Image validation/resizing (decompression-bomb protection, EXIF orientation) |
| python-docx | 1.2.0 | Word report export |
| SQLite | bundled | Database (development / single-server deployment) |

### 4.2 AI runtime

| Component | Version | Purpose |
|---|---|---|
| Ollama | 0.33.3 | Local model server: model storage, GPU scheduling, `/api/chat`, `/api/generate`, streaming |
| Qwen3 8B | `qwen3:8b` (Q4_K_M) | General reasoning, document Q&A, summaries, OCR-text answers |
| Qwen2.5-Coder 7B | `qwen2.5-coder:7b` | Code generation / explanation |
| Qwen2.5-VL 7B | `qwen2.5vl:7b` | Image and visual document understanding |
| PP-OCRv6 (medium) det/rec | PaddleX official models | Default OCR models (`OCR_MODEL_PROFILE=server`) |
| PP-OCRv5 mobile det / en rec | PaddleX official models | Optional faster OCR profile (`mobile`) |
| PP-LCNet_x1_0_doc_ori | PaddleX official models | Page orientation correction (on by default) |

### 4.3 Frontend

| Component | Version | Purpose |
|---|---|---|
| React / React DOM | 18.3.1 | UI |
| Vite | 5.4.x | Dev server (with `/api` and `/media` proxy) and production build |
| react-markdown | 9.1.0 | Markdown rendering of answers (raw HTML is **not** rendered) |
| remark-gfm | 4.0.1 | GitHub-flavoured Markdown: tables, strikethrough, task lists |
| lowlight + highlight.js | 3.3.0 / 11.11.2 | Syntax highlighting with a curated set of ~20 languages (custom rehype plugin) |
| lucide-react | 0.475.0 | Icons |
| Node.js (build tool only) | 18.19 | `npm install` / `vite build` — not needed on clients |

No UI framework, CSS framework, state library or CDN is used: styling is plain CSS with design
tokens (`index.css`) and a dark theme; all assets are bundled locally.

### 4.4 Development & verification tools

| Tool | Use |
|---|---|
| Django test runner | 138 backend tests (Ollama and OCR mocked where appropriate) |
| Headless Google Chrome + Chrome DevTools Protocol | Live end-to-end UI verification (streaming, copy, images, sidebar, dashboard, console errors) |
| axe-core 4 | Automated accessibility audit (WCAG 2.x rules) in light and dark themes |
| `samples/ocr_benchmark.py` | OCR accuracy/speed/memory benchmark on generated test scans |

---

## 5. Local AI models

The registry (`backend/chat/model_registry.py`) is the single source of truth. Adding a model =
`ollama pull <name>` + one `LocalModel(...)` entry.

| Registry id | Ollama tag | Capability | Modality | Used for | Size on disk |
|---|---|---|---|---|---|
| `qwen3` | `qwen3:8b` | reasoning | text | General chat, document Q&A, summaries, OCR text of chat images | 5.2 GB |
| `qwen-coder` | `qwen2.5-coder:7b` | coding | text | Code generation / debugging | 4.7 GB |
| `qwen-vl` | `qwen2.5vl:7b` | vision | multimodal | Images, visual PDF questions, image + OCR requests | 6.0 GB |

- **Sequential loading:** only one model is resident in the 8 GB GPU at a time. Ollama unloads an
  idle model when another is requested; a model switch costs ~12–16 s. The workbench never
  preloads models.
- **Context window:** every request sets `num_ctx=8192` (Ollama's default is 4096, which silently
  truncates longer prompts — see §19).
- **Qwen3 "thinking":** Qwen3 reasons before answering; the reasoning text is never shown or
  stored. `OLLAMA_THINK=false` makes answers much faster (see §19) at the cost of less
  step-by-step reasoning.

Verify installation at any time:

```bash
cd backend && ../env/bin/python manage.py check_local_models
```

---

## 6. Resource requirements — server

The server runs Django, Ollama (GPU) and PaddleOCR (CPU). Values below were **measured on the
development machine** unless marked as recommendations.

### 6.1 Reference hardware (development / tested)

| Resource | Development machine |
|---|---|
| OS | Ubuntu 24.04.4 LTS (Linux 7.0 kernel) |
| CPU | Intel Core i5-14450HX, 16 threads |
| RAM | 16 GB |
| GPU | NVIDIA GeForce RTX 5050 Laptop GPU, 8 GB VRAM (driver 595.84) |
| Disk | NVMe SSD |

### 6.2 Recommended minimum

| Resource | Minimum | Recommended | Why |
|---|---|---|---|
| GPU | NVIDIA, 8 GB VRAM | 12–16 GB+ | 8 GB fits one model at an 8k context; more VRAM allows larger context or concurrency |
| RAM | 16 GB | 32 GB | Ollama host memory + Django + OCR engine (~1 GB resident, 3.5 GB peak) |
| CPU | 8 threads | 16+ threads | OCR runs on CPU (`OCR_CPU_THREADS=8`) |
| Disk | 25 GB free | 50 GB+ SSD | Models, Python environment, uploads |
| OS | Linux (tested) | Ubuntu 22.04/24.04 | Ollama + PaddlePaddle wheels |

### 6.3 Disk usage

| Item | Size |
|---|---|
| Ollama models (3 models) | ~15 GB (`/usr/share/ollama/.ollama/models`) |
| PaddleOCR / PaddleX model files | ~170 MB (`~/.paddlex/official_models`, downloaded once) |
| Python virtual environment (`env/`) | ~1.5 GB (PaddlePaddle is the largest) |
| `frontend/node_modules` (build machine only) | ~116 MB |
| Production frontend build (`frontend/dist`) | ~0.5 MB |
| Database + uploads | grows with use (uploads ≤ 15 MB each; chat images ≤ 1024 px) |

### 6.4 GPU memory (measured, Ollama 0.33.3)

| Scenario | GPU memory |
|---|---|
| qwen3:8b, `num_ctx` 4096 | 5.2 GB model, ~5.4 GB GPU total (5,532 MiB) |
| qwen3:8b, `num_ctx` 8192 (default here) | 5.8 GB model, ~6.0 GB GPU total (6,112 MiB) — fully on GPU |
| qwen3:8b, `num_ctx` 16384 | 7.3 GB, **partly offloaded to CPU** (only 6.4 GB on GPU) |
| qwen2.5vl:7b, 1–3 images of 1024 px, `num_ctx` 8192 | 5.3 GB model, ~6.8 GB GPU total (6,952 MiB of 8,151) |
| qwen2.5vl:7b with one raw 3840×2160 image (before backend resizing) | **CUDA out of memory** |
| System status / model health check | **no change** (metadata calls only) |

### 6.5 CPU / RAM (Django process, measured)

| State | RSS |
|---|---|
| Django idle | ~107 MB |
| After first OCR (engine stays loaded) | ~970 MB |
| Peak during 2-page PDF OCR at 200 dpi | ~3.5 GB |

### 6.6 Network & ports

| Port | Service | Exposure |
|---|---|---|
| 8000 | Django (API, `/media` in DEBUG) | LAN (bind `0.0.0.0`) or loopback |
| 5173 | Vite dev server (development) | LAN |
| 11434 | Ollama | **Loopback only** recommended; if on another LAN host it must be listed in `OLLAMA_ALLOWED_HOSTS` |

- **Internet access** is only needed once, to download Python/npm packages, Ollama models and
  PaddleOCR model files. At runtime the system works fully offline (verified by running OCR in a
  network namespace with no network).
- For an air-gapped server copy `~/.paddlex/official_models`, the Ollama models directory, the
  Python wheels and the built frontend from a connected machine.

---

## 7. Resource requirements — client

Clients are ordinary PCs on the LAN. **No model or OCR runs on the client.**

| Resource | Requirement |
|---|---|
| Browser | Current Chrome, Edge, Firefox or Safari (uses `fetch` streaming, `ReadableStream`, CSS custom properties) |
| CPU / RAM | Any office PC; the page uses tens of MB of memory |
| GPU | Not required |
| Network | HTTP access to the server (port 5173 in development, or the web server in production). No external requests: no CDNs, web fonts or analytics |
| Download size | Initial JS **~180 KB (58 KB gzipped)** + CSS ~31 KB; the Markdown renderer (~81 KB gz), Document Assistant (~8 KB gz) and Dashboard (~3 KB gz) load on first use |
| Local processing | Images are resized in the browser (canvas) to ≤1024 px before upload — the backend enforces this limit again |
| Browser storage | `localStorage` keys `mrpl.chat.conversationId` (open conversation), `mrpl.theme`, `mrpl.sidebar.collapsed` — conveniences only; all conversation content lives on the server |
| Clipboard | Copy buttons use the Clipboard API; on plain-HTTP LAN deployments a fallback is used |
| Accessibility | Keyboard navigation, focus rings, ARIA labels, WCAG AA contrast; axe-core audit clean |

---

## 8. Installation & setup

### 8.1 Prerequisites (server)

- Linux with NVIDIA driver + CUDA-capable GPU
- [Ollama](https://ollama.com/download) installed and running
- Python 3.12, Node.js 18+ (for building the frontend)

### 8.2 Pull the local models

```bash
ollama pull qwen3:8b
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5vl:7b
ollama list
```

### 8.3 Backend

```bash
cd /path/to/Dj
python3.12 -m venv env
env/bin/pip install -r requirements.txt          # includes PaddlePaddle (CPU) and PaddleOCR
cp .env.example .env                             # then edit values (see §9)
cd backend
../env/bin/python manage.py migrate
../env/bin/python manage.py check                # warns about legacy/unsafe settings
../env/bin/python manage.py check_local_models   # verifies the three models are installed
../env/bin/python manage.py runserver 0.0.0.0:8000
```

The first OCR request downloads PaddleOCR model files (~170 MB) into `~/.paddlex` — do this once
while online, or copy the folder for offline servers.

### 8.4 Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api and /media to :8000)
```

Production build (static files served by any web server that proxies `/api` and `/media` to
Django):

```bash
npm run build        # outputs frontend/dist/
```

### 8.5 Open the app

- On the server: <http://localhost:5173>
- From another LAN PC: `http://<server-ip>:5173`

---

## 9. Configuration reference

All settings are environment variables (read from `.env` in the project root or `backend/`).
See `.env.example` for a ready template.

### Core / network

| Variable | Default | Meaning |
|---|---|---|
| `DEBUG` | `True` | Django debug mode (**set `False` in production**) |
| `SECRET_KEY` | insecure dev key | **Must be changed for any shared deployment** |
| `ALLOWED_HOSTS` | `*` | Django allowed hosts |
| `CORS_ALLOWED_ORIGINS` | — | Comma-separated origins (CORS currently allows all origins) |

### Ollama & models

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama address |
| `OLLAMA_ALLOWED_HOSTS` | *(empty)* | Private-LAN hosts/IPs/CIDRs allowed for `OLLAMA_URL` (loopback always allowed; public and link-local always refused) |
| `DEFAULT_CHAT_MODEL` | `qwen3` | Model id used when none is resolved |
| `OLLAMA_TIMEOUT` | `300` | Seconds per model request |
| `OLLAMA_NUM_CTX` | `8192` | Context window per request |
| `OLLAMA_THINK` | *(empty)* | Qwen3 thinking: empty = model default (on), `false` = off (faster), `true` = force on |
| `RELIABILITY_INSTRUCTIONS` | `true` | Add reliability instructions to every model's system message |
| `CHAT_SYSTEM_PROMPT` | formatting guidance | Extra system text for General Chat (empty = none) |

### Conversation & images

| Variable | Default | Meaning |
|---|---|---|
| `CONTEXT_MAX_MESSAGES` | `12` | Earlier messages sent with each request (within the context budget) |
| `CONTEXT_IMAGE_TURNS` | `8` | How many recent messages an earlier image stays available for follow-ups |
| `VISION_MAX_SIDE` | `1024` | Longest side of images sent to the vision model |
| `VISION_MAX_INPUT_PIXELS` | `50000000` | Reject larger images before decoding |
| `MAX_IMAGES_PER_MESSAGE` | `3` | Images per chat message |
| `VISION_MAX_PDF_PAGES` | `2` | PDF pages the vision model sees per question |

### Documents & OCR

| Variable | Default | Meaning |
|---|---|---|
| `DOCUMENT_MAX_CHARS` | `50000` | Characters kept from a document (reported when truncated) |
| `DOCUMENT_MAX_PDF_PAGES` | `300` | PDFs with more pages are rejected |
| `OCR_MAX_PDF_PAGES` | `20` | Scanned pages OCR'd per PDF (skipped pages are reported) |
| `OCR_PDF_DPI` | `200` | Render resolution for scanned PDF pages |
| `OCR_LANG` | `en` | Default OCR language |
| `OCR_ALLOWED_LANGS` | `OCR_LANG` | Languages users may pick per upload (`en,hi,mr,ka,ta,te,ml,ch,latin`) — each downloads its model once |
| `OCR_MODEL_PROFILE` | `server` | `server` (most accurate) or `mobile` (~3× faster on CPU) |
| `OCR_DET_MODEL` / `OCR_REC_MODEL` | *(empty)* | Explicit PaddleOCR model names (override the profile) |
| `OCR_USE_DOC_ORIENTATION` | `true` | Page-orientation correction (fixes rotated scans) |
| `OCR_USE_TEXTLINE_ORIENTATION` | `false` | Text-line orientation (did not help in tests) |
| `OCR_USE_UNWARPING` | `false` | Document unwarping for photographed curved pages (not evaluated) |
| `OCR_CPU_THREADS` | `8` | CPU threads for OCR |

Legacy variables `OLLAMA_MODEL` and `ALLOW_EXTERNAL_AI` are **no longer used**; `manage.py check`
warns if they are set. There is no cloud-AI option.

---

## 10. Using the workbench

### Chat
- Type a question and press **Enter** (Shift+Enter = new line). The model picker shows **Auto**
  (router decides) or a specific model.
- 📎 attaches up to 3 PNG/JPEG images. Click a sent image to enlarge it (Esc closes).
- Each answer shows *MRPL Local AI · model · routing* and a basis indicator; hover the routing
  label to see why the router chose that model. Use **Copy** or **Regenerate** under the answer.
- Sidebar: **New chat**, search (titles and message text), rename ✎, delete 🗑, Chat / Document
  Assistant / Dashboard, theme toggle (bottom), collapse button (top). Shortcut `Ctrl/⌘+Shift+S`.

### Document Assistant
1. Upload a PDF, TXT, PNG or JPG (drag & drop). Progress shows *Uploading %* → *Processing* →
   *Ready*. Scanned pages take ~20 s each.
2. Warnings appear for truncated text, skipped OCR pages, tables/multi-column layouts and low OCR
   recognition confidence.
3. **Document Q&A** — ask questions; say "page 3" to make the vision model look at a page.
4. **AI Executive Summary**, **Extracted Text** (copyable) and **Export DOCX**.
5. Q&A conversations appear in the sidebar with a file icon.

### Dashboard
- **Refresh** reloads usage statistics; **Check Status** re-runs the health checks. Nothing is
  polled automatically.

---

## 11. API reference

Base URL: `http://<server>:8000`. All bodies are JSON unless stated. There is **no
authentication** yet (see §17).

### 11.1 Chat

#### `POST /api/chat/` — one answer (JSON)

Request:

```json
{
  "message": "Write a Python function to calculate factorial.",
  "model": "auto",
  "images": ["<base64 or data: URL>"],
  "conversation_id": "optional-uuid",
  "regenerate": false
}
```

| Field | Notes |
|---|---|
| `message` | Required unless `regenerate` is true |
| `model` | `auto` (default, router decides) or `qwen3` / `qwen-coder` / `qwen-vl` |
| `images` | 0–3 PNG/JPEG, ≤10 MB each; resized server-side to ≤1024 px |
| `conversation_id` | Continue a conversation; unknown/omitted → new conversation |
| `regenerate` | Re-run the last question of `conversation_id`; the old answer is replaced only on success |

Response (success):

```json
{
  "success": true,
  "conversation_id": "…",
  "response": "…markdown…",
  "model": "qwen-coder",
  "ollama_model": "qwen2.5-coder:7b",
  "routing": {"mode": "auto", "reason": "coding", "explanation": "coding request"},
  "context": {"history_messages_used": 2, "history_messages_available": 2, "history_truncated": false, "reused_images": 0},
  "basis": {"type": "code", "label": "Generated code — not executed", "detail": "", "undetermined": false},
  "ocr": null,
  "images": [],
  "duration_ms": 12913,
  "context_overflow": false,
  "external_api": false
}
```

Special reply when a visual request has no image (no model is called):

```json
{"success": true, "needs_image": true, "response": "This looks like a request about an image, but no image is attached. …", "model": null}
```

Errors: `400` validation · `503` Ollama unavailable / model not installed / GPU out of memory /
misconfigured endpoint / OCR failure · `504` timeout · `502` other model errors. Error bodies
contain a short message only — no stack traces or internal addresses.

#### `POST /api/chat/stream/` — streaming answer (NDJSON)

Same request body. Response `Content-Type: application/x-ndjson`, one JSON object per line:

```text
{"type": "start", "conversation_id": "…", "routing": {…}, "ollama_model": "qwen3:8b", "ocr": null, "images": []}
{"type": "thinking"}
{"type": "delta", "text": "Federated "}
{"type": "delta", "text": "learning …"}
{"type": "done", …same fields as the JSON endpoint…}
```

or a final `{"type": "error", "error": "…"}`. Errors that occur **before** generation starts and
the `needs_image` reply are returned as normal JSON. The turn is stored only when the stream
completes.

#### `POST /api/chat/route/` — routing decision only (no inference)

```json
{"message": "Analyze this P&ID", "images": []}
```

Returns `model`, `model_id`, `reason`, `requires_image`, `ocr`, `explanation`, `signals`,
`matched`.

#### Conversations

| Method & path | Description |
|---|---|
| `GET /api/chat/conversations/` | Up to 50 most recent conversations with messages. Query: `scope=all` (include Document Q&A), `document=<id>`, `q=<text>` (searches titles **and** message text) |
| `GET /api/chat/conversations/<uuid>/` | Messages (role, content, model, routing_reason, images URLs, basis) |
| `PATCH /api/chat/conversations/<uuid>/` | Rename: `{"title": "…"}` |
| `DELETE /api/chat/conversations/<uuid>/` | Delete conversation, messages and stored images |

#### `GET /api/models/`

Registered models (`id`, `name`, `ollama_name`, `capability`, `modality`, `supports_images`),
the default model and limits (`max_images_per_message`, `vision_max_side`).

### 11.2 Documents

| Method & path | Description |
|---|---|
| `GET /api/documents/` | List documents |
| `POST /api/documents/upload/` | Multipart: `file` (PDF/TXT/PNG/JPG ≤15 MB), optional `ocr_lang`. Returns the document incl. `extraction_method`, `ocr_pages`, `ocr_confidence`, `page_count`, `ocr_pages_skipped`, `truncated`, `complex_layout`, `limits` |
| `GET /api/documents/ocr-config/` | Allowed OCR languages and default |
| `GET /api/documents/<id>/` | Document detail incl. extracted text |
| `DELETE /api/documents/<id>/` | Delete document, file and its Q&A conversations |
| `POST /api/documents/<id>/ask/` | `{"question": "…", "conversation_id": "…", "regenerate": false}` → `answer`, `model`, `ollama_model`, `routing`, `context`, `basis`, `vision_pages`, `page_count`, `conversation_id` |
| `POST /api/documents/<id>/ask/stream/` | Streaming variant (same NDJSON events; `done` carries `answer`) |
| `POST /api/documents/<id>/summary/` | Executive summary (`summary`, `model`, `basis`, `context`) |
| `POST /api/documents/<id>/generate-report/` | `{"summary": "…"}` → `.docx` file download |

### 11.3 Dashboard

| Method & path | Description |
|---|---|
| `GET /api/dashboard/usage/?tz_offset=<minutes>` | `total_queries`, `successful_queries`, `failed_queries`, `today` (viewer's local day; `tz_offset` = browser `getTimezoneOffset()`), `models` {tag: count}, `model_details` (per model incl. `last_success`), `routing` {general, coding, vision}, `sources`, `first_recorded` |
| `GET /api/dashboard/status/` | `services.backend/ollama/ocr` with `state` (`ready`/`unavailable`), `label`, `reason`; `models[]` with `state`, `capability_label`, `size_bytes`, `loaded`, `vram_bytes`, `last_success` |

### 11.4 Admin

`/admin/` — Django admin (conversations, usage records). Create a user with
`manage.py createsuperuser`.

---

## 12. Model routing

Deterministic, rule-based routing (no LLM, no embeddings). Rules are data in
`backend/chat/routing_rules.py`; the decision logic is `backend/chat/router.py`.

### Decision order (first match wins)

```mermaid
flowchart TD
    A["Request"] --> B{"Image attached?"}
    B -- yes --> B1{"Text task only<br/>(summarise, transcribe, list findings)?"}
    B1 -- yes --> R1["ocr_text → OCR → qwen3"]
    B1 -- no --> B2{"Text task + visual question?"}
    B2 -- yes --> R2["vision_ocr → image + OCR text → qwen2.5vl"]
    B2 -- no --> R3["vision → qwen2.5vl"]
    B -- no --> C{"Earlier image available<br/>and message refers to it?"}
    C -- yes --> R3
    C -- no --> D{"Explicit visual target<br/>('this drawing', 'in the image')?"}
    D -- yes --> R4["requires_image → ask user to attach an image<br/>(no model call)"]
    D -- no --> E{"Coding signal?"}
    E -- yes --> R5["coding → qwen2.5-coder"]
    E -- no --> R6["general_reasoning → qwen3"]
```

### Signals

| Signal | Examples |
|---|---|
| Strong coding | code fences, tracebacks, `SyntaxError`, "fix my script", "write a function", language names (Python, SQL, C++…), file names (`app.py`) |
| Weak coding (need a second signal or a code verb) | code, function, class, program, error, bug, loop |
| Negative phrases (neutralise keywords) | "training program", "human error", "margin of error", "drawing conclusions", "ASME code", "function of a valve", rust (corrosion), "react with water" |
| Visual target | "this P&ID", "the attached photo", "in the image", "analyze this drawing" |
| Visual properties (only with an image in scope) | colour, shape, position, size, left/right, above/below, appearance, damage |
| Follow-up markers | it, this, which component, the largest… |

Manual model selection bypasses the router (`routing.reason = "manual"`).

Verified examples: "Explain what a P&ID is" → qwen3 · "fix my script" → Coder · "Design a
training program" → qwen3 · "Analyze this engineering drawing" without image → *attach an image*
· image + "write Python to extract the detected objects" → VL · "What colour is the pipe?" →
qwen3 without an image, VL with one.

---

## 13. Conversation context

- Conversations, messages and chat images are stored on the server (`Conversation`,
  `ChatMessage`, `ChatAttachment`); images live under `media/chat/`.
- For each request the context manager sends the most recent messages (max
  `CONTEXT_MAX_MESSAGES`) that fit in **¾ of the context window** (the rest is left for the answer).
- Only the **vision model** receives images, and only the most recent set. Text models see a
  placeholder `[user attached N image(s)]` plus any stored OCR text.
- OCR text of chat images is stored with the user message (`extra_context`) so follow-up questions
  can use it; it is not shown in the UI.
- Document Q&A conversations are linked to their document; the document text is placed in the
  system message and trimmed to leave a quarter of the budget for history.

---

## 14. Documents & OCR pipeline

- **Text layer first:** PDF pages with ≥20 characters of text use PyMuPDF; only scanned pages
  are OCR'd (mixed PDFs are supported, `extraction_method = text+ocr`).
- **OCR engine:** PaddleOCR on CPU (keeps the GPU free for Ollama), engine loaded once per
  language and reused; access is serialised with a lock.
- **Orientation correction** (PP-LCNet doc orientation) is on by default.
- **Layout heuristic:** rows with several text boxes separated by wide gaps (≥3 rows, ≥30 % of
  rows) mark the document as *table / multi-column*, and the UI warns that reading order may be
  wrong.
- **Recognition confidence** is PaddleOCR's own score (mean over lines), labelled as such — it is
  not measured accuracy.
- **Model context:** the document text given to the model is trimmed to fit the context window;
  when trimmed, the answer notes how many characters the model saw.
- **Visual questions** render only the requested pages (default page 1, max 2) at ≤1024 px.

---

## 15. Response reliability (hallucination reduction)

> The reliability layer **reduces** unsupported claims. It does **not** eliminate hallucinations,
> and the indicators do **not** guarantee that an answer is correct.

### Instructions (`backend/chat/reliability.py`)

One shared **core** instruction (accuracy over confidence; do not fabricate facts, numbers,
names, measurements, components, references, citations or observations; say when information is
insufficient; separate observation from inference; explain ambiguity) plus one mode:

| Mode | Used for | Key rules |
|---|---|---|
| `general` | General questions | Answer normally (no unnecessary refusals); mark uncertainty; no invented statistics, quotations, URLs or citations |
| `document` | Document Q&A and summaries | Answer only from the document; say exactly *"I could not find this information in the provided document."* when absent; label inferences |
| `image_text` | OCR text of a chat image | Answer only from the OCR text; point out garbled values |
| `vision` | Images, visual PDF questions | Observed / Inferred / Cannot be determined; never invent manufacturer, model, measurements, capacity, certification, serial numbers, dates, hidden objects, unreadable text; *"This cannot be determined from the provided image."* |
| `coding` | Code | Never claim code was executed, tested or verified |

The router picks the model; the reliability module maps the routing reason to a mode and builds
the system message. It is separate from routing, and there is **no second model, LLM-as-judge or
confidence score**.

### Answer basis indicator

Computed in code from **what was actually sent to the model**:

| Indicator | When |
|---|---|
| ✓ Based on uploaded document · *file* | Document Q&A / summary (text path) |
| ✓ Based on uploaded document · *file — page 2 (image)* | Visual PDF question (the pages really sent) |
| ✓ Based on provided image | Image(s) sent to the vision model |
| ✓ Based on text read from the provided image (OCR) | `ocr_text` route |
| ℹ General AI response | General knowledge answers |
| ℹ Generated code — not executed | Coding answers |
| ⚠ Not found in the provided document / Cannot be determined from the provided image | A grounded answer whose opening matches a fixed list of "not available" phrases |

No page numbers are invented: text answers name the document only, because the page an answer
came from is not tracked.

---

## 16. Monitoring: usage dashboard, system status & model health

### Usage tracking
- One `UsageRecord` per model call, written by the execution layer (`chat/model_manager.py`) —
  the single path every inference takes — so chat, streaming, document Q&A and summaries are all
  counted exactly once.
- Recorded: model, category (general/coding/vision), router reason, source, success, error class
  name, duration, streamed flag, timestamp. **Not recorded:** prompts, answers, document text,
  images, OCR text.
- Failures are recorded (timeouts, Ollama unavailable, GPU OOM, interrupted streams, client
  disconnects). Requests that never reach a model (validation errors, the *attach an image* reply)
  are not counted.
- Statistics are independent of conversations (deleting a chat does not change them). Reset with
  `cleanup_dev_data --usage --all --yes`.

### Health checks (no inference, no model loading)
| Check | How |
|---|---|
| Django backend | The status endpoint responding |
| Ollama | `GET /api/version`, `/api/tags` (installed models), `/api/ps` (loaded models + VRAM), each with a 3 s timeout, through the same local-only endpoint check as inference |
| OCR engine | PaddleOCR/PaddlePaddle packages findable and model files present on disk; reports whether the engine is already loaded — the engine is **not** loaded by the check |
| Model health | Ready = installed in Ollama; Unavailable with a plain reason; plus capability, size, loaded-in-GPU state and last successful use |

"Ready" means **installed and reachable**, not that answers are good. Usage counts are request
counts, not accuracy.

---

## 17. Security & privacy

### Implemented
- **Local-only inference:** the only AI endpoint is `OLLAMA_URL`. Before every call it must
  resolve to loopback or an allow-listed private LAN address; public and link-local addresses
  (incl. `169.254.169.254`) are refused, redirects are refused, `HTTP(S)_PROXY` variables are
  ignored.
- **No cloud AI code** of any kind (no OpenAI/Anthropic/Gemini/Hugging Face inference clients).
- **Offline runtime** (after one-time model downloads).
- **Input limits:** 15 MB uploads, PNG/JPEG signature checks, 50 MP image cap before decoding,
  backend image resizing, PDF page limits, context-window fitting.
- **Model output is not rendered as HTML** (Markdown only).
- **Logging** records metadata (model, sizes, durations, routing keywords) — not prompts,
  documents or images.
- **Clean errors:** no stack traces or internal addresses in API responses.

### Not implemented (known gaps)
- **No authentication or authorisation** — anyone who can reach the server on the LAN can read
  and delete all conversations, documents and statistics.
- Development defaults: `DEBUG=True`, insecure default `SECRET_KEY`, `ALLOWED_HOSTS=*`, CORS
  allows all origins, Django `runserver` (not a production server), media served by Django.
- No encryption at rest, no retention policy, no audit log, no rate limiting, HTTP (not HTTPS).
- The Ollama allowlist is a network restriction, not complete security.

---

## 18. Testing

```bash
cd backend
../env/bin/python manage.py test chat documents monitoring      # 138 tests
```

| App | Tests | Covers |
|---|---|---|
| `chat` | 79 | API contract, routing rules (30+ cases), image safety, context/history, streaming (events, errors, disconnects, 406 regression), regenerate, rename, search, local-only endpoint rules, GPU OOM mapping, reliability instructions and basis |
| `documents` | 45 | Upload/extraction, OCR paths (mocked), limits, context fitting, visual page selection, document conversations, streaming Q&A, regenerate, grounding prompt and basis, cleanup command |
| `monitoring` | 14 | Usage recording (routes, failures, streams, disconnects, no content stored), aggregation, status/health with Ollama mocked (ready, missing model, Ollama down, misconfigured URL), OCR status |

**OCR benchmark** (real PaddleOCR on generated samples):

```bash
cd backend
../env/bin/python ../samples/make_samples.py              # regenerate samples
../env/bin/python ../samples/ocr_benchmark.py server docori mobile
```

**Live end-to-end verification** was performed with the real models through the UI (headless
Chrome driven over the DevTools protocol): streaming, Markdown and code-block copy, image preview,
follow-ups about earlier images, sidebar (search, rename, delete, collapse), dashboard counts and
persistence, system status, hallucination tests (see §19.7), mobile layout, zero console errors,
and axe-core accessibility audits in light and dark themes.

---

## 19. Research & experimental findings

Measurements from building and testing this system on the reference hardware (§6.1).

### 19.1 Ollama context window truncation
- With the default `num_ctx=4096`, a ~20,000-token prompt was cut to **exactly half the window**
  (`prompt_eval_count` 2,050) and the answer was wrong.
- Prompts that fit (e.g. 3,758 tokens in 4,096) are kept whole; once a prompt overflows, Ollama
  0.33.3 truncates it to `num_ctx/2`, dropping the start (instructions and document start).
- Decision: `num_ctx=8192` (largest size fully on the 8 GB GPU for qwen3) and the application fits
  prompts to ¾ of the window itself. Numeric text measured ~2.75 characters/token; the budget uses
  a conservative 3.0.

### 19.2 GPU memory
See §6.4. 16k context spills qwen3 to CPU; three 1024 px images on Qwen2.5-VL (~1,100 prompt
tokens each) fit at 8k; a single raw 4K image caused CUDA OOM before backend resizing was added.

### 19.3 Latency
| Measurement | Result |
|---|---|
| Model switch (load) | ~12–16 s |
| Qwen3 simple question, thinking on / off | 39.2 s / 3.3 s (same answer) |
| Streaming token interval (Coder) | ~18 ms per token, first token after model load |
| Qwen2.5-VL image description (warm) | ~2–20 s |

### 19.4 OCR benchmark (accuracy = character similarity to known text)

| Sample | server | + page orientation | + text-line orientation | mobile |
|---|---|---|---|---|
| Clean page 1 / page 2 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| Rotated 90° | **0.147** | **1.000** | 0.093 | 0.017 |
| Rotated 180° | **0.089** | **1.000** | 0.057 | 0.011 |
| Skewed 5° | 0.962 | 0.962 | 0.962 | 1.000 |
| 100 dpi / 75 dpi | 1.000 / 0.998 | 1.000 / 0.998 | 1.000 / 0.998 | 0.998 / 0.998 |
| Noisy / JPEG q15 | 0.999 / 0.999 | 0.999 / 0.999 | 0.999 / 0.999 | 0.998 / 1.000 |
| Cursive *font* (handwriting proxy) | 1.000 | 1.000 | 1.000 | 1.000 |
| Time per page | ~20 s | ~20 s | ~20 s | **~6 s** |

- Page-orientation correction fixed rotated scans at negligible cost → **on by default**.
- Text-line orientation did not help and produced **high confidence (0.996) on wrong output** →
  off.
- The mobile profile is ~3× faster with similar accuracy on these synthetic samples; the server
  profile stays default until real scans prove otherwise.
- Rotated scans without correction had recognition confidence ~0.66, which is why the UI warns
  below 0.85.
- **Kannada** sample: English model 0.15 accuracy (with misleading 0.76 confidence); Kannada model
  (`ka_PP-OCRv3_mobile_rec`) 0.77.
- Table and two-column samples were correctly flagged by the layout heuristic; PaddleOCR's table
  pipeline was evaluated but needs 26 extra packages (`paddlex[ocr]`) and was not adopted.
- PaddlePaddle 3.3 CPU with oneDNN crashed (`ConvertPirAttribute2RuntimeAttribute not support`);
  oneDNN is disabled.
- OCR ran successfully with networking disabled (`unshare -rn`), confirming offline operation.

### 19.5 Routing
The rule set is validated by 30+ table-driven test cases (see `RoutingRulesTests`), including the
false-positive cases that motivated negative phrases ("training program", "human error",
"drawing conclusions", "ASME code", "rust on the pipe").

### 19.6 Frontend
| Metric | Before | After |
|---|---|---|
| Initial JavaScript | 534 KB (164 KB gz) | **180 KB (58 KB gz)** |
| Technique | — | curated highlight.js grammars; lazy Markdown renderer, Document Assistant and Dashboard |
| Accessibility (axe-core) | contrast + landmark issues | **0 violations** (light & dark) |

Bugs found by live testing: DRF content negotiation rejected `Accept: application/x-ndjson` with
HTTP 406 (fixed with a custom negotiation class); a failed lazy chunk load unmounted the whole
app (fixed with an error boundary that falls back to plain text).

### 19.7 Hallucination tests (live, real models)

| Test | Result |
|---|---|
| Document with "Project location: Jaipur"; "What is the project budget?" | *"I could not find this information in the provided document…"* · ⚠ Not found — no budget invented |
| "What is the maximum operating temperature?" | *120°C* · ✓ Based on uploaded document |
| Crane image: "What objects are visible?" | Crane, hook, load, building, ground, sky — no manufacturer/capacity invented |
| "What is the exact manufacturer of this machine?" | *"This cannot be determined from the provided image…"* · ⚠ |
| "Write a Python function that calculates factorial." | Code, no execution claim · ℹ Generated code — not executed |
| "What is federated learning?" | Normal full answer, no refusal · ℹ General AI response |

These are single runs on synthetic inputs; they show the intended behaviour, not a measured
hallucination rate.

---

## 20. Limitations & roadmap

### Current limitations (summary)

| Area | Limitation |
|---|---|
| Security | No authentication/authorisation; development defaults; no HTTPS, encryption at rest, retention policy or audit log |
| Routing | Keyword/phrase rules; paraphrases without keywords can be misrouted; follow-up detection is heuristic; mixed image + coding requests are answered by the vision model (no VL→Coder chain) |
| Context | Bounded history, no summarisation of long conversations; token counts are estimated |
| Documents | Model sees ~17,000 characters of a long document per question (no retrieval); visual analysis limited to 2 named PDF pages; no page-level citations for text answers |
| OCR | ~20 s/page on CPU; tested on synthetic scans only; tables/columns flattened (warning only); handwriting not supported; OCR runs inside the HTTP request (no background jobs); non-English accuracy lower (Kannada 0.77) |
| Vision | Max 3 images of 1024 px; concurrency on the 8 GB GPU not tested |
| Models / GPU | One model in GPU at a time (12–16 s switch); 8k context ceiling on 8 GB; Qwen3 thinking on by default (slow) |
| UI | Regenerate only for the latest answer; search over the latest 50 results; no translation of the interface; no manual screen-reader testing; output formatting depends on the model |
| Dashboard | Counts requests, not accuracy; history starts when the feature was added; no per-user or time-series views; manual reset only |
| Health | Point-in-time checks, no polling; "Ready" = installed, not verified by inference; no GPU/driver health beyond Ollama's loaded-model data |
| Reliability | Instructions can be ignored by the model; "not found" detection is a phrase heuristic; basis ≠ correctness; general answers are not fact-checked |
| Operations | Django development server and SQLite; no deployment scripts; GitHub push currently requires repository write access |

### Roadmap (future enhancements)
- Authentication, roles, audit logging, HTTPS, production deployment (Gunicorn/Uvicorn + reverse
  proxy), data retention policies.
- Retrieval-augmented generation with a vector store and page-level citations; deterministic
  checks of numeric claims against sources; evaluation datasets.
- Semantic / learned routing; VL→Coder multi-step pipelines; agent frameworks.
- Background OCR jobs with progress; table extraction; handwriting recognition; validation on
  real plant scans.
- Sandboxed code execution so generated code can actually be tested.
- Response-time optimisation (thinking defaults, OCR mobile profile, caching) and response-format
  standardisation.
- Dashboard trends, per-user usage, GPU/driver monitoring.
- Interface translation (e.g. Kannada, Hindi).

---

## 21. Operations & troubleshooting

### Management commands

```bash
cd backend
../env/bin/python manage.py check_local_models                     # registry vs installed models
../env/bin/python manage.py cleanup_dev_data --all                 # dry run: list documents
../env/bin/python manage.py cleanup_dev_data --ids 3,4 --yes       # delete documents (+files)
../env/bin/python manage.py cleanup_dev_data --name test_ --yes    # by filename
../env/bin/python manage.py cleanup_dev_data --conversations --older-than 30 --yes
../env/bin/python manage.py cleanup_dev_data --usage --all --yes   # reset dashboard statistics
```

All cleanup commands are **dry runs unless `--yes` is given**.

### Logs
Console logging for `chat`, `documents` and `monitoring`: routing decisions, context sizes,
inference start/success/failure with durations and token counts, OCR timings. Prompt and document
content is not logged.

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Local AI server is unavailable." | Ollama not running → `systemctl status ollama` / `ollama serve`; check Dashboard → System Status |
| "The selected model is not installed…" | `ollama pull <tag>`; run `check_local_models` |
| "Local AI server is misconfigured." | `OLLAMA_URL` is public/link-local or a LAN host missing from `OLLAMA_ALLOWED_HOSTS` |
| "The local GPU ran out of memory…" | Fewer/smaller images; lower `OLLAMA_NUM_CTX`; close other GPU programs |
| First answer after switching models is slow | Model load (12–16 s) — expected with sequential loading |
| Qwen3 answers take 30–90 s | Thinking is on; set `OLLAMA_THINK=false` if speed matters more |
| Scanned upload takes minutes | OCR ~20 s/page on CPU; consider `OCR_MODEL_PROFILE=mobile`; limit with `OCR_MAX_PDF_PAGES` |
| OCR "models missing" on an offline server | Copy `~/.paddlex/official_models` from a connected machine |
| Blank answers after installing frontend packages during development | Restart Vite with `npx vite --force` (stale dependency cache) |
| `manage.py check` warns about `OLLAMA_MODEL` / `ALLOW_EXTERNAL_AI` | Remove these legacy variables from `.env` |

---

## 22. Repository structure

```text
Dj/
├── .env.example                  # configuration template (copy to .env)
├── requirements.txt              # Python dependencies
├── README.md
├── backend/
│   ├── manage.py
│   ├── config/                   # settings.py, urls.py, wsgi/asgi
│   ├── chat/
│   │   ├── model_registry.py     # local model definitions
│   │   ├── model_manager.py      # execution layer: Ollama calls, streaming, local-only check, usage recording
│   │   ├── router.py             # routing decision logic
│   │   ├── routing_rules.py      # routing rule data (phrases, negatives, visual targets)
│   │   ├── context.py            # conversation context manager
│   │   ├── reliability.py        # reliability instructions + answer basis
│   │   ├── images.py             # image validation / resizing
│   │   ├── views.py              # chat, stream, route, conversations, models endpoints
│   │   ├── serializers.py, models.py, urls.py, admin.py, checks.py, services.py
│   │   ├── management/commands/check_local_models.py
│   │   ├── migrations/
│   │   └── tests.py
│   ├── documents/
│   │   ├── extractors.py         # PDF text layer / TXT / OCR fallback, limits
│   │   ├── ocr.py                # PaddleOCR processor (CPU), layout heuristic, languages
│   │   ├── processing.py         # chat-image OCR, page rendering, page selection
│   │   ├── services.py           # document Q&A / summary (router + execution layer)
│   │   ├── generators.py         # DOCX report
│   │   ├── views.py, serializers.py, models.py, urls.py
│   │   ├── management/commands/cleanup_dev_data.py
│   │   ├── migrations/
│   │   └── tests.py
│   └── monitoring/
│       ├── models.py             # UsageRecord
│       ├── usage.py              # recording + aggregation
│       ├── health.py             # Ollama / OCR / model health (metadata only)
│       ├── views.py, urls.py, admin.py
│       ├── migrations/
│       └── tests.py
├── frontend/
│   ├── index.html, package.json, vite.config.js
│   └── src/
│       ├── main.jsx, App.jsx, index.css (design tokens, dark theme), App.css (documents)
│       ├── api/                  # chatApi.js (incl. NDJSON streaming), documentApi.js, dashboardApi.js
│       ├── components/
│       │   ├── Sidebar.jsx, Header.jsx, ChatWindow.jsx, MessageBubble.jsx, MessageInput.jsx
│       │   ├── ModelSelector.jsx, Markdown.jsx, LazyMarkdown.jsx, CopyButton.jsx, ImageLightbox.jsx
│       │   ├── documents/        # DocumentsPage, DocumentUpload, DocumentList, DocumentViewer, DocumentQuestionBox
│       │   └── dashboard/        # DashboardPage
│       ├── styles/               # shell.css, chat.css, dashboard.css
│       └── utils/                # highlight.js (curated grammars), modelLabels.js
└── samples/
    ├── make_samples.py           # generates synthetic test scans
    ├── ocr_benchmark.py          # OCR accuracy/speed/memory benchmark
    ├── scanned_inspection_report.pdf, inspection_page1.png, inspection_page2.jpg
    ├── degraded/                 # rotated, skewed, low-res, noisy, JPEG-artifact scans
    ├── layout/                   # table and two-column samples
    ├── handwriting_proxy.png     # cursive FONT (not real handwriting)
    └── kannada_notice.png
```

Not in the repository (ignored): `.env`, `env/`, `backend/db.sqlite3`, `backend/media/`,
`frontend/node_modules/`, `frontend/dist/`.

---

## 23. References

Links and versions as used during development; check the linked sources for current information.

### Models & research
1. Qwen Team. *Qwen3 Technical Report.* arXiv:2505.09388, 2025. <https://arxiv.org/abs/2505.09388>
2. Hui, B. et al. *Qwen2.5-Coder Technical Report.* arXiv:2409.12186, 2024. <https://arxiv.org/abs/2409.12186>
3. Bai, S. et al. *Qwen2.5-VL Technical Report.* arXiv:2502.13923, 2025. <https://arxiv.org/abs/2502.13923>
4. Cui, C. et al. *PaddleOCR 3.0 Technical Report.* arXiv:2507.05595, 2025. <https://arxiv.org/abs/2507.05595>
5. Ji, Z. et al. *Survey of Hallucination in Natural Language Generation.* ACM Computing Surveys 55(12), 2023. <https://doi.org/10.1145/3571730>
6. Huang, L. et al. *A Survey on Hallucination in Large Language Models: Principles, Taxonomy, Challenges, and Open Questions.* arXiv:2311.05232, 2023. <https://arxiv.org/abs/2311.05232>
7. Lewis, P. et al. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS 2020. arXiv:2005.11401. <https://arxiv.org/abs/2005.11401> (planned future direction)

### Software & documentation
8. Ollama — <https://ollama.com> · API reference: <https://github.com/ollama/ollama/blob/main/docs/api.md>
9. Qwen models on Ollama — <https://ollama.com/library/qwen3>, <https://ollama.com/library/qwen2.5-coder>, <https://ollama.com/library/qwen2.5vl>
10. PaddleOCR — <https://github.com/PaddlePaddle/PaddleOCR> · PaddlePaddle — <https://www.paddlepaddle.org.cn/en>
11. Django — <https://docs.djangoproject.com/> · Django REST Framework — <https://www.django-rest-framework.org/>
12. PyMuPDF — <https://pymupdf.readthedocs.io/> · Pillow — <https://pillow.readthedocs.io/> · python-docx — <https://python-docx.readthedocs.io/>
13. React — <https://react.dev/> · Vite — <https://vite.dev/>
14. react-markdown — <https://github.com/remarkjs/react-markdown> · remark-gfm — <https://github.com/remarkjs/remark-gfm> · lowlight — <https://github.com/wooorm/lowlight> · highlight.js — <https://highlightjs.org/>
15. Lucide icons — <https://lucide.dev/>
16. NDJSON (newline-delimited JSON) — <https://github.com/ndjson/ndjson-spec>
17. axe-core accessibility engine — <https://github.com/dequelabs/axe-core> · WCAG 2.1 — <https://www.w3.org/TR/WCAG21/>
18. Chrome DevTools Protocol — <https://chromedevtools.github.io/devtools-protocol/>
