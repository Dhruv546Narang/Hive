<![CDATA[<div align="center">

```
   ╭──╮ ╭──╮
   │░░├─┤░░│
   └┬─╯ ╰─┬┘
    │ ●  ● │
    │  ▽   │
    ╰──────╯
```

# H I V E

**Local AI Coding Assistant — Like Claude Code, but runs entirely on your hardware.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-a855f7?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/ollama-local%20LLM-a855f7?style=flat-square)](https://ollama.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-a855f7?style=flat-square)](LICENSE)

</div>

---

## What is Hive?

Hive is a **fully local, privacy-first AI coding assistant** that runs in your terminal. It connects to your local LLM (via [Ollama](https://ollama.com)) and gives you an agentic coding experience — reading files, writing code, running commands, and searching your codebase — all without sending a single byte to the cloud.

Think **Claude Code** or **GitHub Copilot CLI**, but:
- 🔒 **100% local** — your code never leaves your machine
- 🆓 **Free forever** — no API keys, no subscriptions
- 🐼 **Cute** — animated panda mascot that blinks at you

---

## Features

### 🤖 Agentic Tool Calling
Hive doesn't just chat — it **acts**. The LLM autonomously calls tools to complete tasks:

| Tool | What it does |
|---|---|
| `read_file` | Read any file in your project |
| `write_file` | Create new files or overwrite existing ones |
| `edit_file` | Targeted find-and-replace edits |
| `run_command` | Execute shell commands (build, test, install) |
| `list_directory` | Explore project structure |
| `search_files` | Regex search across your codebase |

### ⚡ Real-Time Streaming
Responses stream token-by-token directly to your terminal. No waiting for the full response — you see text appear in real-time at ~13 tok/s on consumer GPUs.

### 🎨 Premium TUI
- **Fixed header** with animated panda mascot (blinking eyes!)
- **Fixed input bar** pinned at the bottom
- **Scrolling chat area** in between — just like a real IDE
- **Purple theme** with box-drawn UI elements
- **Alternate screen buffer** — clean start, old terminal restored on exit
- **Syntax-highlighted** code blocks in responses

### 🛠️ Built-in Commands

| Command | Description |
|---|---|
| `/help` | Show all commands |
| `/clear` | Clear conversation + redraw UI |
| `/model NAME` | Hot-swap to a different Ollama model |
| `/cd PATH` | Change working directory |
| `/stats` | Session statistics (messages, tokens, tok/s) |
| `/diff` | Show `git diff --stat` |
| `/undo` | Revert the last file edit the agent made |
| `/compact` | Toggle compact mode (hide stats bar) |
| `/exit` | Exit Hive |

### 📊 Smart Stats
After every response, see:
```
  3 tools  ·  142 tokens  ·  13.5 tok/s  ·  4.2s
```

### 🌐 Web Dashboard
A React-based dashboard for monitoring cluster health, viewing models, and chatting via the browser.

### 🔗 Multi-Node Architecture (WIP)
Designed from the ground up for distributed inference — split large models across multiple laptops on your LAN using llama.cpp RPC layer sharding.

---

## Quick Start

### Prerequisites
- **Python 3.10+**
- **[Ollama](https://ollama.com)** installed and running
- A model pulled: `ollama pull qwen3.5` (or any model you prefer)

### Install

```bash
git clone https://github.com/Dhruv546Narang/Hive.git
cd Hive
python -m venv .venv

# Windows
.\.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -e .
```

### Run

```bash
# Start the coding assistant (default command)
hive chat

# Use a specific model
hive chat -m llama3.1

# Start the coordinator daemon (API + Dashboard)
hive start

# Check cluster status
hive status

# List available models
hive models
```

---

## Architecture

```
hive/
├── cli.py                  # Main CLI — TUI, chat loop, streaming
├── coordinator/
│   ├── agent.py            # Agentic loop (prompt → tools → response)
│   ├── tools.py            # Tool definitions + executor
│   ├── main.py             # FastAPI coordinator daemon
│   ├── router.py           # API routes
│   ├── discovery.py        # mDNS node discovery (AsyncZeroconf)
│   ├── rpc_client.py       # Ollama API client
│   ├── capacity.py         # Hardware detection (GPU, RAM)
│   ├── config.py           # Configuration management
│   ├── metrics.py          # Prometheus-style metrics
│   ├── model_watcher.py    # GGUF model file watcher
│   ├── shard_planner.py    # Layer allocation for multi-node
│   └── auth.py             # API key authentication
├── worker/
│   ├── main.py             # Worker daemon
│   └── rpc_server.py       # llama.cpp RPC server wrapper
├── ui/                     # React dashboard (Vite)
│   ├── src/
│   │   ├── pages/          # Dashboard, Chat, Models, Settings
│   │   └── components/     # Sidebar, shared components
│   └── package.json
├── models/                 # Model registry
├── config/                 # Default configuration
└── pyproject.toml          # Python package config
```

### How the Agent Loop Works

```
User Input
    │
    ▼
┌─────────────┐
│  Ollama API  │◄──── System prompt + conversation history + tool definitions
│  (streaming) │
└──────┬──────┘
       │
       ▼
  Tool calls?  ──Yes──► Execute tools (read/write/edit/run/search)
       │                       │
       No                      │
       │                       ▼
       ▼               Append results to history
  Stream text          Loop back to Ollama ───►
  to terminal
```

---

## Configuration

Hive uses `config/default.toml`:

```toml
coordinator_port = 8000
worker_port = 8080
model_dir = "~/.ollama/models"
```

Environment variables override config:
```bash
HIVE_COORDINATOR_PORT=9000 hive start
```

---

## Multi-Node Setup (Coming Soon)

The vision: run models too large for one GPU by splitting layers across multiple machines.

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Laptop A      │    │   Laptop B      │    │   Laptop C      │
│   RTX 4050 6GB  │◄──►│   GTX 1660 6GB  │◄──►│   RTX 3060 8GB  │
│   Layers 0–10   │    │   Layers 11–20  │    │   Layers 21–32  │
│   (coordinator) │    │   (worker)      │    │   (worker)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

**What you could run:**
| Model | VRAM Needed | Laptops (6GB each) |
|---|---|---|
| Qwen 2.5 14B (Q4) | ~9 GB | 2 |
| Qwen 2.5 32B (Q4) | ~18 GB | 3 |
| Llama 3.1 70B (Q4) | ~40 GB | 7 |

---

## Tech Stack

| Component | Technology |
|---|---|
| CLI & Agent | Python, asyncio, ANSI escape codes |
| LLM Backend | Ollama (local inference) |
| API Server | FastAPI, Uvicorn |
| Discovery | AsyncZeroconf (mDNS) |
| Dashboard | React, Vite |
| Distributed Inference | llama.cpp RPC (planned) |

---

## Roadmap

- [x] Interactive CLI with TUI (fixed header/footer, scrolling chat)
- [x] Agentic tool calling (read, write, edit, run, search)
- [x] Real-time token streaming
- [x] Animated panda mascot
- [x] Session stats (tokens, tok/s, timing)
- [x] Undo file edits
- [x] Git integration (`/diff`)
- [x] Web dashboard
- [x] mDNS node discovery
- [ ] Multi-node layer sharding via llama.cpp RPC
- [ ] Conversation persistence / session resume
- [ ] Tab completion for commands and file paths
- [ ] Image understanding (multimodal models)
- [ ] Auto-commit with generated messages
- [ ] Plugin system for custom tools

---

## Contributing

Contributions are welcome! This project is in active development. Feel free to open issues or PRs.

---

## License

MIT License — do whatever you want with it.

---

<div align="center">

**Built with 🐼 by [Dhruv](https://github.com/Dhruv546Narang)**

*Your code stays on your machine. Always.*

</div>
]]>
