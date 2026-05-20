# 2. Installation

## System Requirements

- **Python** >= 3.13
- **Operating system** Linux, macOS, or Windows
- **Disk space** Varies by corpus size; 10+ GB recommended for large novels
- **RAM** 16+ GB recommended for running local LLMs
- **llama.cpp server** running in router mode (or any OpenAI-compatible API)

## Setup

### 1. Install Resemantica

```bash
git clone <repository-url>
```
```bash
cd resemantica
```
```bash
uv venv
```
```bash
# Linux/macOS
source .venv/bin/activate
```
```bash
# Windows
.venv\Scripts\activate
```
```bash
uv sync
```

For development extras:
```bash
uv sync --group dev
```

For embedding critic support (required for glossary discovery):
```bash
uv sync --extra critic
```

### 2. Start llama.cpp with Router Mode

Resemantica requires a running llama.cpp server. Router mode allows hosting multiple models simultaneously with dynamic switching and automatic VRAM management.

Create a `models.ini` file defining your models:

```ini
; Default settings for all models
[*]
parallel = 1
ctx-size = 4096

; Translator model for Pass 1
[HY-MT1.5-7B]
model = /path/to/HY-MT1.5-7B.gguf
n-gpu-layers = 32
load-on-startup = true

; Analyst model for Pass 2/3, summaries, idioms, entity extraction
[Qwen3.5-9B-GLM5.1]
model = /path/to/Qwen3.5-9B-GLM5.1.gguf
n-gpu-layers = 32
load-on-startup = true

; Evaluation model for candidate evaluation
[Qwen3.5-9B-NonThinking-unsloth]
model = /path/to/Qwen3.5-9B-NonThinking-unsloth.gguf
n-gpu-layers = 32
```

Launch the server:

```bash
llama-server --models-preset /path/to/models.ini --port 8080
```

The model names in the `.ini` section headers must match the `translator_name`, `analyst_name`, and `eval_name` values in your `resemantica.toml`. The default endpoint is `http://localhost:8080` (configurable in `[llm]` `base_url`).

See the official llama.cpp server documentation for details:
<https://github.com/ggml-org/llama.cpp/blob/master/examples/server/README.md>

### 3. Configure

Copy the template to a custom config file and adjust to your environment:

```bash
cp resemantica.toml my-config.toml
```

At minimum, update `[llm]` `base_url` to point to your llama.cpp server. See [Configuration](04-configuration.md) for all options.

### 4. Verify

```bash
rsem --help
```

Should display the help text with all available commands.

## First Run & Downloads

Two components download data automatically on first use:

- **BAAI/bge-m3** (embedding model) — Auto-downloaded from HuggingFace via `huggingface_hub.snapshot_download` when glossary discovery runs. Cached at `embedding/BAAI/bge-m3/`. Do not change the `embedding_name` in config unless you understand the embedding pipeline.

- **HanLP** (Chinese segmentation) — Downloads ~500MB on first call to `preprocess glossary-discover`. The MTL pipeline (`CLOSE_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_BASE_ZH`) provides tokenization, POS tagging, and NER. Falls back to simple character-level segmentation if unavailable (e.g., when `hanlp` package is not installed).

## Next Steps

See [Quick Start](03-quick-start.md) for your first translation run.
