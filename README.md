# 超星学习通 AI 助教 & 萤火虫 AI 逆向工程与 OpenAI 兼容反代服务

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![WebSocket](https://img.shields.io/badge/WebSocket-Supported-orange.svg)](https://websockets.readthedocs.io/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

本项目深度逆向了**超星学习通学生端 AI 助教工作台**（`http://mooc1.chaoxing.com/course-ans/ai/getStuAiWorkBench`）与**超星萤火虫 AI 智能体中台**（`https://robot.chaoxing.com`）的通信协议与鉴权机制，并提供了：

1. **一键凭证提取工具** (`get_credentials.py`)：支持免登录访客模式与 AES-CBC 账号加密登录模式，自动获取 WebSocket 对话凭证与课程 AI 助教参数。
2. **Python 对话核心 SDK** (`chaoxing_ai.py`)：支持双向 WebSocket 流式通信、模型热切换、Agent 深度思考过程捕获与 Token 统计。
3. **OpenAI 兼容反向代理服务** (`openai_proxy.py`)：将超星 WebSocket 对话接口无缝转换为标准 OpenAI `/v1/chat/completions` 与 `/v1/models` 接口，完美适配各类第三方 AI 客户端（NextChat、Cherry Studio、Chatbox、Open WebUI、Cursor、OpenAI 官方 SDK 等）。

> ⚠️ **声明**：本项目仅供计算机网络协议分析、API 逆向工程与学术技术交流研究使用。请遵守平台相关服务协议，切勿用于商业用途或违规行为。

---

## 目录

- [一、 架构与通信原理](#一-架构与通信原理)
- [二、 快速开始与环境配置](#二-快速开始与环境配置)
- [三、 凭证获取指南 (`get_credentials.py`)](#三-凭证获取指南-get_credentialspy)
  - [3.1 访客免登录模式](#31-访客免登录模式)
  - [3.2 账号密码登录模式](#32-账号密码登录模式)
  - [3.3 课程 AI 工作台参数解析](#33-课程-ai-工作台参数解析)
- [四、 核心协议规范 (API Specification)](#四-核心协议规范-api-specification)
  - [4.1 HTTP REST 接口](#41-http-rest-接口)
  - [4.2 WebSocket 实时流式协议](#42-websocket-实时流式协议)
- [五、 OpenAI 标准反代搭建教程 (`openai_proxy.py`)](#五-openai-标准反代搭建教程-openai_proxypy)
  - [5.1 一键启动反代服务器](#51-一键启动反代服务器)
  - [5.2 第三方客户端配置教程](#52-第三方客户端配置教程)
    - [1. NextChat (ChatGPT-Next-Web)](#1-nextchat-chatgpt-next-web)
    - [2. Cherry Studio / Chatbox](#2-cherry-studio--chatbox)
    - [3. OpenAI 官方 Python SDK](#3-openai-官方-python-sdk)
    - [4. cURL 命令行测试](#4-curl-命令行测试)
- [六、 项目结构说明](#六-项目结构说明)

---

## 一、 架构与通信原理

超星学习通课程页面中的 **AI 助教工作台** 与 **萤火虫 AI 机器人** 的底层架构关系如下：

```
+-------------------------------------------------------------------------------+
|                        客户端 (Client / Third-Party Web)                       |
|   (NextChat / Cherry Studio / Chatbox / Python SDK / Cursor / Browser)         |
+-------------------------------------------------------------------------------+
                                       │
                         HTTP / SSE (/v1/chat/completions)
                                       ▼
+-------------------------------------------------------------------------------+
|                  OpenAI 兼容反向代理服务 (openai_proxy.py)                     |
|           将 OpenAI 标准请求转换为超星 WebSocket 格式并分发流式响应              |
+-------------------------------------------------------------------------------+
                                       │
                      WebSocket (wss://robot.chaoxing.com)
                                       ▼
+-------------------------------------------------------------------------------+
|                       超星萤火虫 AI 中台 (robot.chaoxing.com)                   |
|  - 访客初始化: /v1/front/chat/initCookie                                       |
|  - 会话申请:   /v1/front/chat/visitor/apply -> conversationId, visitorVc      |
|  - 模型管理:   /v1/front/llm/getModelSettingInfo / saveConversationModel       |
|  - WebSocket长连: /v1/ws/chat/{unitId}/visitor                                |
+-------------------------------------------------------------------------------+
           ▲                                                   ▲
           │ (包含课程 courseId, clazzId, cpi, ut)              │ (机构知识库 / 大模型)
+--------------------------------------+      +---------------------------------+
| 课程 AI 助教工作台 (getStuAiWorkBench)|      | 大模型底座 (汇雅/DeepSeek/豆包) |
+--------------------------------------+      +---------------------------------+
```

### 核心通信链路：
1. **握手初始化**：通过 `POST /v1/front/chat/initCookie` 与 `GET /v1/front/chat/visitor/apply` 获取会话凭证（`conversationId`, `visitorVc`, `visitorId`）。
2. **大模型协商**：通过 `POST /v1/front/chat/saveConversationModel` 指定底层推理大模型（如 `huiya-chat-34-q4`、`deepseek-v4-flash-0731`、`doubao-1-5-pro-32k-250115`）。
3. **全双工 WebSocket 长连接**：与 `wss://robot.chaoxing.com/v1/ws/chat/{unitId}/visitor` 建立加密连接，发送结构化问答帧，服务端通过增量数据包（`MACHINE_READ` / `LLM_STREAM`）下发思考过程与答案。
4. **SSE 流式转换**：反代服务接收 WebSocket 帧后实时组装为标准 OpenAI SSE 格式（`data: {"choices": [{"delta": {"content": "..."}}]}`）推送给前端。

---

## 二、 快速开始与环境配置

### 2.1 克隆仓库与安装依赖

本项目依赖轻量，兼容 Python 3.10+：

```bash
# 安装必要依赖
pip install requests websockets fastapi uvicorn cryptography
```

---

## 三、 凭证获取指南 (`get_credentials.py`)

运行凭证获取工具即可生成包含完整 WebSocket 握手参数的 JSON 文件：

```bash
python get_credentials.py
```

### 3.1 访客免登录模式

如果未提供账号密码，脚本将自动以**匿名访客模式**生成凭证。输出格式如下：

```json
{
  "unitId": "347810",
  "robotId": "dd3d60ca12534592ac57bcef56f9a1a0",
  "visitorId": "1bea45601f2c4e68ab219eb25524d174",
  "conversationId": "8c060416cde79d8ee205a462e4ccb5d5260924",
  "visitorVc": "7327c5c39ee6f8f2babd9484a8291c10",
  "wsUrl": "wss://robot.chaoxing.com/v1/ws/chat/347810/visitor?userId=1bea45601f2c4e68ab219eb25524d174&channel=WEB&conversationId=8c060416cde79d8ee205a462e4ccb5d5260924&robotId=dd3d60ca12534592ac57bcef56f9a1a0&visitorVc=7327c5c39ee6f8f2babd9484a8291c10&scene=&lang=zh-CN&isLLMPlanning=0",
  "availableModels": [
    "huiya-chat-34-q4",
    "deepseek-v4-flash-0731",
    "doubao-1-5-pro-32k-250115"
  ]
}
```

凭证将自动保存到项目目录下的 `credentials.json` 中。

### 3.2 账号密码登录模式

如需绑定个人账号、调用个人选修课程的专有 AI 助教知识库，可设置环境变量或在脚本中配置手机号和密码：

```bash
# Windows PowerShell
$env:CHAOXING_PHONE="你的手机号"
$env:CHAOXING_PASSWORD="你的密码"

# Linux / macOS
export CHAOXING_PHONE="你的手机号"
export CHAOXING_PASSWORD="你的密码"
```

#### 超星 AES-CBC 加密规范：
- **算法**：`AES-CBC`
- **Key (密钥)**：`u2oh6Vu^HWe4_AES` (16 字节)
- **IV (向量)**：与 Key 相同
- **填充方式**：`PKCS7`
- **输出格式**：`Base64`

### 3.3 课程 AI 工作台参数解析

登录成功后，脚本会自动拉取课程列表，并提取课程对应的 AI 助教工作台地址：
- 格式：`http://mooc1.chaoxing.com/course-ans/ai/getStuAiWorkBench?courseId={courseId}&clazzId={clazzId}&cpi={cpi}&ut=s`
- 当 `scene=course` 且附带 `courseId` 时，萤火虫中台将自动关联该课程的专属教案、课件知识库进行针对性答疑。

---

## 四、 核心协议规范 (API Specification)

### 4.1 HTTP REST 接口

#### 1. 初始化访客 Cookie
- **端点**：`POST https://robot.chaoxing.com/v1/front/chat/initCookie`
- **请求体**：
  ```json
  { "visitorId": "32位十六进制字符串", "location": "" }
  ```
- **响应**：`{"statusCode": 0, "msg": "操作成功", "data": null}`

#### 2. 申请对话会话 (`apply`)
- **端点**：`GET https://robot.chaoxing.com/v1/front/chat/visitor/apply`
- **查询参数**：
  | 参数名 | 类型 | 说明 |
  |---|---|---|
  | `visitorId` | string | 访客唯一 ID |
  | `unitId` | string | 机构/学校 ID (通用默认: `347810`) |
  | `channel` | string | 固定值 `WEB` |
  | `robotId` | string | 智能体 ID (通用默认: `999e575daa4646c8812b477a0f75f62b`) |
  | `referUrl` | string | `https://robot.chaoxing.com/chat` |
  | `scene` | string | 场景标记（课程助教为 `course`，通用为空） |
  | `courseId` | string | 选填，课程 ID |
- **响应示例**：
  ```json
  {
    "cvsInfo": {
      "conversationId": "8c060416cde79d8ee205a462e4ccb5d5260924",
      "chatStatus": 1
    },
    "code": 1,
    "robotId": "dd3d60ca12534592ac57bcef56f9a1a0",
    "visitorVc": "7327c5c39ee6f8f2babd9484a8291c10",
    "visitorId": "1bea45601f2c4e68ab219eb25524d174"
  }
  ```

#### 3. 获取可用大模型列表
- **端点**：`GET https://robot.chaoxing.com/v1/front/llm/getModelSettingInfo`
- **参数**：`unitId`, `robotId`, `visitorId`, `conversationId`
- **返回值**：支持的模型列表（汇雅、DeepSeek、豆包等）及参数。

#### 4. 切换/绑定会话大模型
- **端点**：`POST https://robot.chaoxing.com/v1/front/chat/saveConversationModel`
- **请求体**：
  ```json
  {
    "unitId": "347810",
    "visitorId": "1bea45601f2c4e68ab219eb25524d174",
    "conversationId": "8c060416cde79d8ee205a462e4ccb5d5260924",
    "modelInfo": {
      "modelId": 254,
      "modelName": "deepseek-v4-flash-0731",
      "ifOpenStageThinkProcess": 1
    }
  }
  ```

---

### 4.2 WebSocket 实时流式协议

#### 1. 连接地址
```
wss://robot.chaoxing.com/v1/ws/chat/{unitId}/visitor?userId={visitorId}&channel=WEB&conversationId={conversationId}&robotId={robotId}&visitorVc={visitorVc}&scene=&lang=zh-CN&isLLMPlanning=0
```

#### 2. 心跳维持
每 30 秒向服务端发送一次保活包：
```json
{ "type": "KEEPALIVE" }
```

#### 3. 上行提问消息包 (Client -> Server)
```json
{
  "msgTimeId": 1725800000000,
  "time": 1725800000000,
  "direction": "IN",
  "messageType": "TEXT",
  "communicateType": "DATA",
  "lang": "zh-CN",
  "msg": {
    "channel": "WEB",
    "question": "用Python写一个快速排序算法",
    "visibleQuestion": "用Python写一个快速排序算法",
    "questionType": "TEXT",
    "chatModel": "deepseek-v4-flash-0731",
    "fileInfo": []
  },
  "robot": {
    "type": "",
    "scene": -1,
    "extend": "",
    "subject": "",
    "spage": 1
  },
  "dxNumber": "",
  "d": ""
}
```

#### 4. 下行响应数据包 (Server -> Client)
- **语义/思考过程事件 (`agent_event`)**：
  ```json
  {
    "event_id": "...",
    "agent_event": { "event": "knowledge_question_thought" },
    "meta": { "description": "正在理解问题与规划回复" },
    "type": "SEMANTIC"
  }
  ```
- **增量文本数据帧 (`renderType: MACHINE_READ / LLM_STREAM`)**：
  ```json
  {
    "renderType": "MACHINE_READ",
    "msg": {
      "answer": "以下是用 Python 实现快速排序的代码..."
    },
    "messageId": "..."
  }
  ```
- **性能与 Token 统计包**：
  ```json
  {
    "answer": "{\"costTime\": 1250, \"totalTokens\": 340}"
  }
  ```
- **结束标志**：收到 `option: 2003` 或 `communicateType: "REPLY_FINISH"`。

---

## 五、 OpenAI 标准反代搭建教程 (`openai_proxy.py`)

### 5.1 一键启动反代服务器

直接运行 `openai_proxy.py` 启动本地 API 服务：

```bash
python openai_proxy.py
```

终端将输出启动信息：
```
============================================================
  超星 AI / 萤火虫 OpenAI 兼容反代服务已启动: http://0.0.0.0:8000
  - 接口地址: http://127.0.0.1:8000/v1
  - 模型列表: http://127.0.0.1:8000/v1/models
  - 对话接口: http://127.0.0.1:8000/v1/chat/completions
============================================================
```

> 提示：可通过环境变量 `PORT=9000` 修改端口，或通过 `PROXY_API_KEY=your_key` 设置 API 访问密码。

---

### 5.2 第三方客户端配置教程

#### 1. NextChat (ChatGPT-Next-Web)
- **接口地址 (API Endpoint)**：`http://127.0.0.1:8000`
- **API Key**：随意填写（或填写你设置的 `PROXY_API_KEY`）
- **自定义模型**：输入 `huiya-chat-34-q4,deepseek-v4-flash-0731,doubao-1-5-pro-32k-250115,chaoxing-firefly`

#### 2. Cherry Studio / Chatbox
- **提供商类型**：选择 `OpenAI` 或 `自定义 API`
- **API 域名 / Base URL**：`http://127.0.0.1:8000/v1`
- **API 密钥**：随意填写（如 `sk-chaoxing`）
- **模型**：选择或手动输入 `deepseek-v4-flash-0731` 或 `huiya-chat-34-q4`

#### 3. OpenAI 官方 Python SDK 调用

可以直接使用官方 `openai` 库发起流式调用：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="sk-chaoxing-noneed"  # 任意占位符
)

response = client.chat.completions.create(
    model="deepseek-v4-flash-0731",
    messages=[
        {"role": "user", "content": "用一句话介绍超星学习通"}
    ],
    stream=True
)

for chunk in response:
    content = chunk.choices[0].delta.content
    if content:
        print(content, end="", flush=True)
print()
```

#### 4. cURL 命令行测试

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash-0731",
    "messages": [{"role": "user", "content": "你好，请自我介绍"}],
    "stream": true
  }'
```

---

## 六、 项目结构说明

```
.
├── README.md               # 完整的项目说明与反代教程文档
├── get_credentials.py      # 凭证获取工具 (支持免登录访客与 AES-CBC 账号登录)
├── chaoxing_ai.py          # 超星 AI 对话客户端核心类 (WebSocket / 流式解析)
├── openai_proxy.py         # OpenAI 标准反向代理服务 (FastAPI / Uvicorn)
├── credentials.json        # 自动生成的本地凭证缓存文件
└── chaoxing-api/           # 超星学习通 API 逆向基础库
```

---

## 七、 许可证与免责声明

- 本项目代码遵循 **MIT License** 开源。
- 本项目仅用于计算机网络技术学习与接口逆向协议研究，不针对任何特定商业系统提供商业服务。使用者在使用本工具时应自觉遵守相关服务协议及法律法规。
