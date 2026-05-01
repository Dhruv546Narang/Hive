"""
Hive CLI — Local AI Coding Assistant
Inspired by Claude Code CLI and GitHub Copilot CLI.
"""

import argparse, asyncio, os, sys, platform, time, threading, subprocess, json, shutil
import uvicorn
from coordinator.config import settings

# ── ANSI ─────────────────────────────────────────────────────────────────
BOLD="\033[1m"; DIM="\033[2m"; ITALIC="\033[3m"; RESET="\033[0m"
AMBER="\033[38;2;168;85;247m"  # re-mapped to purple as primary theme
GREEN="\033[38;2;16;185;129m"
SKY="\033[38;2;56;189;248m"; ROSE="\033[38;2;244;63;94m"
GRAY="\033[38;2;100;100;120m"; WHITE="\033[38;2;240;240;245m"
PURPLE="\033[38;2;168;85;247m"; LILAC="\033[38;2;192;132;252m"
CYAN="\033[38;2;34;211;238m"
BG_DARK="\033[48;2;14;14;22m"; CLEAR_LINE="\033[2K\r"

# ── Screen Buffer ────────────────────────────────────────────────────────
ALT_SCREEN_ON  = "\033[?1049h"  # Enter alternate screen buffer
ALT_SCREEN_OFF = "\033[?1049l"  # Leave alternate screen buffer (restores old content)
CLEAR_SCREEN   = "\033[2J\033[H"  # Clear screen + move cursor to top
HIDE_CURSOR    = "\033[?25l"
SHOW_CURSOR    = "\033[?25h"
SAVE_CURSOR    = "\033[s"
RESTORE_CURSOR = "\033[u"

def enter_alt_screen():
    sys.stdout.write(ALT_SCREEN_ON + CLEAR_SCREEN + HIDE_CURSOR)
    sys.stdout.flush()

def leave_alt_screen():
    sys.stdout.write(SHOW_CURSOR + ALT_SCREEN_OFF)
    sys.stdout.flush()

# ── Box drawing ──────────────────────────────────────────────────────────
def box(lines, width=54, color=AMBER):
    top = f"  {color}╭{'─'*width}╮{RESET}"
    bot = f"  {color}╰{'─'*width}╯{RESET}"
    rows = []
    for l in lines:
        stripped = l.replace(BOLD,"").replace(DIM,"").replace(RESET,"").replace(AMBER,"").replace(GREEN,"").replace(SKY,"").replace(ROSE,"").replace(GRAY,"").replace(WHITE,"").replace(PURPLE,"").replace(CYAN,"").replace(ITALIC,"")
        pad = width - 2 - len(stripped)
        rows.append(f"  {color}│{RESET} {l}{' '*max(pad,0)} {color}│{RESET}")
    return "\n".join([top]+rows+[bot])

# ── Spinner (with pulsing hex in header) ─────────────────────────────────
class Spinner:
    FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    HEX_PULSE = ["⬡","⬢","⬡","◇","⬡","⬢"]
    def __init__(self, text="Thinking", header_hex_col=5):
        self.text = text; self._stop = threading.Event(); self._thread = None
        self._hex_col = header_hex_col
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
    def _spin(self):
        i = 0
        while not self._stop.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            elapsed = time.time() - self._start
            hex_c = self.HEX_PULSE[(i // 5) % len(self.HEX_PULSE)]
            # Pulse the hex in the compact header (row 2)
            sys.stdout.write(f"{SAVE_CURSOR}\033[2;{self._hex_col}H{AMBER}{BOLD}{hex_c}{RESET}{RESTORE_CURSOR}")
            sys.stdout.write(f"{CLEAR_LINE}  {AMBER}{frame}{RESET} {GRAY}{self.text} ({elapsed:.0f}s){RESET}")
            sys.stdout.flush(); i += 1; self._stop.wait(0.08)
        # Restore logo
        sys.stdout.write(f"{SAVE_CURSOR}\033[2;{self._hex_col}H{AMBER}{BOLD}⬡{RESET}{RESTORE_CURSOR}")
        sys.stdout.write(CLEAR_LINE); sys.stdout.flush()
    def __enter__(self):
        self._start = time.time(); self.start(); return self
    def __exit__(self, *a):
        self._stop.set()
        if self._thread: self._thread.join(timeout=1)

# ── System Detection ─────────────────────────────────────────────────────
def detect_gpu():
    try:
        r = subprocess.run(["nvidia-smi","--query-gpu=name,memory.total","--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            if len(parts) >= 2:
                return f"{parts[0]} ({int(float(parts[1]))//1024} GB)"
    except: pass
    return "CPU only"

def detect_ram():
    try:
        import ctypes
        class MS(ctypes.Structure):
            _fields_=[("dwLength",ctypes.c_ulong),("dwMemoryLoad",ctypes.c_ulong),
                      ("ullTotalPhys",ctypes.c_ulonglong),("ullAvailPhys",ctypes.c_ulonglong),
                      ("a",ctypes.c_ulonglong),("b",ctypes.c_ulonglong),
                      ("c",ctypes.c_ulonglong),("d",ctypes.c_ulonglong),("e",ctypes.c_ulonglong)]
        s=MS(); s.dwLength=ctypes.sizeof(s)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        total=s.ullTotalPhys//(1024**3); avail=s.ullAvailPhys//(1024**3)
        return f"{total} GB ({avail} GB free)"
    except: return "Unknown"

def detect_git():
    try:
        branch = subprocess.run(["git","rev-parse","--abbrev-ref","HEAD"],
                                capture_output=True,text=True,timeout=3,cwd=os.getcwd())
        if branch.returncode != 0: return None
        b = branch.stdout.strip()
        status = subprocess.run(["git","status","--porcelain"],
                                capture_output=True,text=True,timeout=3,cwd=os.getcwd())
        changes = len([l for l in status.stdout.strip().split("\n") if l.strip()]) if status.stdout.strip() else 0
        return f"{b}" + (f" ({changes} modified)" if changes else "")
    except: return None

def detect_project():
    cwd = os.getcwd()
    markers = {
        "package.json":"Node.js","pyproject.toml":"Python","Cargo.toml":"Rust",
        "go.mod":"Go","pom.xml":"Java/Maven","build.gradle":"Java/Gradle",
        "*.sln":"C#/.NET","Gemfile":"Ruby","composer.json":"PHP",
    }
    for f,lang in markers.items():
        if os.path.exists(os.path.join(cwd,f)): return lang
    # Check by file extensions
    exts = set()
    for fn in os.listdir(cwd):
        if "." in fn: exts.add(fn.rsplit(".",1)[-1])
    ext_map = {"py":"Python","js":"JavaScript","ts":"TypeScript","rs":"Rust","go":"Go","java":"Java","cpp":"C++","c":"C"}
    for e,l in ext_map.items():
        if e in exts: return l
    return "Unknown"

def detect_ollama_models():
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        if r.status_code == 200:
            return [m.get("name","") for m in r.json().get("models",[])]
    except: pass
    return []

# ── Animated Banner ──────────────────────────────────────────────────────
def animate_banner(model, gpu, ram, git_info, project):
    W = 50  # box width
    c = AMBER
    sys.stdout.write(SHOW_CURSOR)

    # Top border
    sys.stdout.write(f"  {c}╭{'─'*W}╮{RESET}\n"); sys.stdout.flush(); time.sleep(0.02)

    # Hexagon inside box
    hex_lines = [
        f"{'╱ ╲':^{W}}",
        f"{'╱   ╲':^{W}}",
        f"{'│  *  │':^{W}}",
        f"{'╲   ╱':^{W}}",
        f"{'╲ ╱':^{W}}",
        f"{'':^{W}}",
        f"{'H I V E':^{W}}",
        f"{'Local AI Coding Assistant · v0.1.0':^{W}}",
    ]
    for hl in hex_lines:
        sys.stdout.write(f"  {c}│{AMBER}{BOLD}{hl}{RESET}{c}│{RESET}\n")
        sys.stdout.flush(); time.sleep(0.03)

    # Separator
    sys.stdout.write(f"  {c}├{'─'*W}┤{RESET}\n"); sys.stdout.flush(); time.sleep(0.02)

    # Info rows
    def info_row(label, value, vc=WHITE):
        txt = f"  {label:>8s}  {RESET}{vc}{value}{RESET}"
        stripped = f"  {label:>8s}  {value}"
        pad = W - len(stripped)
        sys.stdout.write(f"  {c}│{RESET}{txt}{' '*max(pad,0)}{c}│{RESET}\n")
        sys.stdout.flush(); time.sleep(0.03)

    info_row("Model", model)
    info_row("GPU", gpu)
    info_row("RAM", ram)
    info_row("CWD", os.getcwd())
    if git_info: info_row("Git", git_info, GREEN)
    if project != "Unknown": info_row("Project", project, SKY)

    # Separator
    sys.stdout.write(f"  {c}├{'─'*W}┤{RESET}\n"); sys.stdout.flush(); time.sleep(0.02)

    # Tools & help row
    tools_txt = f"  Tools  read · write · edit · run · list · search"
    help_txt  = f"  Help  /help   Exit  /exit   Clear  /clear"
    pad1 = W - len(tools_txt)
    pad2 = W - len(help_txt)
    sys.stdout.write(f"  {c}│{RESET}{GRAY}{tools_txt}{' '*max(pad1,0)}{c}│{RESET}\n")
    sys.stdout.write(f"  {c}│{RESET}{GRAY}{help_txt}{' '*max(pad2,0)}{c}│{RESET}\n")

    # Bottom border
    sys.stdout.write(f"  {c}╰{'─'*W}╯{RESET}\n\n"); sys.stdout.flush(); time.sleep(0.02)

# ── Response Formatter ───────────────────────────────────────────────────
def format_response(text):
    """Basic syntax highlighting for markdown code blocks."""
    lines = text.split("\n")
    output = []
    in_code = False
    lang = ""
    for line in lines:
        if line.strip().startswith("```") and not in_code:
            in_code = True
            lang = line.strip()[3:].strip()
            label = f" {lang} " if lang else " code "
            output.append(f"  {GRAY}┌──{DIM}[{label}]{RESET}{GRAY}{'─'*max(1,38-len(label))}{RESET}")
        elif line.strip() == "```" and in_code:
            in_code = False
            output.append(f"  {GRAY}└{'─'*44}{RESET}")
        elif in_code:
            # Colorize some syntax
            colored = line
            colored = colored.replace("def ", f"{PURPLE}def {RESET}")
            colored = colored.replace("class ", f"{PURPLE}class {RESET}")
            colored = colored.replace("import ", f"{PURPLE}import {RESET}")
            colored = colored.replace("from ", f"{PURPLE}from {RESET}")
            colored = colored.replace("return ", f"{PURPLE}return {RESET}")
            colored = colored.replace("async ", f"{PURPLE}async {RESET}")
            colored = colored.replace("await ", f"{PURPLE}await {RESET}")
            colored = colored.replace("const ", f"{SKY}const {RESET}")
            colored = colored.replace("let ", f"{SKY}let {RESET}")
            colored = colored.replace("function ", f"{PURPLE}function {RESET}")
            output.append(f"  {GRAY}│{RESET} {colored}")
        else:
            # Bold markdown headers
            if line.startswith("### "): line = f"{BOLD}{line[4:]}{RESET}"
            elif line.startswith("## "): line = f"{BOLD}{line[3:]}{RESET}"
            elif line.startswith("# "): line = f"{BOLD}{line[2:]}{RESET}"
            elif line.startswith("- "): line = f"{AMBER}•{RESET} {line[2:]}"
            elif line.startswith("* "): line = f"{AMBER}•{RESET} {line[2:]}"
            # Inline code
            import re
            line = re.sub(r'`([^`]+)`', f'{CYAN}\\1{RESET}', line)
            output.append(f"  {WHITE}{line}{RESET}")
    return "\n".join(output)

# ── Tool Display ─────────────────────────────────────────────────────────
TOOL_ICONS = {
    "read_file":"📄","write_file":"✏️ ","edit_file":"🔧","run_command":"▶️ ",
    "list_directory":"📁","search_files":"🔍",
}

def print_tool_start(name, args):
    icon = TOOL_ICONS.get(name, "⚙️")
    preview = args.get("path", args.get("command","")[:60] if "command" in args else args.get("query",""))
    sys.stdout.write(f"  {icon} {DIM}{name}{RESET} {GRAY}{preview}{RESET}\n")
    sys.stdout.flush()

_edit_history = []  # [(path, original_content)]

def print_tool_end(name, result):
    # Track file edits for /undo
    if name in ("write_file","edit_file"):
        # Result contains the path info
        pass
    if name == "run_command":
        lines = result.strip().split("\n")
        show = lines[:6]
        for l in show:
            print(f"  {GRAY}  │ {l[:100]}{RESET}")
        if len(lines) > 6:
            print(f"  {GRAY}  │ ... ({len(lines)-6} more lines){RESET}")

def track_edit(name, args, cwd):
    """Save original file content before edits for /undo."""
    if name in ("write_file","edit_file"):
        path = args.get("path","")
        if not os.path.isabs(path): path = os.path.normpath(os.path.join(cwd, path))
        if os.path.exists(path):
            try:
                with open(path,"r",encoding="utf-8",errors="replace") as f:
                    _edit_history.append((path, f.read()))
            except: pass
        else:
            _edit_history.append((path, None))  # new file

# ── Stats Bar ────────────────────────────────────────────────────────────
def print_stats_bar(result):
    """Print a compact stats line after each response."""
    from coordinator.agent import ChatResult
    parts = []
    if result.tool_calls_made:
        parts.append(f"{AMBER}{result.tool_calls_made} tool{'s' if result.tool_calls_made!=1 else ''}{RESET}")
    if result.eval_count:
        parts.append(f"{GRAY}{result.eval_count} tokens{RESET}")
    tps = result.tokens_per_sec
    if tps > 0:
        parts.append(f"{GRAY}{tps:.1f} tok/s{RESET}")
    parts.append(f"{GRAY}{result.total_time:.1f}s{RESET}")
    if parts:
        print(f"  {DIM}{'  ·  '.join(parts)}{RESET}\n")

# ── Slash Commands ───────────────────────────────────────────────────────
HELP_TEXT = f"""
  {BOLD}{AMBER}Commands{RESET}

  {AMBER}/help{RESET}          Show this help
  {AMBER}/clear{RESET}         Clear conversation history
  {AMBER}/model{RESET} NAME    Switch model
  {AMBER}/cd{RESET} PATH       Change working directory
  {AMBER}/stats{RESET}         Show session statistics
  {AMBER}/diff{RESET}          Show git diff of working tree
  {AMBER}/undo{RESET}          Undo last file edit
  {AMBER}/compact{RESET}       Toggle compact mode (fewer details)
  {AMBER}/exit{RESET}          Exit Hive

  {BOLD}Input{RESET}
  {GRAY}End a line with \\ to continue on next line (multi-line input){RESET}
  {GRAY}Ctrl+C to interrupt a running response{RESET}
"""

# ── Main Commands ────────────────────────────────────────────────────────
def cmd_start(args):
    import socket
    from coordinator.capacity import get_local_capacity
    
    hostname = socket.gethostname()
    local = get_local_capacity()
    
    print(f"\n{AMBER}{BOLD}  [*] HIVE COORDINATOR  –  {hostname}{RESET}")
    print(f"  {'='*58}")
    print(f"  {GRAY}Port{RESET}    {WHITE}{settings.coordinator_port}{RESET}")
    print(f"  {GRAY}VRAM{RESET}    {WHITE}{local.vram_total_mb:,} MB ({len(local.gpus)} GPU){RESET}")
    print(f"  {GRAY}RAM {RESET}    {WHITE}{local.ram_total_mb:,} MB{RESET}")
    print(f"  {'='*58}")
    print(f"  {GREEN}[+]{RESET} Starting API and Dashboard...")
    print(f"  {GREEN}[+]{RESET} Dashboard available at {SKY}http://localhost:{settings.coordinator_port}{RESET}\n")
    
    # Hide the default uvicorn startup logs to keep it clean
    import logging
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    uvicorn.run("coordinator.main:app",host="0.0.0.0",port=settings.coordinator_port,reload=False,log_level="warning")

def cmd_worker(args):
    from worker.main import main as w; w()

def cmd_status(args):
    import httpx
    try:
        r=httpx.get(f"http://localhost:{settings.coordinator_port}/api/cluster/status",timeout=5.0)
        r.raise_for_status(); d=r.json(); c=d["cluster"]
        print(box([
            f"{AMBER}{BOLD}[*] HIVE CLUSTER STATUS{RESET}","",
            f"Nodes      {WHITE}{c['node_count']}{RESET}",
            f"VRAM       {WHITE}{c['total_vram_mb']:,} MB{RESET}",
            f"RAM        {WHITE}{c['total_ram_mb']:,} MB{RESET}",
            f"Usable     {WHITE}{c['usable_memory_mb']:,} MB{RESET}",
            f"Ollama     {GREEN if c['ollama_connected'] else ROSE}{'Connected' if c['ollama_connected'] else 'Offline'}{RESET}",
        ]))
        for n in d["nodes"]:
            gpus=n.get("gpus",[]); gs=", ".join(g["name"] for g in gpus) if gpus else "CPU"
            print(f"  {WHITE}{n['hostname']}{RESET} ({n['role']}) — {gs}")
        for m in d.get("ollama_models",[]):
            print(f"  {GREEN}[+]{RESET} {m['name']} ({m.get('size',0)/(1024**3):.1f} GB)")
        print()
    except Exception as e:
        print(f"{ROSE}Error: {e}{RESET}"); sys.exit(1)

def cmd_models(args):
    from coordinator.model_downloader import get_registry, list_downloaded, is_downloaded
    registry = get_registry()
    downloaded = list_downloaded()
    dl_names = {d['filename'] for d in downloaded}

    print(f"\n  {BOLD}{AMBER}Available Models{RESET}")
    print(f"  {'='*58}")
    print(f"  {GRAY}{'Name':<28} {'Size':>7} {'VRAM':>7} {'Status':>10}{RESET}")
    print(f"  {GRAY}{'-'*58}{RESET}")
    for m in registry:
        fname = m.get('filename', '')
        if fname in dl_names or is_downloaded(fname):
            status = f"{GREEN}installed{RESET}"
            icon = f"{GREEN}*{RESET}"
        else:
            status = f"{GRAY}available{RESET}"
            icon = f"{GRAY}o{RESET}"
        name = m.get('name', m['id'])
        if len(name) > 26: name = name[:24] + '..'
        size = f"{m.get('size_gb', '?')} GB"
        vram = f"{m.get('vram_gb', '?')} GB"
        print(f"  {icon} {WHITE}{name:<26}{RESET} {size:>7} {vram:>7} {status:>10}")

    if downloaded:
        print(f"\n  {BOLD}{AMBER}Downloaded Models{RESET}")
        print(f"  {GRAY}{'-'*58}{RESET}")
        for d in downloaded:
            print(f"  {GREEN}*{RESET} {WHITE}{d['filename']}{RESET}  ({d['size_gb']} GB)")

    print(f"\n  {GRAY}Pull a model: hive pull <name>{RESET}")
    print(f"  {GRAY}Example: hive pull qwen2.5-7b{RESET}\n")


def cmd_pull(args):
    import asyncio
    from coordinator.model_downloader import pull_model, find_model, is_downloaded

    query = args.model_name
    if not query:
        print(f"  {ROSE}Usage: hive pull <model-name>{RESET}")
        print(f"  {GRAY}Example: hive pull qwen2.5-7b{RESET}")
        print(f"  {GRAY}Run 'hive models' to see available models{RESET}")
        return

    # Show what we're about to download
    model = find_model(query)
    if model:
        if is_downloaded(model['filename']):
            print(f"  {GREEN}*{RESET} {model['name']} is already downloaded")
            print(f"  {GRAY}Path: ~/.hive/models/{model['filename']}{RESET}")
            return
        print(f"\n  {AMBER}Pulling {model['name']}{RESET}")
        print(f"  {GRAY}Size: ~{model.get('size_gb', '?')} GB  |  VRAM: ~{model.get('vram_gb', '?')} GB  |  Quant: {model.get('quant', 'Q4_K_M')}{RESET}")
        print(f"  {GRAY}Repo: {model['repo']}{RESET}")
        print()
    else:
        print(f"\n  {AMBER}Pulling from: {query}{RESET}\n")

    def on_progress(downloaded, total):
        pct = downloaded * 100 // total
        dl_gb = downloaded / (1024**3)
        total_gb = total / (1024**3)
        bar_w = 40
        filled = pct * bar_w // 100
        bar = "#" * filled + "-" * (bar_w - filled)
        sys.stdout.write(f"\r  [{bar}] {pct}% ({dl_gb:.1f}/{total_gb:.1f} GB)")
        sys.stdout.flush()
        if downloaded >= total:
            sys.stdout.write("\n")

    def on_status(msg):
        print(f"  {GRAY}{msg}{RESET}")

    try:
        result = asyncio.run(pull_model(
            query,
            on_progress=on_progress,
            on_status=on_status,
        ))
        if result:
            print(f"\n  {GREEN}*{RESET} Model ready: {result}")
            print(f"  {GRAY}Use with: hive chat -m {result.stem}{RESET}\n")
        else:
            print(f"\n  {ROSE}Download failed or model not found{RESET}")
    except KeyboardInterrupt:
        print(f"\n  {GRAY}Download cancelled (partial file saved, will resume){RESET}")
    except Exception as e:
        print(f"\n  {ROSE}Error: {e}{RESET}")


def _load_model_for_chat(model: str) -> str:
    """Checks if the model is GGUF, triggers cluster load, else checks Ollama. Returns actual model name."""
    from coordinator.model_downloader import list_downloaded, find_model
    ggufs = list_downloaded()
    
    # Is it in the registry/downloaded models?
    reg_model = find_model(model)
    local_gguf = None
    if reg_model and reg_model['filename'] in [g['filename'] for g in ggufs]:
        local_gguf = next(g['path'] for g in ggufs if g['filename'] == reg_model['filename'])
    else:
        # Check by filename directly
        for g in ggufs:
            if model.lower() in g['filename'].lower():
                local_gguf = g['path']
                model = g['filename']  # Update display name
                break
                
    if local_gguf:
        import httpx
        from coordinator.config import settings
        # Call the coordinator to load the model across the cluster
        try:
            r = httpx.post(
                f"http://127.0.0.1:{settings.coordinator_port}/api/cluster/load_model",
                json={"model_path": local_gguf},
                timeout=15.0
            )
            r.raise_for_status()
        except Exception as e:
            print(f"  {ROSE}Failed to initialize distributed cluster (is the coordinator running?){RESET}")
            print(f"  {GRAY}Run 'hive start' first.{RESET}")
            sys.exit(1)
            
    else:
        # Fallback to Ollama logic
        models = detect_ollama_models()
        if models:
            matched = None
            for m in models:
                if model.lower() in m.lower(): matched = m; break
            if not matched:
                matched = models[0]
                print(f"  {GRAY}'{model}' not found in Ollama, using '{matched}'{RESET}")
            model = matched
        else:
            print(f"  {ROSE}Cannot find model '{model}' in Hive models or Ollama.{RESET}")
            print(f"  {GRAY}Use 'hive pull <model>' to download a model.{RESET}")
            sys.exit(1)
            
    return model

# ── Chat Command (the main event) ────────────────────────────────────────
def cmd_chat(args):
    model = args.model
    cwd = os.getcwd()
    compact_mode = False
    session_start = time.time()

    # Detect system info (before alt screen so errors show normally)
    gpu = detect_gpu()
    ram = detect_ram()
    git_info = detect_git()
    project = detect_project()

    model = _load_model_for_chat(model)

    # ── Enter alternate screen (old terminal content hidden, restored on exit)
    enter_alt_screen()

    try:
        _chat_loop(args, model, cwd, gpu, ram, git_info, project, session_start)
    except (KeyboardInterrupt, EOFError):
        pass  # Clean exit on Ctrl+C at any point
    finally:
        leave_alt_screen()

# ── TUI Layout ───────────────────────────────────────────────────────────
HEADER_ROWS = 6   # clean neo header
FOOTER_ROWS = 2   # separator + input prompt

def _get_size():
    return shutil.get_terminal_size((80, 24))

def _draw_neo_header(model, cwd, gpu="", ram=""):
    """Draw a clean 6-row neo-glassmorphic header."""
    cols, _ = _get_size()
    w = min(cols - 4, 72)
    c = GRAY
    max_cwd = max(10, w - 30)
    dc = cwd if len(cwd) <= max_cwd else "..." + cwd[-(max_cwd-3):]

    def pad_row(txt):
        stripped_len = len(txt.replace(BOLD,'').replace(DIM,'').replace(RESET,'').replace(AMBER,'').replace(GREEN,'').replace(LILAC,'').replace(SKY,'').replace(GRAY,'').replace(WHITE,'').replace(PURPLE,'').replace(CYAN,'').replace(ROSE,'').replace(ITALIC,''))
        return txt + ' ' * max(0, w - 4 - stripped_len)

    info1 = f"{BOLD}{AMBER}[*] H I V E{RESET}  {GRAY}·{RESET}  {WHITE}{model}{RESET}"
    info2 = f"{GRAY}Dir:{RESET}  {WHITE}{dc}{RESET}"
    info3 = f"{GRAY}Sys:{RESET}  {WHITE}{gpu}{RESET}" if gpu else ""
    info4 = f"{GRAY}Cmds: /help  /clear  /model  /cd  /stats  /exit{RESET}"

    rows = [
        pad_row(f"  {info1}"),
        pad_row(f"  {info2}"),
        pad_row(f"  {info3}"),
        pad_row(f"  {info4}"),
    ]

    sys.stdout.write(f"\033[1;1H")
    sys.stdout.write(f"  {c}╭{'─'*(w-2)}╮{RESET}\n")
    for r in rows:
        sys.stdout.write(f"  {c}│{RESET} {r} {c}│{RESET}\n")
    sys.stdout.write(f"  {c}╰{'─'*(w-2)}╯{RESET}\n")
    sys.stdout.flush()

def _draw_footer():
    """Draw a 2-row fixed footer at the bottom."""
    cols, rows = _get_size()
    w = min(cols - 4, 72)
    sys.stdout.write(SAVE_CURSOR)
    sys.stdout.write(f"\033[{rows-1};1H\033[2K")  # separator line
    sys.stdout.write(f"  {GRAY}{'─'*w}{RESET}")
    sys.stdout.write(f"\033[{rows};1H\033[2K")    # prompt line (cleared, ready)
    sys.stdout.write(RESTORE_CURSOR)
    sys.stdout.flush()

def _setup_scroll_region():
    """Set scroll region between header and footer."""
    _, rows = _get_size()
    top = HEADER_ROWS + 1
    bottom = rows - FOOTER_ROWS
    sys.stdout.write(f"\033[{top};{bottom}r")  # set scroll region
    sys.stdout.write(f"\033[{top};1H")          # move cursor into region
    sys.stdout.flush()

def _reset_scroll_region():
    sys.stdout.write("\033[r")
    sys.stdout.flush()

def _get_input():
    """Read input from the fixed bottom prompt."""
    _, rows = _get_size()
    # Move cursor to the footer prompt line
    sys.stdout.write(f"\033[{rows};1H\033[2K")
    sys.stdout.write(f"  {AMBER}{BOLD}❯{RESET} ")
    sys.stdout.flush()
    text = input()
    # Clear the prompt line after reading
    sys.stdout.write(f"\033[{rows};1H\033[2K")
    # Move cursor back to the bottom of the scroll region
    _, rows2 = _get_size()
    bottom = rows2 - FOOTER_ROWS
    sys.stdout.write(f"\033[{bottom};1H")
    sys.stdout.flush()
    return text

def _scroll_print(text):
    """Print text inside the scroll region."""
    sys.stdout.write(text + "\n")
    sys.stdout.flush()

# ── Chat loop ────────────────────────────────────────────────────────────
def _chat_loop(args, model, cwd, gpu, ram, git_info, project, session_start):
    compact_mode = False

    # Collapse to neo header + scroll layout
    sys.stdout.write(CLEAR_SCREEN)
    sys.stdout.flush()
    _draw_neo_header(model, cwd, gpu=gpu, ram=ram)
    _setup_scroll_region()
    _draw_footer()

    # Welcome message in scroll region
    _scroll_print(f"  {GRAY}Ready. Type a message or /help for commands.{RESET}")
    _scroll_print("")

    # Create agent
    from coordinator.agent import HiveAgent
    context = f"Language: {project}"
    if git_info: context += f", Git: {git_info}"
    agent = HiveAgent(model=model, cwd=cwd, os_name=platform.system(), context=context)

    def on_tool_start(name, tool_args):
        track_edit(name, tool_args, agent.cwd)
        print_tool_start(name, tool_args)

    while True:
        try:
            _draw_footer()
            user_input = _get_input().strip()
            if not user_input:
                continue

            # Show user message in scroll region
            _scroll_print(f"  {AMBER}{BOLD}You:{RESET} {WHITE}{user_input}{RESET}")
            _scroll_print("")

            # ── Slash commands ──
            if user_input.startswith("/"):
                cmd = user_input.split()[0].lower()
                rest = user_input[len(cmd):].strip()

                if cmd in ("/exit","/quit","/q"):
                    elapsed = time.time() - session_start
                    stats = agent.get_session_stats()
                    _scroll_print(f"  {GRAY}Session: {stats['messages']} msgs · {stats['tool_calls']} tools · {stats['tokens']} tokens · {elapsed:.0f}s{RESET}")
                    _scroll_print(f"  {AMBER}Goodbye! 🐼{RESET}")
                    time.sleep(0.5)
                    break
                elif cmd == "/clear":
                    agent.clear_history()
                    # Redraw layout cleanly
                    sys.stdout.write(CLEAR_SCREEN); sys.stdout.flush()
                    _draw_neo_header(model, cwd, gpu=gpu, ram=ram)
                    _setup_scroll_region(); _draw_footer()
                    _scroll_print(f"  {GREEN}✓ Conversation cleared{RESET}")
                elif cmd == "/help":
                    for line in HELP_TEXT.strip().split("\n"):
                        _scroll_print(line)
                elif cmd == "/model":
                    if rest:
                        try:
                            _scroll_print(f"  {GRAY}Loading model {rest}...{RESET}")
                            new_model = _load_model_for_chat(rest)
                            agent = HiveAgent(model=new_model, cwd=agent.cwd, os_name=platform.system(), context=context)
                            model = new_model
                            _draw_neo_header(model, cwd, gpu=gpu, ram=ram)
                            _scroll_print(f"  {GREEN}[+] Switched to {new_model}{RESET}")
                        except SystemExit:
                            _scroll_print(f"  {ROSE}Failed to switch model.{RESET}")
                    else:
                        _scroll_print(f"  {GRAY}Current: {model}{RESET}")
                elif cmd == "/cd":
                    if rest:
                        new = os.path.abspath(os.path.join(agent.cwd, rest))
                        if os.path.isdir(new):
                            agent.set_cwd(new); cwd = new
                            _draw_neo_header(model, cwd, gpu=gpu, ram=ram)
                            _scroll_print(f"  {GREEN}✓ {new}{RESET}")
                        else: _scroll_print(f"  {ROSE}Not a directory: {new}{RESET}")
                    else: _scroll_print(f"  {GRAY}{agent.cwd}{RESET}")
                elif cmd == "/stats":
                    elapsed = time.time() - session_start
                    s = agent.get_session_stats()
                    for line in box([
                        f"{AMBER}{BOLD}Session Stats{RESET}","",
                        f"Messages     {WHITE}{s['messages']}{RESET}",
                        f"Tool calls   {WHITE}{s['tool_calls']}{RESET}",
                        f"Tokens       {WHITE}{s['tokens']:,}{RESET}",
                        f"Uptime       {WHITE}{elapsed:.0f}s ({elapsed/60:.1f}m){RESET}",
                        f"Edits        {WHITE}{len(_edit_history)}{RESET}",
                    ]).split("\n"): _scroll_print(line)
                elif cmd == "/diff":
                    try:
                        r = subprocess.run(["git","diff","--stat"],capture_output=True,text=True,cwd=agent.cwd,timeout=5)
                        if r.stdout.strip():
                            for l in r.stdout.strip().split("\n"): _scroll_print(f"  {GRAY}{l}{RESET}")
                        else: _scroll_print(f"  {GRAY}No changes{RESET}")
                    except: _scroll_print(f"  {GRAY}Not a git repository{RESET}")
                elif cmd == "/undo":
                    if not _edit_history:
                        _scroll_print(f"  {GRAY}Nothing to undo{RESET}")
                    else:
                        path, original = _edit_history.pop()
                        try:
                            if original is None:
                                if os.path.exists(path): os.remove(path)
                                _scroll_print(f"  {GREEN}✓ Removed {path}{RESET}")
                            else:
                                with open(path,"w",encoding="utf-8") as f: f.write(original)
                                _scroll_print(f"  {GREEN}✓ Restored {path}{RESET}")
                        except Exception as e: _scroll_print(f"  {ROSE}Undo failed: {e}{RESET}")
                elif cmd == "/compact":
                    compact_mode = not compact_mode
                    _scroll_print(f"  {GREEN}✓ Compact mode {'on' if compact_mode else 'off'}{RESET}")
                else:
                    _scroll_print(f"  {GRAY}Unknown command. Try /help{RESET}")
                _scroll_print("")
                continue

            # ── Send to agent with streaming ──
            spinner = Spinner("Thinking")
            spinner._start = time.time()
            spinner.start()
            first_token = [True]

            def handle_token(text):
                if first_token[0]:
                    spinner._stop.set()
                    spinner._thread.join(timeout=0.5)
                    sys.stdout.write(CLEAR_LINE)
                    sys.stdout.write(f"  {WHITE}")
                    first_token[0] = False
                sys.stdout.write(text)
                sys.stdout.flush()

            try:
                result = asyncio.run(agent.chat(
                    user_input,
                    on_tool_start=on_tool_start,
                    on_tool_end=print_tool_end,
                    on_token=handle_token,
                ))
            except KeyboardInterrupt:
                spinner._stop.set()
                _scroll_print(f"  {GRAY}(interrupted){RESET}"); _scroll_print(""); continue
            except Exception as e:
                spinner._stop.set()
                _scroll_print(f"  {ROSE}Error: {e}{RESET}"); _scroll_print(""); continue

            if first_token[0]:
                spinner._stop.set()
                spinner._thread.join(timeout=0.5)
                sys.stdout.write(CLEAR_LINE)

            if not first_token[0]:
                sys.stdout.write(f"{RESET}\n\n")
                sys.stdout.flush()
            elif result.content:
                formatted = format_response(result.content)
                for line in formatted.split("\n"): _scroll_print(line)
                _scroll_print("")

            if not compact_mode:
                print_stats_bar(result)

        except (KeyboardInterrupt, EOFError):
            elapsed = time.time() - session_start
            stats = agent.get_session_stats()
            _scroll_print(f"\n  {GRAY}Session: {stats['messages']} msgs · {stats['tool_calls']} tools · {elapsed:.0f}s{RESET}")
            _scroll_print(f"  {AMBER}Goodbye! ⬡{RESET}")
            time.sleep(0.5)
            break

    _reset_scroll_region()

# ── Entry Point ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="🐝 Hive — Local AI Coding Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Commands:\n  chat    Interactive coding assistant (default)\n  start   Start coordinator daemon\n  worker  Start worker daemon\n  status  Cluster status\n  models  List models")
    sub = parser.add_subparsers(dest="command")
    cp = sub.add_parser("chat", help="Interactive coding assistant")
    cp.add_argument("-m","--model", default="qwen3.5", help="Ollama model (default: qwen3.5)")
    sub.add_parser("start", help="Start coordinator daemon")
    sub.add_parser("worker", help="Start worker daemon")
    sub.add_parser("status", help="Cluster status")
    sub.add_parser("models", help="List models")
    pp = sub.add_parser("pull", help="Download a model")
    pp.add_argument("model_name", nargs="?", default="", help="Model name or HF repo")
    args = parser.parse_args()
    cmds = {"chat":cmd_chat,"start":cmd_start,"worker":cmd_worker,"status":cmd_status,"models":cmd_models,"pull":cmd_pull}
    h = cmds.get(args.command)
    if h: h(args)
    else: args.model="qwen3.5"; cmd_chat(args)

if __name__ == "__main__":
    main()
