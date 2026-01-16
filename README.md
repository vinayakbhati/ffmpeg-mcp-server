# FFmpeg MCP Server

An MCP (Model Context Protocol) compliant HTTP server that exposes FFmpeg as a safe, discoverable tool for AI systems such as VS Code Copilot and automation agents.

## Features
- MCP-compliant APIs (initialize, tools/list, tools/call)
- Exposes ffmpeg.execute tool
- Input validation & execution timeouts
- Captures stdout, stderr, exit codes
- JSON-RPC + REST compatible

## Prerequisites
- Python 3.9+
- FFmpeg installed and available in PATH

## Installation
```bash
git clone <repo>
cd ffmpeg-mcp-server
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run Server
```bash
python server.py
```

Server runs on http://localhost:8000

## Documentation
See docs/ for architecture, MCP overview, and VS Code integration.