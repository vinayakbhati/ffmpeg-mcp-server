"""
FFmpeg MCP Server
=================
A Model Context Protocol (MCP) compliant HTTP server for executing FFmpeg commands.

MCP Specification (JSON-RPC 2.0):
- POST /: Main message endpoint (initialize, tools/list, tools/call)
- GET /mcp: Server metadata endpoint (REST, for manual testing)
- GET /mcp/tools: Tool discovery endpoint (REST, for manual testing)
- POST /mcp/tools/{toolName}/invoke: Tool invocation endpoint (REST, for manual testing)
"""

from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, Union
import subprocess
import os
import re
import logging
import json
from pathlib import Path as FilePath

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="FFmpeg MCP Server",
    description="MCP-compliant server for executing FFmpeg commands",
    version="1.0.0"
)

# ============================================================================
# MCP Message Models (JSON-RPC 2.0)
# ============================================================================

class MCPMessage(BaseModel):
    """MCP message following JSON-RPC 2.0 format"""
    jsonrpc: str = "2.0"
    id: Optional[Union[int, str]] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

# ============================================================================
# MCP ROOT ENDPOINT: JSON-RPC 2.0 Message Handler (Primary MCP Protocol)
# ============================================================================

@app.post("/")
async def handle_mcp_message(message: MCPMessage):
    """
    Main MCP endpoint for JSON-RPC 2.0 protocol.
    VS Code MCP client connects here and sends JSON-RPC messages.
    """
    logger.info(f"Received MCP message: method={message.method}, id={message.id}")
    
    try:
        # Handle initialize request
        if message.method == "initialize":
            return MCPMessage(
                jsonrpc="2.0",
                id=message.id,
                result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "ffmpeg-mcp-server",
                        "version": "1.0.0"
                    }
                }
            )
        
        # Handle tools/list request
        elif message.method == "tools/list":
            return MCPMessage(
                jsonrpc="2.0",
                id=message.id,
                result={
                    "tools": [
                        {
                            "name": "ffmpeg_execute",
                            "description": "Execute FFmpeg commands on the host machine and return success or failure with logs",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "command": {
                                        "type": "string",
                                        "description": "FFmpeg command to execute. Must start with 'ffmpeg '"
                                    },
                                    "workingDir": {
                                        "type": "string",
                                        "description": "Optional working directory for execution. Defaults to current directory."
                                    },
                                    "timeout": {
                                        "type": "integer",
                                        "description": "Execution timeout in seconds (default 120, max 600)",
                                        "default": 120
                                    }
                                },
                                "required": ["command"]
                            }
                        }
                    ]
                }
            )
        
        # Handle tools/call request
        elif message.method == "tools/call":
            tool_name = message.params.get("name") if message.params else None
            arguments = message.params.get("arguments", {}) if message.params else {}
            
            logger.info(f"Tool call: {tool_name}")
            
            if tool_name != "ffmpeg_execute":
                return MCPMessage(
                    jsonrpc="2.0",
                    id=message.id,
                    error={
                        "code": -32601,
                        "message": f"Tool not found: {tool_name}"
                    }
                )
            
            # Execute the FFmpeg command
            try:
                args = FFmpegExecuteRequest(**arguments)
                
                # Validate command
                is_valid, error_msg = FFmpegCommandValidator.validate_command(args.command)
                if not is_valid:
                    return MCPMessage(
                        jsonrpc="2.0",
                        id=message.id,
                        error={
                            "code": -32602,
                            "message": error_msg
                        }
                    )
                
                # Validate working directory
                is_valid, error_msg, resolved_dir = FFmpegCommandValidator.validate_working_dir(args.workingDir)
                if not is_valid:
                    return MCPMessage(
                        jsonrpc="2.0",
                        id=message.id,
                        error={
                            "code": -32602,
                            "message": error_msg
                        }
                    )
                
                # Execute command
                exec_result = FFmpegExecutor.execute(
                    command=args.command,
                    working_dir=resolved_dir,
                    timeout=args.timeout if args.timeout is not None else 21600
                )
                
                # Format output for MCP
                output_text = f"""FFmpeg execution {'succeeded' if exec_result['success'] else 'failed'}

Exit Code: {exec_result['exitCode']}

Stdout:
{exec_result['logs']['stdout']}

Stderr:
{exec_result['logs']['stderr']}"""
                
                return MCPMessage(
                    jsonrpc="2.0",
                    id=message.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": output_text
                            }
                        ],
                        "isError": not exec_result['success']
                    }
                )
                
            except ValueError as e:
                return MCPMessage(
                    jsonrpc="2.0",
                    id=message.id,
                    error={
                        "code": -32602,
                        "message": f"Invalid parameters: {str(e)}"
                    }
                )
        
        # Unknown method
        else:
            return MCPMessage(
                jsonrpc="2.0",
                id=message.id,
                error={
                    "code": -32601,
                    "message": f"Method not found: {message.method}"
                }
            )
            
    except Exception as e:
        logger.error(f"Error handling MCP message: {str(e)}", exc_info=True)
        return MCPMessage(
            jsonrpc="2.0",
            id=message.id,
            error={
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        )

# ============================================================================
# REST ENDPOINTS (For Manual Testing with curl)
# ============================================================================

# ============================================================================
# MCP ENDPOINT 1: Server Metadata
# ============================================================================

@app.get("/mcp")
async def get_mcp_metadata():
    """
    Returns server metadata according to MCP specification.
    This endpoint tells clients what this server is and what it can do.
    """
    return {
        "name": "ffmpeg-mcp-server",
        "version": "1.0.0",
        "description": "MCP server for executing FFmpeg commands safely",
        "protocol": "mcp/http",
        "capabilities": {
            "tools": True,
            "resources": False,
            "prompts": False
        },
        "vendor": {
            "name": "FFmpeg MCP",
            "url": "https://github.com/yourusername/ffmpeg-mcp"
        }
    }

# ============================================================================
# MCP ENDPOINT 2: Tool Discovery
# ============================================================================

@app.get("/mcp/tools")
async def get_tools():
    """
    Returns the list of available tools according to MCP specification.
    GitHub Copilot uses this to discover what operations this server supports.
    """
    return {
        "tools": [
            {
                "name": "ffmpeg.execute",
                "description": "Execute FFmpeg commands on the host machine and return success or failure with logs",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "FFmpeg command to execute. Must start with 'ffmpeg '"
                        },
                        "workingDir": {
                            "type": "string",
                            "description": "Optional working directory for execution. Defaults to current directory."
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Execution timeout in seconds (default 120, max 600)",
                            "default": 120,
                            "minimum": 1,
                            "maximum": 600
                        }
                    },
                    "required": ["command"]
                }
            }
        ]
    }

# ============================================================================
# Request/Response Models
# ============================================================================

class FFmpegExecuteRequest(BaseModel):
    """Request model for ffmpeg.execute tool"""
    command: str = Field(..., description="FFmpeg command to execute")
    workingDir: Optional[str] = Field(None, description="Working directory for execution")
    timeout: Optional[int] = Field(None, ge=1, le=21600, description="Timeout in seconds (max 21600, default: unlimited)")

    @validator('command')
    def validate_command(cls, v):
        """Validate that command starts with 'ffmpeg '"""
        if not v.strip().startswith('ffmpeg '):
            raise ValueError("Command must start with 'ffmpeg '")
        return v.strip()

class ToolInvocationRequest(BaseModel):
    """Generic MCP tool invocation request"""
    arguments: Dict[str, Any] = Field(..., description="Tool arguments")

# ============================================================================
# FFmpeg Command Validation and Execution
# ============================================================================

class FFmpegCommandValidator:
    """Validates and sanitizes FFmpeg commands for safe execution"""
    
    # Shell operators that could be used for command injection
    BLOCKED_OPERATORS = ['&&', '||', ';', '|', '>', '<', '`', '$', '$(', '${']
    
    @staticmethod
    def validate_command(command: str) -> tuple[bool, str]:
        """
        Validates FFmpeg command for security concerns.
        
        Returns:
            tuple: (is_valid, error_message)
        """
        # Check if command starts with ffmpeg
        if not command.strip().startswith('ffmpeg '):
            return False, "Command must start with 'ffmpeg '"
        
        # Check for blocked shell operators
        for operator in FFmpegCommandValidator.BLOCKED_OPERATORS:
            if operator in command:
                return False, f"Blocked shell operator detected: {operator}"
        
        # Additional check for newlines which could inject commands
        if '\n' in command or '\r' in command:
            return False, "Newlines are not allowed in commands"
        
        return True, ""
    
    @staticmethod
    def validate_working_dir(working_dir: Optional[str]) -> tuple[bool, str, Optional[str]]:
        """
        Validates and resolves working directory.
        
        Returns:
            tuple: (is_valid, error_message, resolved_path)
        """
        if not working_dir:
            return True, "", os.getcwd()
        
        try:
            # Resolve to absolute path
            resolved = os.path.abspath(working_dir)
            
            # Check if directory exists
            if not os.path.exists(resolved):
                return False, f"Working directory does not exist: {resolved}", None
            
            if not os.path.isdir(resolved):
                return False, f"Working directory is not a directory: {resolved}", None
            
            return True, "", resolved
        except Exception as e:
            return False, f"Invalid working directory: {str(e)}", None


class FFmpegExecutor:
    """Executes FFmpeg commands safely with proper error handling"""
    
    @staticmethod
    def execute(command: str, working_dir: str, timeout: Optional[int]) -> Dict[str, Any]:
        """
        Execute FFmpeg command and capture output.
        
        Args:
            command: The FFmpeg command to execute
            working_dir: Working directory for execution
            timeout: Timeout in seconds
            
        Returns:
            dict: Execution result with success status, exit code, and logs
        """
        logger.info(f"Executing FFmpeg command: {command[:100]}...")
        logger.info(f"Working directory: {working_dir}")
        logger.info(f"Timeout: {timeout if timeout is not None else 'unlimited'}s")
        try:
            # Execute command with or without timeout
            run_kwargs = dict(
                args=command,
                shell=True,  # Required for Windows to handle paths correctly
                cwd=working_dir,
                capture_output=True,
                text=True
            )
            if timeout is not None:
                run_kwargs['timeout'] = timeout
            result = subprocess.run(**run_kwargs)
            
            # Prepare response
            response = {
                "success": result.returncode == 0,
                "exitCode": result.returncode,
                "logs": {
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            }
            
            if result.returncode != 0:
                response["error"] = f"FFmpeg command failed with exit code {result.returncode}"
                logger.warning(f"Command failed with exit code {result.returncode}")
            else:
                logger.info("Command executed successfully")
            
            return response
            
        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after {timeout if timeout is not None else 'unlimited'} seconds"
            logger.error(error_msg)
            return {
                "success": False,
                "exitCode": -1,
                "logs": {
                    "stdout": "",
                    "stderr": error_msg
                },
                "error": error_msg
            }
            
        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                "success": False,
                "exitCode": -1,
                "logs": {
                    "stdout": "",
                    "stderr": error_msg
                },
                "error": error_msg
            }

# ============================================================================
# MCP ENDPOINT 3: Tool Invocation
# ============================================================================

@app.post("/mcp/tools/{tool_name}/invoke")
async def invoke_tool(
    tool_name: str = Path(..., description="Name of the tool to invoke"),
    request: ToolInvocationRequest = None
):
    """
    Invokes a tool according to MCP specification.
    This is the main endpoint where GitHub Copilot sends execution requests.
    
    Args:
        tool_name: The name of the tool to invoke (e.g., "ffmpeg.execute")
        request: Tool invocation request with arguments
    """
    logger.info(f"Tool invocation request: {tool_name}")
    
    # Only support ffmpeg.execute tool
    if tool_name != "ffmpeg.execute":
        raise HTTPException(
            status_code=404,
            detail=f"Tool not found: {tool_name}"
        )
    
    try:
        # Parse and validate arguments
        args = FFmpegExecuteRequest(**request.arguments)
        
        # Validate command
        is_valid, error_msg = FFmpegCommandValidator.validate_command(args.command)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Validate working directory
        is_valid, error_msg, resolved_dir = FFmpegCommandValidator.validate_working_dir(args.workingDir)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Execute command
        result = FFmpegExecutor.execute(
            command=args.command,
            working_dir=resolved_dir,
            timeout=args.timeout if args.timeout is not None else 21600
        )
        
        # Return MCP-compliant response
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"FFmpeg execution {'succeeded' if result['success'] else 'failed'}"
                }
            ],
            "result": result
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# ============================================================================
# Health Check Endpoint (Non-MCP, for monitoring)
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring server status"""
    return {"status": "healthy", "service": "ffmpeg-mcp-server"}

# ============================================================================
# Server Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Server configuration
    HOST = "0.0.0.0"  # Listen on all interfaces
    PORT = 8765  # Default MCP server port
    
    logger.info(f"Starting FFmpeg MCP Server on {HOST}:{PORT}")
    logger.info("MCP Endpoints:")
    logger.info(f"  - POST http://localhost:{PORT}/ (JSON-RPC 2.0 - Main MCP Protocol)")
    logger.info(f"  - GET  http://localhost:{PORT}/mcp (REST - For testing)")
    logger.info(f"  - GET  http://localhost:{PORT}/mcp/tools (REST - For testing)")
    logger.info(f"  - POST http://localhost:{PORT}/mcp/tools/{{toolName}}/invoke (REST - For testing)")
    
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info"
    )
