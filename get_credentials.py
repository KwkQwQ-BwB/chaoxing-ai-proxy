"""
超星学习通 AI 助教 / 萤火虫 AI 凭证获取工具
支持：
1. 访客模式（免登录，快速生成可用凭证）
2. 账号登录模式（AES-CBC 加密登录，获取用户 Cookie 与各课程 AI 助教参数）
"""

import base64
import json
import os
import re
import sys
import time
import uuid
import requests

# ==================== 超星 AES-CBC 加密 (兼容 cryptography 与 pycryptodome) ====================
AES_KEY = b"u2oh6Vu^HWe4_AES"
AES_IV = AES_KEY

def encrypt_aes(text: str) -> str:
    """超星专用 AES-CBC 加密算法"""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(text.encode("utf-8")) + padder.finalize()
        cipher = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV))
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded_data) + encryptor.finalize()
        return base64.b64encode(encrypted).decode("utf-8")
    except ImportError:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        padded = pad(text.encode("utf-8"), AES.block_size)
        encrypted = cipher.encrypt(padded)
        return base64.b64encode(encrypted).decode("utf-8")

class ChaoxingAuth:
    """超星认证与凭证管理类"""

    DEFAULT_UNIT_ID = "347810"
    DEFAULT_ROBOT_ID = "999e575daa4646c8812b477a0f75f62b"

    def __init__(self, phone: str = None, password: str = None):
        self.phone = phone
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://robot.chaoxing.com/chat",
            "Origin": "https://robot.chaoxing.com"
        })
        self.is_logged_in = False
        self.user_info = {}

    def login(self, phone: str = None, password: str = None) -> bool:
        """使用手机号和密码进行 AES-CBC 登录"""
        phone = phone or self.phone
        password = password or self.password
        if not phone or not password:
            print("[Auth] 未提供手机号或密码，跳过登录。")
            return False

        print(f"[Auth] 正在登录超星学习通账号: {phone} ...")
        # 1. 预请求获取基础 Cookie
        self.session.get(
            "https://passport2.chaoxing.com/login?loginType=1&newversion=true&fid=-1&refer=http%3A%2F%2Fi.chaoxing.com",
            timeout=10
        )

        # 2. 发送加密登录请求
        login_url = "http://passport2.chaoxing.com/fanyalogin"
        data = {
            "fid": "-1",
            "uname": encrypt_aes(phone),
            "password": encrypt_aes(password),
            "refer": "http%3A%2F%2Fi.chaoxing.com",
            "t": "true",
            "forbidotherlogin": "0"
        }
        resp = self.session.post(login_url, data=data, timeout=15)
        res = resp.json()

        if res.get("status"):
            uid = self.session.cookies.get("_uid") or self.session.cookies.get("UID")
            print(f"[Auth] 登录成功！用户 UID: {uid}")
            self.is_logged_in = True
            self.user_info = {
                "uid": uid,
                "d": self.session.cookies.get("_d"),
                "vc3": self.session.cookies.get("vc3")
            }
            return True
        else:
            print(f"[Auth] 登录失败: {res.get('msg2', res.get('mes', '未知错误'))}")
            return False

    def get_courses(self) -> list:
        """获取当前账号的所有课程列表"""
        if not self.is_logged_in:
            print("[Auth] 获取课程列表需要先登录账号。")
            return []

        url = f"http://mooc2-ans.chaoxing.com/visit/courses/list?v={int(time.time()*1000)}&rss=1&start=0&size=500"
        r = self.session.get(url, timeout=15)
        pattern = r'<a[^>]*href="(https?://[^"]*stucoursemiddle[^"]+)"[^>]*>.*?<span[^>]*title="([^"]+)"[^>]*>'
        matches = re.findall(pattern, r.text, re.S)

        courses = []
        for link, name in matches:
            cid_m = re.search(r'courseid=(\d+)', link)
            clid_m = re.search(r'clazzid=(\d+)', link)
            cpi_m = re.search(r'cpi=(\d+)', link)
            courses.append({
                "name": name,
                "url": link,
                "courseId": cid_m.group(1) if cid_m else None,
                "clazzId": clid_m.group(1) if clid_m else None,
                "cpi": cpi_m.group(1) if cpi_m else None,
            })
        return courses

    def get_course_ai_params(self, course: dict) -> dict:
        """访问课程主页并提取 AI 助教所需参数 (courseId, clazzId, cpi, enc, ut 等)"""
        if not self.is_logged_in or not course.get("url"):
            return {}

        resp = self.session.get(course["url"], timeout=15)
        html = resp.text

        def find_val(name):
            m = re.search(rf'(?:name|id)=["\']?{name}["\']?\s+value=["\']([^"\']+)["\']', html, re.I)
            if not m:
                m = re.search(rf'value=["\']([^"\']+)["\']\s+(?:name|id)=["\']?{name}["\']?', html, re.I)
            return m.group(1) if m else ""

        course_id = find_val("courseid") or find_val("courseId") or course.get("courseId")
        clazz_id = find_val("clazzid") or find_val("classId") or course.get("clazzId")
        cpi = find_val("cpi") or course.get("cpi")
        fid = find_val("fid") or self.DEFAULT_UNIT_ID
        enc = find_val("enc")

        workbench_url = f"http://mooc1.chaoxing.com/course-ans/ai/getStuAiWorkBench?courseId={course_id}&clazzId={clazz_id}&cpi={cpi}&ut=s"

        return {
            "courseName": course.get("name"),
            "courseId": course_id,
            "clazzId": clazz_id,
            "cpi": cpi,
            "fid": fid,
            "enc": enc,
            "workbenchUrl": workbench_url
        }

    def fetch_ai_credentials(self, unit_id: str = None, robot_id: str = None, scene: str = "", course_id: str = "") -> dict:
        """
        获取用于 WebSocket 通信的完整凭证
        :param unit_id: 学校/机构 ID (默认: 347810)
        :param robot_id: 智能体 ID (默认: 999e575daa4646c8812b477a0f75f62b)
        :param scene: 场景，课程场景传 "course"，通用场景传 ""
        :param course_id: 课程 ID (可选)
        :return: 包含 visitorId, conversationId, visitorVc, wsUrl 的字典
        """
        unit_id = str(unit_id or self.DEFAULT_UNIT_ID)
        robot_id = str(robot_id or self.DEFAULT_ROBOT_ID)
        visitor_id = uuid.uuid4().hex

        # 1. 建立访客 Cookie 会话
        self.session.post(
            "https://robot.chaoxing.com/v1/front/chat/initCookie",
            json={"visitorId": visitor_id, "location": ""},
            timeout=10
        )

        # 2. 查询智能体详情 (获取实际绑定的 robotId 与配置)
        try:
            r_info = self.session.get(
                f"https://robot.chaoxing.com/v1/front/robotInfo?unitId={unit_id}&robotId={robot_id}",
                timeout=10
            )
            if r_info.status_code == 200:
                robot_data = r_info.json().get("data") or {}
                actual_robot_id = robot_data.get("robotId") or robot_id
            else:
                actual_robot_id = robot_id
        except Exception:
            actual_robot_id = robot_id

        # 3. 申请对话会话 (visitor/apply)
        apply_params = {
            "visitorId": visitor_id,
            "unitId": unit_id,
            "channel": "WEB",
            "robotId": actual_robot_id,
            "referUrl": "https://robot.chaoxing.com/chat",
            "scene": scene,
        }
        if self.is_logged_in and self.user_info.get("uid"):
            apply_params["uid"] = self.user_info["uid"]
            apply_params["d"] = self.user_info.get("d", "")
            apply_params["vc3"] = self.user_info.get("vc3", "")
        if course_id:
            apply_params["courseId"] = course_id

        r_apply = self.session.get(
            "https://robot.chaoxing.com/v1/front/chat/visitor/apply",
            params=apply_params,
            timeout=10
        )
        apply_data = r_apply.json()
        cvs_info = apply_data.get("cvsInfo") or {}

        actual_visitor_id = apply_data.get("visitorId", visitor_id)
        conversation_id = cvs_info.get("conversationId")
        visitor_vc = apply_data.get("visitorVc")

        # 4. 获取支持的大模型列表
        models = []
        try:
            r_models = self.session.get(
                "https://robot.chaoxing.com/v1/front/llm/getModelSettingInfo",
                params={
                    "unitId": unit_id,
                    "robotId": actual_robot_id,
                    "visitorId": actual_visitor_id,
                    "conversationId": conversation_id
                },
                timeout=10
            )
            if r_models.status_code == 200:
                models_data = r_models.json().get("data") or {}
                models = models_data.get("switchModelList", [])
        except Exception:
            pass

        # 5. 构造标准 WebSocket 连接 URL
        ws_url = (
            f"wss://robot.chaoxing.com/v1/ws/chat/{unit_id}/visitor?"
            f"userId={actual_visitor_id}&channel=WEB&conversationId={conversation_id}&"
            f"robotId={actual_robot_id}&visitorVc={visitor_vc}&scene={scene}&lang=zh-CN&isLLMPlanning=0"
        )

        credentials = {
            "unitId": unit_id,
            "robotId": actual_robot_id,
            "visitorId": actual_visitor_id,
            "conversationId": conversation_id,
            "visitorVc": visitor_vc,
            "scene": scene,
            "courseId": course_id,
            "wsUrl": ws_url,
            "models": models,
            "cookies": self.session.cookies.get_dict(),
            "timestamp": int(time.time())
        }

        return credentials

def main():
    print("=" * 60)
    print("      超星学习通 AI 助教 / 萤火虫 AI 凭证获取工具")
    print("=" * 60)

    auth = ChaoxingAuth()

    phone = os.environ.get("CHAOXING_PHONE")
    password = os.environ.get("CHAOXING_PASSWORD")

    if phone and password:
        print("[Mode] 检测到环境变量配置，使用账号登录模式...")
        if auth.login(phone, password):
            print("\n[Courses] 正在提取课程 AI 助教信息...")
            courses = auth.get_courses()
            print(f"找到 {len(courses)} 门课程:")
            for i, c in enumerate(courses[:5], 1):
                ai_params = auth.get_course_ai_params(c)
                print(f"  [{i}] {c['name']} (CourseID: {c['courseId']}, AI工作台: {ai_params.get('workbenchUrl')})")
    else:
        print("[Mode] 未配置环境变量账号，使用访客免登录模式...")

    print("\n[Credentials] 正在获取萤火虫 AI / 对话凭证...")
    creds = auth.fetch_ai_credentials()

    print("\n" + "=" * 25 + " 凭证信息 " + "=" * 25)
    print(json.dumps({
        "unitId": creds["unitId"],
        "robotId": creds["robotId"],
        "visitorId": creds["visitorId"],
        "conversationId": creds["conversationId"],
        "visitorVc": creds["visitorVc"],
        "wsUrl": creds["wsUrl"],
        "availableModels": [m.get("modelName") for m in creds.get("models", [])]
    }, indent=2, ensure_ascii=False))

    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2, ensure_ascii=False)
    print(f"\n[Success] 凭证已完整保存至: {output_file}")

if __name__ == "__main__":
    main()
