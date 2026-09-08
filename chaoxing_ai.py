"""
超星学习通 AI 助教 / 萤火虫 AI 核心客户端
支持：
- 双向 WebSocket 流式通信
- 多大模型切换 (汇雅、DeepSeek-V4、豆包等)
- 深度思考 (Thinking / Reasoning) 过程捕获
- 自动保活心跳 (KeepAlive)
"""

import asyncio
import json
import time
import uuid
import requests
import websockets
from get_credentials import ChaoxingAuth

class ChaoxingAIClient:
    """超星 AI 助教 / 萤火虫 AI 客户端"""

    DEFAULT_UNIT_ID = "347810"
    DEFAULT_ROBOT_ID = "999e575daa4646c8812b477a0f75f62b"

    def __init__(self, auth: ChaoxingAuth = None, unit_id: str = None, robot_id: str = None, model: str = None):
        self.auth = auth or ChaoxingAuth()
        self.unit_id = str(unit_id or self.DEFAULT_UNIT_ID)
        self.robot_id = str(robot_id or self.DEFAULT_ROBOT_ID)
        self.active_model_name = model or "huiya-chat-34-q4"
        self.active_model_id = None
        self.credentials = {}
        self.available_models = []

    def refresh_credentials(self, scene: str = "", course_id: str = "") -> dict:
        """获取或刷新会话凭证"""
        self.credentials = self.auth.fetch_ai_credentials(
            unit_id=self.unit_id,
            robot_id=self.robot_id,
            scene=scene,
            course_id=course_id
        )
        self.unit_id = self.credentials["unitId"]
        self.robot_id = self.credentials["robotId"]
        self.available_models = self.credentials.get("models", [])

        # 匹配默认模型 ID
        for m in self.available_models:
            if m.get("modelName") == self.active_model_name or str(m.get("modelId")) == str(self.active_model_name):
                self.active_model_id = m.get("modelId")
                self.active_model_name = m.get("modelName")
                break
        if not self.active_model_id and self.available_models:
            self.active_model_id = self.available_models[0].get("modelId")
            self.active_model_name = self.available_models[0].get("modelName")

        return self.credentials

    def switch_model(self, model_name_or_id: str | int) -> bool:
        """切换对话大模型"""
        if not self.credentials:
            self.refresh_credentials()

        target_model = None
        for m in self.available_models:
            if str(m.get("modelId")) == str(model_name_or_id) or m.get("modelName") == str(model_name_or_id):
                target_model = m
                break

        if not target_model:
            print(f"[ChaoxingAI] 未找到指定模型: {model_name_or_id}，保持当前模型。")
            return False

        self.active_model_id = target_model.get("modelId")
        self.active_model_name = target_model.get("modelName")

        # 同步切换配置到超星后端
        save_payload = {
            "unitId": self.unit_id,
            "visitorId": self.credentials["visitorId"],
            "conversationId": self.credentials["conversationId"],
            "modelInfo": {
                "modelId": self.active_model_id,
                "modelName": self.active_model_name,
                "ifOpenStageThinkProcess": target_model.get("ifOpenStageThinkProcess", 1)
            }
        }
        try:
            r = self.auth.session.post(
                "https://robot.chaoxing.com/v1/front/chat/saveConversationModel",
                json=save_payload,
                timeout=10
            )
            return r.status_code == 200
        except Exception as e:
            print(f"[ChaoxingAI] 切换模型失败: {e}")
            return False

    async def chat_stream(self, prompt: str, model: str = None, timeout: int = 45):
        """
        流式对话异步生成器
        :param prompt: 用户输入内容
        :param model: 指定模型名称或 ID (可选)
        :param timeout: 超时时间 (秒)
        :yield: 事件字典，如 {"type": "thinking"|"delta"|"done", "content": "..."}
        """
        if not self.credentials:
            self.refresh_credentials()

        if model and (model != self.active_model_name and model != self.active_model_id):
            self.switch_model(model)

        ws_url = self.credentials.get("wsUrl")
        if not ws_url:
            self.refresh_credentials()
            ws_url = self.credentials["wsUrl"]

        async with websockets.connect(
            ws_url,
            origin="https://robot.chaoxing.com",
            open_timeout=30,
            ping_interval=20,
            ping_timeout=20
        ) as ws:
            # 构造上行消息包
            now_ms = int(time.time() * 1000)
            payload = {
                "msgTimeId": now_ms,
                "time": now_ms,
                "direction": "IN",
                "messageType": "TEXT",
                "communicateType": "DATA",
                "lang": "zh-CN",
                "msg": {
                    "channel": "WEB",
                    "question": prompt,
                    "visibleQuestion": prompt,
                    "questionType": "TEXT",
                    "chatModel": self.active_model_name,
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

            await ws.send(json.dumps(payload))

            full_content = ""
            total_tokens = 0
            cost_time = 0

            while True:
                try:
                    res_raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    msg_obj = json.loads(res_raw)

                    # 1. 深度思考 / Agent 状态事件
                    if msg_obj.get("agent_event"):
                        event_data = msg_obj["agent_event"]
                        desc = msg_obj.get("meta", {}).get("description", "")
                        yield {
                            "type": "thinking",
                            "event": event_data.get("event"),
                            "content": desc
                        }

                    # 2. 增量文本推送 (MACHINE_READ / LLM_STREAM / MIX)
                    if msg_obj.get("renderType") in ["MACHINE_READ", "LLM_STREAM", "MIX"]:
                        ans = (msg_obj.get("msg") or {}).get("answer") or ""
                        if ans and ans != full_content:
                            if ans.startswith(full_content):
                                delta = ans[len(full_content):]
                            else:
                                delta = ans
                            full_content = ans
                            yield {
                                "type": "delta",
                                "content": delta
                            }

                    # 3. 直接 Answer 兜底
                    if msg_obj.get("answer"):
                        ans_direct = msg_obj.get("answer")
                        if isinstance(ans_direct, str) and not ans_direct.startswith("{"):
                            if ans_direct != full_content:
                                yield {
                                    "type": "delta",
                                    "content": ans_direct
                                }
                                full_content += ans_direct

                    # 4. Token 与性能统计
                    if "answer" in msg_obj:
                        ans_val = msg_obj["answer"]
                        if isinstance(ans_val, str) and ans_val.startswith("{"):
                            try:
                                ans_json = json.loads(ans_val)
                                total_tokens = ans_json.get("totalTokens", total_tokens)
                                cost_time = ans_json.get("costTime", cost_time)
                            except Exception:
                                pass

                    # 5. 结束标志 (option: 2003 / "gb" / "FINISH")
                    if msg_obj.get("option") in [2003, "gb", "FINISH"] or msg_obj.get("communicateType") == "REPLY_FINISH":
                        break

                except asyncio.TimeoutError:
                    break

            yield {
                "type": "done",
                "content": full_content,
                "total_tokens": total_tokens,
                "cost_time": cost_time
            }

    def chat(self, prompt: str, model: str = None) -> str:
        """同步阻塞式对话"""
        async def _run():
            full_text = ""
            async for chunk in self.chat_stream(prompt, model=model):
                if chunk["type"] == "delta":
                    full_text += chunk["content"]
                elif chunk["type"] == "done":
                    if chunk["content"]:
                        full_text = chunk["content"]
            return full_text

        return asyncio.run(_run())

def main():
    print("=" * 60)
    print("        超星学习通 AI 助教 / 萤火虫 AI 对话客户端")
    print("=" * 60)

    client = ChaoxingAIClient()
    print("[1] 正在初始化会话凭证与大模型列表...")
    client.refresh_credentials()

    models = [m.get("modelName") for m in client.available_models]
    print(f"[2] 可用模型: {models}")
    print(f"[3] 当前使用模型: {client.active_model_name}")

    test_prompt = "请简要解释什么是二分查找，并给出时间复杂度"
    print(f"\n[4] 发送提问: {test_prompt}")
    print("\n--- AI 实时回答 ---")

    async def stream_output():
        async for chunk in client.chat_stream(test_prompt):
            if chunk["type"] == "thinking" and chunk["content"]:
                print(f"[思考中: {chunk['content']}]")
            elif chunk["type"] == "delta":
                print(chunk["content"], end="", flush=True)
            elif chunk["type"] == "done":
                print(f"\n\n[回答完成 | Tokens: {chunk['total_tokens']} | 耗时: {chunk['cost_time']}ms]")

    asyncio.run(stream_output())

if __name__ == "__main__":
    main()
