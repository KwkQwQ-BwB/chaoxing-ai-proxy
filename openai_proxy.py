"""
超星学习通 AI 助教 / 萤火虫 AI -> OpenAI 兼容反向代理服务
将超星 WebSocket 对话接口封装为标准 OpenAI API (/v1/chat/completions, /v1/models)
可无缝接入 NextChat, Chatbox, Cherry Studio, LibreChat, Cursor, OpenAI SDK 等第三方客户端。
"""

import asyncio
import json
import os
import sys
import time
import uuid
from typing import List, Optional, Union
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from chaoxing_ai import ChaoxingAIClient
from get_credentials import ChaoxingAuth

# ==================== FastAPI 应用初始化 ====================
app = FastAPI(
    title="ChaoXing AI / Firefly OpenAI Proxy",
    description="超星学习通 AI 助教 / 萤火虫 AI 反向代理服务（OpenAI 兼容格式）",
    version="1.0.0"
)

# 允许跨域请求（方便 Web 客户端调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化全局超星客户端
auth = ChaoxingAuth(
    phone=os.environ.get("CHAOXING_PHONE"),
    password=os.environ.get("CHAOXING_PASSWORD")
)
if os.environ.get("CHAOXING_PHONE") and os.environ.get("CHAOXING_PASSWORD"):
    auth.login()

client = ChaoxingAIClient(auth=auth)

# 可选 API Key 认证（留空则不校验）
API_KEY = os.environ.get("PROXY_API_KEY", "")

# ==================== 数据模型定义 ====================
class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None

class ChatCompletionRequest(BaseModel):
    model: Optional[str] = "huiya-chat-34-q4"
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None

# ==================== 认证校验 ====================
def verify_api_key(authorization: Optional[str] = Header(None)):
    if not API_KEY:
        return True
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    token = authorization.replace("Bearer ", "").strip()
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True

# ==================== 接口路由 ====================
@app.get("/")
def index():
    return {
        "status": "online",
        "service": "ChaoXing AI OpenAI-Compatible Proxy",
        "endpoints": ["/v1/models", "/v1/chat/completions"],
        "docs": "/docs"
    }

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/v1/models")
def list_models(authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)
    if not client.available_models:
        client.refresh_credentials()

    models_data = []
    # 默认/通用别名
    models_data.append({
        "id": "chaoxing-firefly",
        "object": "model",
        "created": 1725800000,
        "owned_by": "chaoxing",
        "permission": [],
        "root": "chaoxing-firefly",
        "parent": None
    })

    for m in client.available_models:
        name = m.get("modelName")
        if name:
            models_data.append({
                "id": name,
                "object": "model",
                "created": 1725800000,
                "owned_by": m.get("modelFactory", "chaoxing"),
                "permission": [],
                "root": name,
                "parent": None
            })

    return {
        "object": "list",
        "data": models_data
    }

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, authorization: Optional[str] = Header(None)):
    verify_api_key(authorization)

    if not request.messages:
        raise HTTPException(status_code=400, detail="Messages list cannot be empty")

    # 提取最后一条用户消息，并将上下文拼装
    user_prompt = request.messages[-1].content
    if len(request.messages) > 1:
        history_lines = []
        for msg in request.messages[:-1]:
            role_tag = "用户" if msg.role == "user" else "助手" if msg.role == "assistant" else "系统"
            history_lines.append(f"{role_tag}: {msg.content}")
        history_lines.append(f"用户: {user_prompt}")
        prompt_with_history = "\n".join(history_lines)
    else:
        prompt_with_history = user_prompt

    chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created_time = int(time.time())
    model_name = request.model or "huiya-chat-34-q4"

    # 流式响应 (SSE)
    if request.stream:
        async def event_generator():
            async for chunk in client.chat_stream(prompt_with_history, model=model_name):
                if chunk["type"] == "delta":
                    delta_payload = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model_name,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "role": "assistant" if not delta_payload_sent else None,
                                    "content": chunk["content"]
                                },
                                "finish_reason": None
                            }
                        ]
                    }
                    yield f"data: {json.dumps(delta_payload, ensure_ascii=False)}\n\n"
                elif chunk["type"] == "done":
                    done_payload = {
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": model_name,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop"
                            }
                        ]
                    }
                    yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"

            delta_payload_sent = False

        delta_payload_sent = False
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # 非流式响应 (直接返回完整 JSON)
    else:
        full_content = ""
        total_tokens = 0
        async for chunk in client.chat_stream(prompt_with_history, model=model_name):
            if chunk["type"] == "delta":
                full_content += chunk["content"]
            elif chunk["type"] == "done":
                if chunk.get("content"):
                    full_content = chunk["content"]
                total_tokens = chunk.get("total_tokens", len(full_content))

        return {
            "id": chat_id,
            "object": "chat.completion",
            "created": created_time,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": len(prompt_with_history),
                "completion_tokens": len(full_content),
                "total_tokens": total_tokens or (len(prompt_with_history) + len(full_content))
            }
        }

def start_server(host: str = "0.0.0.0", port: int = 8000):
    print("=" * 60)
    print(f"  超星 AI / 萤火虫 OpenAI 兼容反代服务已启动: http://{host}:{port}")
    print(f"  - 接口地址: http://127.0.0.1:{port}/v1")
    print(f"  - 模型列表: http://127.0.0.1:{port}/v1/models")
    print(f"  - 对话接口: http://127.0.0.1:{port}/v1/chat/completions")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    start_server(port=port)
