#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AstrBot 青龙面板管理插件 v1.3.3
修复目标格式问题，支持多种格式的配置
新增：推送后询问是否推送错误日志详情
"""

import time
import asyncio
import json
import re
import uuid
import datetime
import traceback
from typing import Dict, List, Optional, Tuple, Any, Set
from collections import deque

import httpx

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.message_event_result import MessageChain


# 常量配置
DEFAULT_TIMEOUT = 10
TOKEN_EXPIRE_SECONDS = 6 * 24 * 3600  # 6天

# Cookie 自动保存相关常量
# 默认匹配 key=value;key=value 形式的 Cookie（至少两组键值对）
DEFAULT_COOKIE_REGEX = r"(?:[A-Za-z0-9_\-]+=[^;\s=]+)(?:;\s*[A-Za-z0-9_\-]+=[^;\s=]+)+"
COOKIE_REMARK_TAG = "astrbot_cookie"  # 环境变量备注中的管理标记，用于识别本插件管理的变量


class QinglongAPI:
    """青龙面板 API 封装（异步版本）"""
    
    def __init__(self, host: str, client_id: str, client_secret: str):
        """初始化青龙 API"""
        self.host = host.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.token: Optional[str] = None
        self.token_expire: float = 0
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端（复用连接池）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return self._client
    
    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def get_token(self) -> bool:
        """获取访问令牌"""
        try:
            if self.token and time.time() < self.token_expire:
                return True
            
            client = await self._get_client()
            response = await client.get(
                f"{self.host}/open/auth/token",
                params={"client_id": self.client_id, "client_secret": self.client_secret}
            )
            result = response.json()
            
            if result.get('code') == 200:
                self.token = result['data']['token']
                self.token_expire = time.time() + TOKEN_EXPIRE_SECONDS
                return True
            else:
                logger.error(f"获取token失败: {result.get('message')}")
                return False
        
        except httpx.TimeoutException:
            logger.error("获取token超时，请检查网络连接")
            return False
        except httpx.ConnectError:
            logger.error("无法连接到青龙面板，请检查地址配置")
            return False
        except Exception as e:
            logger.error(f"获取token异常: {e}")
            return False
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    async def _request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict] = None,
        json_data: Any = None
    ) -> Tuple[bool, Any]:
        """统一的请求方法"""
        if not await self.get_token():
            return False, "认证失败"
        
        try:
            client = await self._get_client()
            url = f"{self.host}{endpoint}"
            
            if method.upper() == "GET":
                response = await client.get(url, headers=self._get_headers(), params=params)
            elif method.upper() == "DELETE":
                response = await client.request("DELETE", url, headers=self._get_headers(), json=json_data)
            elif method.upper() == "PUT":
                response = await client.put(url, headers=self._get_headers(), json=json_data)
            else:  # POST
                response = await client.post(url, headers=self._get_headers(), json=json_data)
            
            result = response.json()
            
            if result.get('code') == 200:
                return True, result.get('data', {})
            else:
                return False, result.get('message', '未知错误')
                
        except httpx.TimeoutException:
            return False, "请求超时"
        except httpx.ConnectError:
            return False, "连接失败"
        except Exception as e:
            return False, str(e)
    
    async def get_envs(self, search_value: str = "") -> List[Dict]:
        """获取环境变量列表"""
        params = {"searchValue": search_value} if search_value else None
        success, data = await self._request("GET", "/open/envs", params=params)
        
        if not success:
            return []
        
        if isinstance(data, dict):
            return data.get('data', [])
        return data if isinstance(data, list) else []
    
    async def add_env(self, name: str, value: str, remarks: str = "") -> Tuple[bool, str]:
        """添加环境变量"""
        success, data = await self._request("POST", "/open/envs", json_data=[{"name": name, "value": value, "remarks": remarks}])
        return success, "添加成功" if success else data
    
    async def update_env(self, env_id: int, name: str, value: str, remarks: str = "") -> Tuple[bool, str]:
        """更新环境变量"""
        success, data = await self._request("PUT", "/open/envs", json_data={"id": env_id, "name": name, "value": value, "remarks": remarks})
        return success, "更新成功" if success else data
    
    async def delete_env(self, env_id: int) -> Tuple[bool, str]:
        """删除环境变量"""
        success, data = await self._request("DELETE", "/open/envs", json_data=[env_id])
        return success, "删除成功" if success else data
    
    async def enable_env(self, env_ids: List[int]) -> Tuple[bool, str]:
        """启用环境变量"""
        success, data = await self._request("PUT", "/open/envs/enable", json_data=env_ids)
        return success, "启用成功" if success else data
    
    async def disable_env(self, env_ids: List[int]) -> Tuple[bool, str]:
        """禁用环境变量"""
        success, data = await self._request("PUT", "/open/envs/disable", json_data=env_ids)
        return success, "禁用成功" if success else data
    
    async def get_crons(self, search_value: str = "") -> List[Dict]:
        """获取定时任务列表"""
        params = {"searchValue": search_value} if search_value else None
        success, data = await self._request("GET", "/open/crons", params=params)
        
        if not success:
            return []
        
        if isinstance(data, dict):
            return data.get('data', [])
        return data if isinstance(data, list) else []
    
    async def get_cron_by_id(self, cron_id: int) -> Optional[Dict]:
        """根据ID获取单个任务详情"""
        crons = await self.get_crons()
        for cron in crons:
            if cron.get('id') == cron_id:
                return cron
        return None
    
    async def run_cron(self, cron_ids: List[int]) -> Tuple[bool, str]:
        """执行定时任务"""
        success, data = await self._request("PUT", "/open/crons/run", json_data=cron_ids)
        return success, "执行成功" if success else data
    
    async def stop_cron(self, cron_ids: List[int]) -> Tuple[bool, str]:
        """停止定时任务"""
        success, data = await self._request("PUT", "/open/crons/stop", json_data=cron_ids)
        return success, "停止成功" if success else data
    
    async def enable_cron(self, cron_ids: List[int]) -> Tuple[bool, str]:
        """启用定时任务"""
        success, data = await self._request("PUT", "/open/crons/enable", json_data=cron_ids)
        return success, "启用成功" if success else data
    
    async def disable_cron(self, cron_ids: List[int]) -> Tuple[bool, str]:
        """禁用定时任务"""
        success, data = await self._request("PUT", "/open/crons/disable", json_data=cron_ids)
        return success, "禁用成功" if success else data
    
    async def pin_cron(self, cron_ids: List[int]) -> Tuple[bool, str]:
        """置顶定时任务"""
        success, data = await self._request("PUT", "/open/crons/pin", json_data=cron_ids)
        return success, "置顶成功" if success else data
    
    async def unpin_cron(self, cron_ids: List[int]) -> Tuple[bool, str]:
        """取消置顶定时任务"""
        success, data = await self._request("PUT", "/open/crons/unpin", json_data=cron_ids)
        return success, "取消置顶成功" if success else data
    
    async def delete_cron(self, cron_ids: List[int]) -> Tuple[bool, str]:
        """删除定时任务"""
        success, data = await self._request("DELETE", "/open/crons", json_data=cron_ids)
        return success, "删除成功" if success else data
    
    async def get_cron_log(self, cron_id: int) -> Tuple[bool, str]:
        """获取定时任务日志"""
        success, data = await self._request("GET", f"/open/crons/{cron_id}/log")
        return success, data if success else data
    
    async def get_system_info(self) -> Optional[Dict]:
        """获取系统信息"""
        success, data = await self._request("GET", "/open/system")
        return data if success and isinstance(data, dict) else None


class JDSmsLogin:
    """京东 H5 短信验证码登录辅助类
    
    公开流程（接口参数可能随京东风控策略调整，可在插件配置中校准）：
    1. send_code:  发送短信验证码到手机号
    2. check_code: 校验用户输入的验证码，换取登录 ticket
    3. get_cookie: 用 ticket 换取 pt_key / pt_pin Cookie
    """
    
    def __init__(self, config: dict):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取会话保持的 HTTP 客户端（登录流程需要携带 Cookie）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, cookies=httpx.Cookies())
        return self._client
    
    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    def _base_headers(self) -> Dict[str, str]:
        """登录接口基础请求头"""
        return {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
            "Referer": "https://plogin.m.jd.com/join/login?appid=20019",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    
    def _app_id(self) -> int:
        return int(self.config.get("jd_sms_app_id", 20019))
    
    async def send_code(self, phone: str, uuid_str: str) -> Tuple[bool, str, Dict]:
        """发送短信验证码，返回 (成功, 消息, 附加信息{smsKey, raw})"""
        try:
            client = await self._get_client()
            url = self.config.get("jd_sms_send_url", "https://plogin.m.jd.com/cgi/ml/sendCode")
            payload = {
                "uuid": uuid_str,
                "mobile": phone,
                "appId": self._app_id(),
                "smsKey": "",
                "authcode": "",
                "encode": "",
            }
            resp = await client.post(url, headers=self._base_headers(), json=payload)
            data = resp.json()
            
            if data.get("code") == 0:
                sms_key = ""
                if isinstance(data.get("result"), dict):
                    sms_key = data["result"].get("smsKey", "") or ""
                return True, data.get("msg", "验证码已发送"), {"smsKey": sms_key, "raw": data}
            
            return False, data.get("msg", f"发送失败(code={data.get('code')})"), {"raw": data}
        
        except httpx.TimeoutException:
            return False, "发送验证码请求超时", {}
        except Exception as e:
            return False, f"发送验证码请求异常: {e}", {}
    
    async def check_code(self, phone: str, code: str, uuid_str: str, sms_key: str = "") -> Tuple[bool, str, Dict]:
        """校验短信验证码，换取 ticket，返回 (成功, 消息, 附加信息{ticket, raw})"""
        try:
            client = await self._get_client()
            url = self.config.get("jd_sms_check_url", "https://plogin.m.jd.com/cgi/ml/checkCode")
            payload = {
                "code": code,
                "uuid": uuid_str,
                "appId": self._app_id(),
                "sceneid": int(self.config.get("jd_sms_scene_id", 8)),
                "smsKey": sms_key or "",
            }
            resp = await client.post(url, headers=self._base_headers(), json=payload)
            data = resp.json()
            
            if data.get("code") == 0:
                ticket = ""
                if isinstance(data.get("result"), dict):
                    ticket = data["result"].get("ticket", "") or ""
                return True, data.get("msg", "校验成功"), {"ticket": ticket, "raw": data}
            
            return False, data.get("msg", f"校验失败(code={data.get('code')})"), {"raw": data}
        
        except httpx.TimeoutException:
            return False, "校验验证码请求超时", {}
        except Exception as e:
            return False, f"校验验证码请求异常: {e}", {}
    
    async def get_cookie(self, ticket: str) -> Tuple[bool, str, Dict]:
        """用 ticket 换取 Cookie，从 Set-Cookie 提取 pt_key / pt_pin，返回 (成功, 消息, 附加信息{cookie, raw})"""
        try:
            client = await self._get_client()
            url = self.config.get("jd_sms_cookie_url", "https://plogin.m.jd.com/cgi/ml/getCookie")
            resp = await client.get(f"{url}?ticket={ticket}", headers=self._base_headers())
            
            # 从 Set-Cookie 提取 pt_ 开头的键值对
            set_cookies = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else []
            pairs = []
            for sc in set_cookies:
                pair = sc.split(";")[0].strip() if sc else ""
                if pair and "=" in pair:
                    key = pair.split("=", 1)[0].strip()
                    if key.startswith("pt_"):
                        pairs.append(pair)
            cookie_str = ";".join(pairs)
            
            if "pt_key=" in cookie_str and "pt_pin=" in cookie_str:
                return True, "获取Cookie成功", {"cookie": cookie_str, "raw_set_cookie": set_cookies}
            
            # 部分版本返回 JSON 结果
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("code") == 0 and isinstance(data.get("result"), dict):
                    # 某些版本 result 中直接包含 cookie 字段
                    direct = data["result"].get("cookie", "") or data["result"].get("ck", "")
                    if direct and "pt_key=" in direct and "pt_pin=" in direct:
                        return True, "获取Cookie成功", {"cookie": direct, "raw": data}
                return False, data.get("msg", "未获取到完整Cookie（可能被风控拦截）"), {"cookie": cookie_str, "raw": data}
            except Exception:
                return False, "未获取到完整Cookie（可能被风控拦截，建议实机抓包校准接口）", {"cookie": cookie_str, "raw_set_cookie": set_cookies}
        
        except httpx.TimeoutException:
            return False, "获取Cookie请求超时", {}
        except Exception as e:
            return False, f"获取Cookie请求异常: {e}", {}


class BrowserLoginHelper:
    """京东短信登录浏览器助手（Playwright 真实浏览器 + 打码平台识别验证码）

    背景：京东短信登录存在强风控（纯 HTTP 调 sendCode 返回 403，且登录页
    必须过滑块/旋转/轨迹类验证码）。本类用 Playwright 驱动真实 Chromium，
    让浏览器自身执行京东 JS 加密，只把"识别验证码"这一步交给打码平台
    （默认图鉴 ttshitu，可在插件配置中更换账号），自动完成：
    打开登录页 → 输入手机号 → 触发并破解验证码 → 发短信 → 
    用户回传验证码后登录并提取 Cookie。

    特性：
    - 每个登录会话独立 BrowserContext，用户之间完全隔离，互不串号
    - Chromium 首次使用时自动安装；Linux 缺失系统依赖时提示修复命令
    - 验证码破解失败自动刷新换题重试（京东题型随机：旋转/轨迹/缺口）
    - 并发登录数可配置（默认同时 1 个，避免多浏览器实例吃内存）
    """

    JD_LOGIN_URL = "https://passport.jd.com/uc/login"

    def __init__(self, config: dict, plugin: 'QinglongPlugin'):
        self.config = config
        self.plugin = plugin
        self._pw = None
        self._browser = None
        self._install_lock = asyncio.Lock()
        self._sessions: Dict[str, dict] = {}  # session_id -> {context, page, phone}
        self._sem = asyncio.Semaphore(int(config.get("jd_browser_max_concurrent", 1)))

    # ------------------------------------------------------------------
    # 浏览器安装与启动
    # ------------------------------------------------------------------
    def _chromium_executable(self) -> Optional[str]:
        """返回 Chromium 可执行文件路径（未安装则为 None）。
        新版 Playwright 会校验浏览器安装完整性（INSTALLATION_COMPLETE + .links 哈希），
        手动解压的浏览器过不了校验；因此优先直接 glob 查找可执行文件，绕过校验。"""
        import glob, os
        # 1. 自定义 / 自动探测目录中直接查找 chrome 可执行文件
        roots = []
        bpath = (self.config.get("jd_browser_path") or "").strip()
        if bpath:
            roots.append(bpath)
        detected = self._find_existing_browser_path()
        if detected:
            roots.append(detected)
        for root in roots:
            if not root:
                continue
            try:
                hits = glob.glob(os.path.join(root, "chromium-*", "chrome-linux64", "chrome"))
                if hits:
                    return hits[0]
            except Exception:
                continue
        # 2. 退回 Playwright 标准安装（registry 校验通过的情况）
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                return p.chromium.executable_path
        except Exception:
            return None

    async def _run_cmd(self, cmd: list, env: dict = None) -> Tuple[bool, str]:
        """在子进程执行命令，返回 (ok, 输出尾部)"""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
            text = (out or b"").decode("utf-8", "ignore")
            return proc.returncode == 0, text[-500:]
        except asyncio.TimeoutError:
            return False, "安装超时"
        except Exception as e:
            return False, str(e)

    def _find_existing_browser_path(self) -> str:
        """自动探测已存在的 Chromium 缓存目录（标准 home 缓存之外的常见共享目录）。
        返回可用的缓存根目录；找不到返回空字符串。"""
        import glob
        candidates = [
            "/vol1/@appdata/astrbot/ms-playwright",
            "/opt/ms-playwright",
            "/var/lib/ms-playwright",
            "/usr/local/share/ms-playwright",
            "/tmp/ms-playwright",
            "/data/ms-playwright",
        ]
        for cand in candidates:
            try:
                hits = glob.glob(os.path.join(cand, "chromium-*", "chrome-linux64", "chrome"))
                if hits:
                    return cand
            except Exception:
                continue
        return ""

    async def ensure_browser(self) -> Tuple[bool, str]:
        """检测 / 自动安装 / 启动 Chromium。返回 (ok, 消息)"""
        async with self._install_lock:
            if self._browser:
                return True, "ok"
            import sys, os

            # 浏览器缓存目录优先级：配置项 jd_browser_path > 自动探测共享目录 > 系统默认
            # AstrBot 若以非当前用户运行（如飞牛OS 应用容器用户），标准 home 缓存路径不可用，
            # 需要指向手动安装到共享目录的 Chromium
            bpath = (self.config.get("jd_browser_path") or "").strip()
            if not bpath:
                bpath = self._find_existing_browser_path()
            if bpath:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bpath
                logger.info(f"浏览器缓存目录: {bpath}")
                try:
                    os.makedirs(bpath, exist_ok=True)
                except Exception:
                    pass
            else:
                logger.info("浏览器缓存目录: 未指定（将使用系统默认路径）")

            # 1. 检查是否已安装
            exe = self._chromium_executable()
            logger.info(f"Chromium 检查结果: {exe}")
            if not exe or not os.path.exists(exe):
                if not self.config.get("jd_browser_auto_install", True):
                    return False, (
                        "Chromium 未安装且已关闭自动安装。请在服务器上执行：\n"
                        f"{sys.executable} -m playwright install chromium\n"
                        "Linux 下如缺系统库再执行："
                        f"{sys.executable} -m playwright install-deps chromium"
                    )
                logger.info("Chromium 未安装，开始自动下载（首次约 130MB，请稍候）…")
                # 国内网络直连 Playwright 官方 CDN 常失败，默认走 npmmirror 镜像
                mirror = (self.config.get("jd_browser_download_mirror") or "").strip() \
                    or "https://npmmirror.com/mirrors/playwright/"
                env = dict(os.environ)
                env.setdefault("PLAYWRIGHT_DOWNLOAD_HOST", mirror)
                logger.info(f"使用镜像下载 Chromium: {mirror}")
                ok, msg = await self._run_cmd(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    env=env,
                )
                if not ok:
                    return False, (
                        "Chromium 自动安装失败（网络原因居多）。\n"
                        "请在服务器上手动执行（已配置国内镜像）：\n"
                        f"PLAYWRIGHT_DOWNLOAD_HOST={mirror} "
                        f"{sys.executable} -m playwright install chromium"
                    )
                # Linux 下尝试补系统依赖（失败不阻塞，启动时再报）
                if os.name == "posix":
                    await self._run_cmd(
                        [sys.executable, "-m", "playwright", "install-deps", "chromium"],
                        env=env,
                    )
            else:
                logger.info(f"Chromium 已就绪: {exe}")

            # 2. 启动
            try:
                from playwright.async_api import async_playwright
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=bool(self.config.get("jd_browser_headless", True)),
                    executable_path=exe,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                return True, "ok"
            except Exception as e:
                err = str(e)
                if "Missing dependencies" in err or "error while loading shared libraries" in err:
                    import sys
                    return False, (
                        "Chromium 缺少系统依赖库。请在服务器执行（需 root）：\n"
                        f"{sys.executable} -m playwright install-deps chromium"
                    )
                return False, f"浏览器启动失败: {err}"

    # ------------------------------------------------------------------
    # 打码平台（图鉴 ttshitu）
    # ------------------------------------------------------------------
    def _captcha_ready(self) -> Tuple[bool, str]:
        """打码平台是否已配置"""
        user = (self.config.get("jd_captcha_username") or "").strip()
        pwd = (self.config.get("jd_captcha_password") or "").strip()
        if user and pwd:
            return True, ""
        return False, (
            "未配置打码平台账号（京东验证码为旋转/轨迹题，需打码平台识别）。\n"
            "请注册 https://www.ttshitu.com （免费送测试点数），在插件配置中填写 "
            "jd_captcha_username / jd_captcha_password"
        )

    async def _ttshitu(self, image_b64: str, typeid: str, imageback_b64: str = "") -> Tuple[bool, str]:
        """调用图鉴通用识别接口。返回 (ok, result)"""
        try:
            payload = {
                "username": (self.config.get("jd_captcha_username") or "").strip(),
                "password": (self.config.get("jd_captcha_password") or "").strip(),
                "typeid": typeid,
                "image": image_b64,
            }
            if imageback_b64:
                payload["imageback"] = imageback_b64
            url = self.config.get("jd_captcha_api_url", "http://api.ttshitu.com/predict")
            timeout = httpx.Timeout(60.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                data = resp.json()
            if data.get("success"):
                result = data.get("data", {}).get("result", "")
                return True, str(result).strip()
            return False, data.get("message", "识别失败")
        except Exception as e:
            return False, f"打码平台调用异常: {e}"

    # ------------------------------------------------------------------
    # 验证码题型识别与破解
    # ------------------------------------------------------------------
    async def _find_in_frames(self, page, selector: str):
        """在所有 frame（含 iframe）中查找第一个匹配元素。
        京东验证码组件可能加载在 iframe 中，主文档查询会漏掉。
        返回 (frame, element_handle)；找不到返回 (None, None)。"""
        for frame in page.frames:
            try:
                el = await frame.query_selector(selector)
                if el:
                    return frame, el
            except Exception:
                continue
        return None, None

    async def _detect_type(self, page) -> str:
        """检测当前验证码题型：rotate(旋转摆正) / arrow(拖动箭头填充拼图) / track(轨迹绘制) / gap(缺口拼图) / unknown"""
        try:
            # 诊断：无条件输出弹窗结构（含所有 frame），便于适配新题型（任何题型都打印）
            for frame in page.frames:
                try:
                    info = await frame.evaluate("""() => {
                        const d = document.querySelector('.captcha_drop');
                        if (!d) return null;
                        const cls = (typeof d.className === 'string') ? d.className : ((d.className && d.className.baseVal) || '');
                        const kids = Array.from(d.querySelectorAll('*')).map(e => {
                            let cn = '';
                            try { cn = (typeof e.className === 'string') ? e.className : ((e.className && e.className.baseVal) || ''); } catch (err) { cn = ''; }
                            return e.tagName + '#' + (e.id || '') + '.' + cn.split(' ').slice(0,2).join('.');
                        }).slice(0,25);
                        return { text: (d.innerText||'').slice(0,200), html: (d.innerHTML||'').slice(0,400), cls: cls, kids: kids };
                    }""")
                    if info:
                        logger.info(
                            f"验证码弹窗诊断 frame={frame.url[:80]}: "
                            f"class={info.get('cls')!r} text={info.get('text')!r} "
                            f"kids={info.get('kids')!r}"
                        )
                    else:
                        logger.info(f"验证码弹窗诊断 frame={frame.url[:80]}: 无 .captcha_drop")
                except Exception as e:
                    logger.info(f"验证码弹窗诊断 frame={frame.url[:80]} 访问失败: {str(e)[:120]}")
            # 题型判定
            _, slider = await self._find_in_frames(page, ".captcha_drop #slider-div")
            if slider is not None:
                return "rotate"
            _, arrow = await self._find_in_frames(page, ".captcha_drop .move-img")
            if arrow is not None:
                return "arrow"
            for frame in page.frames:
                try:
                    text = await frame.evaluate("""() => {
                        const d = document.querySelector('.captcha_drop');
                        return d ? (d.innerText || '') : '';
                    }""")
                    if text and ("轨迹" in text or "绘制" in text):
                        return "track"
                except Exception:
                    continue
            _, canvas = await self._find_in_frames(page, ".captcha_drop canvas")
            if canvas is not None:
                return "gap"
            return "unknown"
        except Exception:
            return "unknown"

    async def _extract_image_b64(self, page) -> Optional[str]:
        """提取验证码弹窗中的主图 base64（去掉 data: 前缀），支持 iframe"""
        try:
            for frame in page.frames:
                try:
                    src = await frame.evaluate("""() => {
                        const d = document.querySelector('.captcha_drop');
                        if (!d) return '';
                        const img = d.querySelector('.slot-content img') || d.querySelector('img');
                        return img ? img.src : '';
                    }""")
                    if src and "," in src:
                        return src.split(",", 1)[1]
                except Exception:
                    continue
            return None
        except Exception:
            return None

    def _parse_angle(self, result: str) -> Optional[int]:
        """解析打码平台返回的旋转角度（支持 ±数字、纯数字）"""
        m = re.search(r"[-+]?\d+", result or "")
        return int(m.group(0)) if m else None

    def _parse_track_points(self, result: str) -> Optional[List[Tuple[int, int]]]:
        """解析轨迹点坐标：尝试多种格式"""
        pts = []
        try:
            # JSON 数组 [[x,y],...]
            import json as _json
            obj = _json.loads(result)
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        pts.append((int(item[0]), int(item[1])))
                return pts if len(pts) >= 2 else None
        except Exception:
            pass
        # 分隔符形式 "x1,y1;x2,y2;..." 或 "x1,y1|x2,y2" 或空格
        for sep in (";", "|", "\n", " "):
            parts = [p for p in result.split(sep) if p.strip()]
            if len(parts) >= 2 and all("," in p for p in parts):
                ok = True
                for p in parts:
                    try:
                        x, y = p.split(",")
                        pts.append((int(x), int(y)))
                    except Exception:
                        ok = False
                        break
                if ok and len(pts) >= 2:
                    return pts
                pts = []
        return None

    async def _drag_human(self, page, start_x: float, start_y: float, distance: float, y_jitter: float = 2.0):
        """类人拖动：先快后慢 + 轻微抖动"""
        import random
        await page.mouse.move(start_x, start_y)
        await page.mouse.down()
        await asyncio.sleep(0.1)
        distance = max(distance, 1)
        steps = max(int(distance / 3), 6)
        # 前 60% 走完 80% 距离（快），后 40% 走完 20%（慢，对齐）
        fast_end = int(steps * 0.6)
        for i in range(1, steps + 1):
            if i <= fast_end:
                x = start_x + distance * (0.8 * i / fast_end)
            else:
                x = start_x + distance * (0.8 + 0.2 * (i - fast_end) / (steps - fast_end))
            y = start_y + random.uniform(-y_jitter, y_jitter)
            await page.mouse.move(x, y, steps=2)
            await asyncio.sleep(random.uniform(0.012, 0.035))
        await page.mouse.up()
        await asyncio.sleep(0.3)

    async def _solve_rotate(self, page) -> Tuple[bool, str]:
        """破解旋转摆正题：打码识别角度 → 拖动"""
        img_b64 = await self._extract_image_b64(page)
        if not img_b64:
            return False, "未获取到旋转图片"
        ok, result = await self._ttshitu(img_b64, str(self.config.get("jd_captcha_rotate_typeid", "29")))
        if not ok:
            return False, f"角度识别失败: {result}"
        angle = self._parse_angle(result)
        if angle is None:
            return False, f"角度识别结果异常: {result}"
        # 拖动距离 = 角度 * px/度（方向与比例可配置，实测校准）
        px_per_deg = float(self.config.get("jd_browser_rotate_px_per_deg", 1.0))
        direction = int(self.config.get("jd_browser_rotate_direction", 1))
        distance = (angle % 360) * px_per_deg * direction
        if distance < 0:
            distance = 360 * px_per_deg + distance  # 负方向换算为正方向拖动
        _, slide = await self._find_in_frames(page, ".captcha_drop #slider-div")
        if not slide:
            return False, "未找到滑块按钮"
        box = await slide.bounding_box()
        if not box:
            return False, "滑块位置不可用"
        logger.info(f"旋转题: 识别角度={angle}°, 拖动距离={int(distance)}px")
        await self._drag_human(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, distance)
        return True, f"已按 {angle}° 拖动"

    async def _solve_track(self, page) -> Tuple[bool, str]:
        """破解轨迹绘制题：打码识别轨迹坐标 → 在图上绘制"""
        img_b64 = await self._extract_image_b64(page)
        if not img_b64:
            return False, "未获取到轨迹图"
        ok, result = await self._ttshitu(img_b64, str(self.config.get("jd_captcha_track_typeid", "48")))
        if not ok:
            return False, f"轨迹识别失败: {result}"
        pts = self._parse_track_points(result)
        if not pts:
            return False, f"轨迹坐标解析失败: {result[:60]}"
        # 图片在 slot-content 内，需要相对页面的绝对坐标（支持 iframe）
        img_box = None
        for frame in page.frames:
            try:
                img_box = await frame.evaluate("""() => {
                    const el = document.querySelector('.captcha_drop .slot-content img');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {x: r.x, y: r.y, w: r.width, h: r.height, nw: el.naturalWidth, nh: el.naturalHeight};
                }""")
                if img_box:
                    break
            except Exception:
                continue
        if not img_box:
            return False, "未找到轨迹图位置"
        scale_x = img_box["w"] / max(img_box["nw"], 1)
        scale_y = img_box["h"] / max(img_box["nh"], 1)
        logger.info(f"轨迹题: 识别到 {len(pts)} 个轨迹点")
        # 起点按下，逐点移动，终点松开
        first = True
        for (px, py) in pts:
            abs_x = img_box["x"] + px * scale_x
            abs_y = img_box["y"] + py * scale_y
            if first:
                await page.mouse.move(abs_x, abs_y)
                await page.mouse.down()
                await asyncio.sleep(0.15)
                first = False
            else:
                await page.mouse.move(abs_x, abs_y, steps=2)
                await asyncio.sleep(0.03)
        await page.mouse.up()
        return True, f"已按 {len(pts)} 个轨迹点绘制"

    async def _solve_gap(self, page) -> Tuple[bool, str]:
        """破解缺口拼图题：图鉴单缺口识别（typeid 33）返回 X 坐标 → 拖动"""
        img_b64 = await self._extract_image_b64(page)
        if not img_b64:
            return False, "未获取到缺口图"
        ok, result = await self._ttshitu(img_b64, str(self.config.get("jd_captcha_gap_typeid", "33")))
        if not ok:
            return False, f"缺口识别失败: {result}"
        x = self._parse_angle(result)
        if x is None:
            return False, f"缺口坐标异常: {result}"
        _, slide = await self._find_in_frames(page, ".captcha_drop #slider-div")
        if not slide:
            return False, "未找到滑块按钮"
        box = await slide.bounding_box()
        if not box:
            return False, "滑块位置不可用"
        # 缺口 X 坐标需减去滑块按钮宽度，并乘图片缩放比例
        scale = 1.0
        for frame in page.frames:
            try:
                img_box = await frame.evaluate("""() => {
                    const el = document.querySelector('.captcha_drop .slot-content img');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {w: r.width, nw: el.naturalWidth};
                }""")
                if img_box and img_box["nw"]:
                    scale = img_box["w"] / img_box["nw"]
                    break
            except Exception:
                continue
        distance = x * scale - box["width"] * 0.5
        logger.info(f"缺口题: 识别X={x}, 拖动距离={int(distance)}px")
        await self._drag_human(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, distance)
        return True, f"已按缺口 X={x} 拖动"

    async def _solve_arrow(self, page) -> Tuple[bool, str]:
        """破解京东'拖动箭头填充拼图'：识别主图目标位置 → 拖动 .move-img 箭头对齐。
        结构：#main_img 主图 / #slot_img 拼图块 / .slide_path 轨道 / .move-img 箭头。"""
        # 1. 提取主图与缺口块图 base64
        main_b64, slot_b64 = "", ""
        for frame in page.frames:
            try:
                srcs = await frame.evaluate("""() => {
                    const m = document.querySelector('#main_img');
                    const s = document.querySelector('#slot_img');
                    return { m: m ? m.src : '', s: s ? s.src : '' };
                }""")
                if srcs and srcs.get("m") and "," in srcs["m"]:
                    main_b64 = srcs["m"].split(",", 1)[1]
                if srcs and srcs.get("s") and "," in srcs["s"]:
                    slot_b64 = srcs["s"].split(",", 1)[1]
                if main_b64:
                    break
            except Exception:
                continue
        if not main_b64:
            return False, "未获取到拼图主图"
        # 2. 打码识别目标 X 坐标：优先 1033 拖动拼图（双图，京东箭头拼图专用，可排除伪缺口），失败回退 33 单缺口
        arrow_typeid = str(self.config.get("jd_captcha_arrow_typeid", "1033"))
        ok, result = await self._ttshitu(main_b64, arrow_typeid, imageback_b64=slot_b64 or "")
        if not ok:
            ok, result = await self._ttshitu(main_b64, str(self.config.get("jd_captcha_gap_typeid", "33")))
        if not ok:
            return False, f"拼图目标识别失败: {result}"
        x = self._parse_angle(result)
        if x is None:
            return False, f"拼图目标坐标异常: {result}"
        logger.info(f"箭头拼图题: typeid={arrow_typeid} 原始返回={result} 解析X={x}")
        # 3. 拖动箭头 move-img 到主图目标位置
        _, move_img = await self._find_in_frames(page, ".captcha_drop .move-img")
        if not move_img:
            return False, "未找到箭头拖动块"
        mbox = await move_img.bounding_box()
        if not mbox:
            return False, "箭头位置不可用"
        # 主图视口位置与缩放
        img_pos = None
        for frame in page.frames:
            try:
                img_pos = await frame.evaluate("""() => {
                    const el = document.querySelector('#main_img');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    return {x: r.x, w: r.width, nw: el.naturalWidth};
                }""")
                if img_pos:
                    break
            except Exception:
                continue
        if not img_pos or not img_pos.get("nw"):
            return False, "未找到主图位置"
        scale = img_pos["w"] / max(img_pos["nw"], 1)
        target_x = img_pos["x"] + x * scale
        start_center = mbox["x"] + mbox["width"] / 2
        # 对齐口径：箭头左边缘对准缺口目标 X（滑块类验证码常规口径），拖动从箭头中心按下
        distance = target_x - mbox["x"]
        # 京东防"完美重合"：故意偏离 2~6px（人手不可能 100% 对齐，精确对齐反被判机器）
        import random as _rr
        imperfect = _rr.choice((-1, 1)) * _rr.uniform(2.5, 6.0)
        distance += imperfect
        logger.info(f"箭头拼图题: 识别目标X={x}, 箭头左边缘={int(mbox['x'])}, 目标视口x={int(target_x)}, 拖动距离={int(distance)}px(含偏差{imperfect:+.1f})")
        await self._drag_human(page, start_center, mbox["y"] + mbox["height"] / 2, distance)
        # 同题微调：弹窗未消失则按偏移重拖（同一验证码，不重新打码，省点数）
        for off in (40, -40, 80, -80):
            if await self._wait_captcha_gone(page, timeout_s=2.5):
                return True, f"已按目标 X={x} 拖动箭头"
            d2 = distance + off + _rr.choice((-1, 1)) * _rr.uniform(2.0, 5.0)
            logger.info(f"箭头拼图同题微调: 偏移 {off:+d}px")
            await self._drag_human(page, start_center, mbox["y"] + mbox["height"] / 2, d2)
        return True, f"已按目标 X={x} 拖动箭头（含微调）"

    async def _refresh_captcha(self, page):
        """点击验证码弹窗的刷新按钮换题"""
        try:
            await page.evaluate("""() => { const r = document.querySelector('.jcap_refresh'); if (r) r.click(); }""")
        except Exception:
            pass
        await asyncio.sleep(2)

    async def _wait_captcha_gone(self, page, timeout_s: float = 10.0) -> bool:
        """等待验证码弹窗消失（=破解成功）"""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                if await page.query_selector(".captcha_drop") is None:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    async def _wait_sms_sent(self, page, timeout_s: float = 20.0) -> Tuple[bool, str]:
        """验证码弹窗消失后，等待京东真正发出短信（按钮进入倒计时或出现提示）"""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                btn = await page.query_selector("#send-sms-code-btn")
                if btn:
                    txt = await btn.inner_text()
                    disabled = await btn.is_disabled()
                    if disabled and any(k in txt for k in ("s", "秒", "重新")):
                        return True, f"验证码已发送（{txt}）"
                # 或页面出现发送成功提示
                body = await page.evaluate("() => document.body.innerText || ''")
                if "验证码已发送" in body or "发送成功" in body:
                    return True, "验证码已发送"
            except Exception:
                pass
            await asyncio.sleep(0.8)
        # 兜底：弹窗已消失视为发送成功
        return True, "验证码已发送"

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    async def start_sms_login(self, session_id: str, phone: str) -> Tuple[bool, str]:
        """第一步：打开登录页 → 输入手机号 → 破解验证码 → 等待发码。
        成功后将浏览器会话保存在 self._sessions[session_id]，等待用户回传验证码。
        """
        ok, msg = self._captcha_ready()
        if not ok:
            return False, msg

        async with self._sem:
            ok, msg = await self.ensure_browser()
            if not ok:
                return False, msg

            context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                viewport={"width": 1280, "height": 900},
            )
            # 隐藏自动化特征，降低被京东风控多维识别（webdriver/插件/languages）的概率
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = window.chrome || { runtime: {} };
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """)
            page = await context.new_page()
            try:
                await page.goto(self.JD_LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
                await asyncio.sleep(5)
                # 切到短信登录 tab
                await page.evaluate("""() => { document.querySelector('#sms-login').click(); }""")
                await asyncio.sleep(1.5)
                # 输入手机号
                mb = await page.query_selector("#mobile-number")
                if not mb:
                    await context.close()
                    return False, "登录页未加载完整（短信表单未出现），请稍后重试"
                await mb.click(force=True)
                await page.keyboard.type(phone, delay=40)
                await asyncio.sleep(0.5)
                # 点击获取验证码
                await page.evaluate("""() => { document.querySelector('#send-sms-code-btn').click(); }""")
                # 等待验证码弹窗
                appeared = False
                for _ in range(30):
                    _, cap = await self._find_in_frames(page, ".captcha_drop")
                    if cap:
                        appeared = True
                        break
                    await asyncio.sleep(0.5)
                if not appeared:
                    # 可能直接发码成功（未弹验证码），或提示错误
                    await asyncio.sleep(3)
                    body = await page.evaluate("() => document.body.innerText || ''")
                    if "验证码已发送" in body or "发送成功" in body:
                        self._sessions[session_id] = {"context": context, "page": page, "phone": phone}
                        return True, "ok"
                    await context.close()
                    return False, f"未弹出验证码且未发送成功：{body[:120]}"

                # 保存验证码弹窗截图（诊断用，登录失败后可查看弹窗真实内容）
                try:
                    import tempfile, os as _os
                    shot = _os.path.join(tempfile.gettempdir(), f"jd_captcha_{int(time.time())}.png")
                    await page.screenshot(path=shot)
                    logger.info(f"验证码弹窗截图已保存: {shot}")
                except Exception as e:
                    logger.info(f"验证码弹窗截图失败: {str(e)[:120]}")

                # 破解验证码（重试循环）
                max_retry = max(int(self.config.get("jd_browser_max_retry", 4)), 1)
                last_err = "验证码破解失败"
                gone = False
                for attempt in range(max_retry):
                    await asyncio.sleep(2)  # 等验证码内容加载
                    ctype = await self._detect_type(page)
                    logger.info(f"验证码破解尝试 {attempt+1}/{max_retry}: 题型={ctype}")
                    if ctype == "rotate":
                        ok, last_err = await self._solve_rotate(page)
                    elif ctype == "arrow":
                        ok, last_err = await self._solve_arrow(page)
                    elif ctype == "track":
                        ok, last_err = await self._solve_track(page)
                    elif ctype == "gap":
                        ok, last_err = await self._solve_gap(page)
                    else:
                        ok, last_err = False, "未识别的验证码题型"
                    if not ok:
                        await self._refresh_captcha(page)
                        continue
                    # 拖动完成，等弹窗消失判定成败
                    gone = await self._wait_captcha_gone(page)
                    if gone:
                        break
                    last_err = "验证码未通过（可能识别角度/轨迹不准）"
                    await self._refresh_captcha(page)

                if not gone:
                    await context.close()
                    return False, f"{last_err}（已重试 {max_retry} 次，请稍后再试）"

                # 验证通过，等待短信发送
                sent, msg2 = await self._wait_sms_sent(page)
                if not sent:
                    await context.close()
                    return False, msg2
                self._sessions[session_id] = {"context": context, "page": page, "phone": phone}
                return True, "ok"

            except Exception as e:
                logger.error(f"浏览器登录流程异常: {e}")
                logger.error(traceback.format_exc())
                try:
                    await context.close()
                except Exception:
                    pass
                return False, f"浏览器登录流程异常: {e}"

    async def submit_sms_code(self, session_id: str, code: str) -> Tuple[bool, str, str]:
        """第二步：输入验证码 → 登录 → 提取 Cookie。返回 (ok, msg, cookie)"""
        session = self._sessions.get(session_id)
        if not session:
            return False, "登录会话已失效，请重新发送手机号", ""
        page = session["page"]
        context = session["context"]
        try:
            code_input = await page.query_selector("#sms-code")
            if not code_input:
                return False, "验证码输入框不可用", ""
            await code_input.click(force=True)
            await page.keyboard.type(code, delay=60)
            await asyncio.sleep(0.5)
            await page.evaluate("""() => { document.querySelector('#sms-login-submit').click(); }""")

            # 等待跳转或错误提示（最长 20 秒）
            login_url = page.url
            deadline = time.time() + 20
            while time.time() < deadline:
                await asyncio.sleep(0.8)
                try:
                    cur = page.url
                    if "passport.jd.com" not in cur or "uc/login" not in cur:
                        break  # 已跳转
                    body = await page.evaluate("() => document.body.innerText || ''")
                    if any(k in body for k in ("验证码错误", "验证码不正确", "输入错误", "验证码已过期")):
                        return False, "验证码错误或已过期，请重新发送手机号获取新验证码", ""
                except Exception:
                    pass

            # 提取 Cookie（pt_key / pt_pin）
            await asyncio.sleep(2)
            cookies = await context.cookies()
            pairs = {}
            for c in cookies:
                if c["name"].startswith("pt_") and c["value"]:
                    pairs[c["name"]] = c["value"]
            cookie = ";".join(f"{k}={v}" for k, v in pairs.items())
            if "pt_key=" in cookie and "pt_pin=" in cookie:
                return True, "登录成功", cookie
            # 未取到完整 cookie：再等一会重试一次
            await asyncio.sleep(3)
            cookies = await context.cookies()
            pairs = {}
            for c in cookies:
                if c["name"].startswith("pt_") and c["value"]:
                    pairs[c["name"]] = c["value"]
            cookie = ";".join(f"{k}={v}" for k, v in pairs.items())
            if "pt_key=" in cookie and "pt_pin=" in cookie:
                return True, "登录成功", cookie
            return False, "登录后未获取到完整 Cookie（pt_key/pt_pin），请重新尝试", cookie
        except Exception as e:
            logger.error(f"提交验证码异常: {e}")
            logger.error(traceback.format_exc())
            return False, f"提交验证码异常: {e}", ""
        finally:
            # 无论成败，结束会话释放浏览器资源
            await self.close_session(session_id)

    async def close_session(self, session_id: str):
        """关闭单个登录会话"""
        session = self._sessions.pop(session_id, None)
        if not session:
            return
        try:
            await session["context"].close()
        except Exception:
            pass

    async def close_all(self):
        """关闭全部浏览器会话与浏览器实例（插件卸载时调用）"""
        for sid in list(self._sessions.keys()):
            await self.close_session(sid)
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw = None


class TaskLogMonitor:
    """任务日志监控器"""
    
    def __init__(self, ql_api: QinglongAPI, plugin_instance: 'QinglongPlugin', config: dict):
        """初始化监控器"""
        self.ql_api = ql_api
        self.plugin = plugin_instance
        self.config = config
        self.monitoring_tasks: Set[int] = set()
        self.pending_logs: Dict[int, Dict] = {}
        self.sent_logs: Set[int] = set()
        logger.info("任务日志监控器已初始化")
    
    async def start_monitor(self, cron_id: int, cron_name: str):
        """开始监控任务执行"""
        if cron_id in self.monitoring_tasks:
            logger.info(f"任务 {cron_id} 已在监控中，跳过")
            return
        
        self.monitoring_tasks.add(cron_id)
        asyncio.create_task(self._monitor_task(cron_id, cron_name))
        logger.info(f"开始监控任务: {cron_name} (ID: {cron_id})")
    
    async def _monitor_task(self, cron_id: int, cron_name: str):
        """监控任务执行状态"""
        try:
            logger.info(f"开始监控任务 {cron_id}: {cron_name}")
            await asyncio.sleep(5)
            
            cron_info = await self.ql_api.get_cron_by_id(cron_id)
            if not cron_info:
                logger.warning(f"任务 {cron_id} 不存在，停止监控")
                return
            
            pid = cron_info.get('pid')
            if pid:
                logger.info(f"任务 {cron_id} 仍在执行 (PID: {pid})")
                await asyncio.sleep(10)
            
            await self._save_task_log(cron_id, cron_name)
            
        except Exception as e:
            logger.error(f"监控任务 {cron_id} 时发生错误: {e}")
            try:
                await self._save_task_log(cron_id, cron_name, error=str(e))
            except Exception as e2:
                logger.error(f"保存任务日志时发生错误: {e2}")
        finally:
            self.monitoring_tasks.discard(cron_id)
            logger.info(f"任务 {cron_id} 监控结束")
    
    async def _save_task_log(self, cron_id: int, cron_name: str, error: str = None):
        """保存任务日志到待发送队列"""
        if not self.config.get("log_push_enabled", True):
            logger.info(f"日志推送功能已禁用，跳过保存任务 {cron_id} 日志")
            return
        
        logger.info(f"开始获取任务 {cron_id} 的日志...")
        
        success, log_content = await self.ql_api.get_cron_log(cron_id)
        
        if not success:
            log_content = f"获取任务日志失败: {log_content}"
            logger.error(f"获取任务 {cron_id} 日志失败: {log_content}")
        elif not log_content:
            log_content = "任务执行无日志输出"
            logger.warning(f"任务 {cron_id} 没有日志内容")
        else:
            logger.info(f"成功获取任务 {cron_id} 的日志，长度: {len(log_content)} 字符")
        
        error_msg = f"（监控错误: {error}）" if error else ""
        message = (
            f"🚀 青龙任务执行完成{error_msg}\n"
            f"📝 任务名称: {cron_name}\n"
            f"🔢 任务ID: {cron_id}\n"
            f"⏰ 时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}\n"
            f"📋 执行日志:\n"
            f"{'─' * 20}\n"
        )
        
        if len(log_content) > 1000:
            original_length = len(log_content)
            log_content = "【日志过长，只显示最后1000字符】\n...\n" + log_content[-1000:]
            logger.info(f"日志过长 ({original_length} 字符)，截取为 1000 字符")
        
        message += log_content
        
        log_entry = {
            "cron_id": cron_id,
            "cron_name": cron_name,
            "time": time.time(),
            "message": message,
            "log_content": log_content,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
            "sent": False
        }
        
        self.pending_logs[cron_id] = log_entry
        self.plugin.last_task_log = log_entry
        
        logger.info(f"任务 {cron_id} 日志已保存到待发送队列，当前队列大小: {len(self.pending_logs)}")
        
        await self._try_auto_send_log(cron_id, log_entry)
        logger.info(f"任务 {cron_id} 的日志已就绪")
    
    async def _try_auto_send_log(self, cron_id: int, log_entry: Dict):
        """尝试自动发送日志到配置的群和好友"""
        try:
            groups = self.config.get("log_push_groups", [])
            friends = self.config.get("log_push_friends", [])
            
            if not groups and not friends:
                logger.info(f"未配置推送目标，跳过自动发送任务 {cron_id} 的日志")
                return
            
            if groups:
                logger.info(f"任务 {cron_id} 的日志可推送到群: {groups}")
            if friends:
                logger.info(f"任务 {cron_id} 的日志可推送到好友: {friends}")
            
            logger.info(f"💡 任务 {cron_id} 执行完成！使用 /ql pending 查看待发送日志，或 /ql sendlog {cron_id} 直接查看")
            
        except Exception as e:
            logger.error(f"尝试自动发送日志时发生错误: {e}")
    
    def get_pending_logs(self) -> List[Dict]:
        """获取待发送的日志（按时间倒序）"""
        logs = list(self.pending_logs.values())
        logs.sort(key=lambda x: x.get('time', 0), reverse=True)
        logger.info(f"获取待发送日志，总数: {len(logs)}")
        return logs
    
    def get_pending_log_by_id(self, cron_id: int) -> Optional[Dict]:
        """根据任务ID获取待发送的日志"""
        log = self.pending_logs.get(cron_id)
        logger.info(f"获取任务 {cron_id} 的待发送日志: {'找到' if log else '未找到'}")
        return log
    
    def mark_log_as_sent(self, cron_id: int):
        """标记日志为已发送"""
        if cron_id in self.pending_logs:
            self.pending_logs[cron_id]['sent'] = True
            self.sent_logs.add(cron_id)
            logger.info(f"标记任务 {cron_id} 的日志为已发送")
    
    def remove_log(self, cron_id: int):
        """从待发送队列中移除日志"""
        if cron_id in self.pending_logs:
            del self.pending_logs[cron_id]
            logger.info(f"从待发送队列中移除任务 {cron_id} 的日志")
        if cron_id in self.sent_logs:
            self.sent_logs.remove(cron_id)
    
    def clear_old_logs(self, max_age_minutes: int = 60):
        """清理超过指定时间的旧日志（分钟为单位）"""
        current_time = time.time()
        old_logs = []
        
        for cron_id, log_entry in list(self.pending_logs.items()):
            log_time = log_entry.get('time', 0)
            if (current_time - log_time > max_age_minutes * 60) and log_entry.get('sent', False):
                old_logs.append(cron_id)
        
        for cron_id in old_logs:
            self.remove_log(cron_id)
        
        if old_logs:
            logger.info(f"已清理 {len(old_logs)} 条超过 {max_age_minutes} 分钟的旧日志")


class LogScheduleManager:
    """日志定时推送管理器"""
    
    def __init__(self, ql_plugin: 'QinglongPlugin', config: dict):
        """初始化调度器"""
        self.plugin = ql_plugin
        self.config = config
        self.schedule_task = None
        self.log_cache = {}
        self.waiting_for_confirm: Dict[str, Dict] = {}  # 存储等待确认的目标和错误日志
        logger.info("日志定时推送管理器已初始化")
    
    async def start_schedule(self):
        """启动定时推送任务"""
        if not self.config.get("log_schedule_enabled", True):
            logger.info("定时日志推送功能已禁用")
            return
        
        self.schedule_task = asyncio.create_task(self._schedule_loop())
        logger.info("日志定时推送任务已启动")
    
    async def stop_schedule(self):
        """停止定时推送任务"""
        if self.schedule_task and not self.schedule_task.done():
            self.schedule_task.cancel()
            try:
                await self.schedule_task
            except asyncio.CancelledError:
                pass
        logger.info("日志定时推送任务已停止")
    
    async def _schedule_loop(self):
        """定时推送主循环"""
        while True:
            try:
                sleep_time = self._calculate_sleep_time()
                logger.info(f"[定时推送] 下次日志推送将在 {sleep_time / 3600:.2f} 小时后")
                await asyncio.sleep(sleep_time)
                
                await self._send_scheduled_logs()
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[定时推送] 任务出错: {e}")
                await asyncio.sleep(300)
    
    def _calculate_sleep_time(self) -> float:
        """计算距离下次推送的秒数"""
        now = datetime.datetime.now()
        schedule_times = self.config.get("log_schedule_time", "08:00,18:00").split(",")
        
        min_sleep = float('inf')
        for time_str in schedule_times:
            try:
                hour, minute = map(int, time_str.strip().split(":"))
                next_push = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                if next_push <= now:
                    next_push += datetime.timedelta(days=1)
                
                sleep_seconds = (next_push - now).total_seconds()
                if sleep_seconds < min_sleep:
                    min_sleep = sleep_seconds
            except Exception as e:
                logger.error(f"解析推送时间失败: {time_str}, 错误: {e}")
        
        return min_sleep if min_sleep != float('inf') else 86400
    
    async def _send_scheduled_logs(self):
        """发送定时日志"""
        try:
            logger.info("开始执行定时日志推送...")
            
            display_count = self.config.get("log_schedule_display_count", 10)
            logger.info(f"配置显示任务数量: {display_count}")
            
            crons = await self.plugin.ql_api.get_crons()
            if not crons:
                logger.info("没有找到定时任务，跳过推送")
                return
            
            logger.info(f"找到 {len(crons)} 个定时任务")
            
            recent_logs = []
            error_logs = []
            for cron in crons[:display_count]:
                cron_id = cron.get('id')
                cron_name = cron.get('name', f'任务{cron_id}')
                
                success, log_content = await self.plugin.ql_api.get_cron_log(cron_id)
                if success and log_content:
                    is_error_log = self._is_error_log(log_content)
                    recent_log = self._extract_log(cron_id, cron_name, log_content, is_error_log)
                    if recent_log:
                        recent_logs.append(recent_log)
                        if is_error_log:
                            error_logs.append(recent_log)
                else:
                    recent_logs.append({
                        'cron_id': cron_id,
                        'cron_name': cron_name,
                        'log': f"获取日志失败: {log_content if not success else '无日志内容'}",
                        'full_log': '',
                        'is_error': True,
                        'log_type': '获取失败',
                        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    error_logs.append(recent_logs[-1])
                
                await asyncio.sleep(0.3)
            
            logger.info(f"获取到 {len(recent_logs)} 个任务的日志，其中 {len(error_logs)} 个有错误")
            
            summary = self._prepare_summary_message(recent_logs, error_logs)
            
            # 发送汇总消息到所有目标
            await self._send_summary_to_targets(summary, error_logs)
            
            logger.info(f"定时日志推送完成，共推送 {len(recent_logs)} 个任务的日志")
            
        except Exception as e:
            logger.error(f"定时推送日志失败: {e}")
            traceback.print_exc()
    
    async def _send_summary_to_targets(self, summary_message: str, error_logs: List[Dict]):
        """发送汇总消息到所有目标，并询问是否推送错误日志"""
        try:
            # 获取配置的推送目标
            groups = self.config.get("log_schedule_groups", [])
            friends = self.config.get("log_schedule_friends", [])
            
            # 清理空值
            groups = [g for g in groups if g and str(g).strip()]
            friends = [f for f in friends if f and str(f).strip()]
            
            if not groups and not friends:
                logger.info("未配置定时推送目标，跳过发送")
                return
            
            logger.info(f"开始向 {len(groups)} 个群和 {len(friends)} 个好友发送定时推送")
            
            # 如果没有错误日志，直接发送汇总消息
            if not error_logs:
                logger.info("没有错误日志，直接发送汇总消息")
                await self._send_message_to_all_targets(summary_message, groups, friends)
                return
            
            # 分割汇总消息
            summary_parts = self._split_message(summary_message)
            
            # 发送汇总消息
            for part_index, part in enumerate(summary_parts):
                await self._send_message_to_all_targets(part, groups, friends)
                await asyncio.sleep(1)
            
            # 为每个目标发送询问消息并设置等待确认
            for group_target in groups:
                try:
                    formatted_target = self._format_target(group_target, "GroupMessage")
                    if not formatted_target:
                        logger.error(f"群组目标格式错误: {group_target}")
                        continue
                    
                    ask_message = self._prepare_ask_message(error_logs)
                    await self._send_message_to_target(formatted_target, ask_message)
                    
                    # 记录等待确认的状态
                    self.waiting_for_confirm[formatted_target] = {
                        "error_logs": error_logs,
                        "start_time": time.time(),
                        "target_type": "group"
                    }
                    
                    logger.info(f"已向群组 {formatted_target} 发送询问消息，等待30秒确认")
                    
                except Exception as e:
                    logger.error(f"向群组 {group_target} 发送询问消息失败: {str(e)}")
            
            for friend_target in friends:
                try:
                    formatted_target = self._format_target(friend_target, "FriendMessage")
                    if not formatted_target:
                        logger.error(f"好友目标格式错误: {friend_target}")
                        continue
                    
                    ask_message = self._prepare_ask_message(error_logs)
                    await self._send_message_to_target(formatted_target, ask_message)
                    
                    # 记录等待确认的状态
                    self.waiting_for_confirm[formatted_target] = {
                        "error_logs": error_logs,
                        "start_time": time.time(),
                        "target_type": "friend"
                    }
                    
                    logger.info(f"已向好友 {formatted_target} 发送询问消息，等待30秒确认")
                    
                except Exception as e:
                    logger.error(f"向好友 {friend_target} 发送询问消息失败: {str(e)}")
            
            # 启动30秒后清理等待状态的任务
            asyncio.create_task(self._cleanup_waiting_status())
                    
        except Exception as e:
            logger.error(f"发送汇总消息失败: {str(e)}")
            traceback.print_exc()
    
    def _prepare_ask_message(self, error_logs: List[Dict]) -> str:
        """准备询问消息"""
        error_count = len(error_logs)
        error_names = ", ".join([f"{log['cron_name']}(ID:{log['cron_id']})" for log in error_logs[:3]])
        if error_count > 3:
            error_names += f" 等 {error_count} 个任务"
        
        message = [
            "──────────────────────────────",
            f"🔴 检测到 {error_count} 个任务执行错误: {error_names}",
            "",
            "是否推送错误日志详情？",
            "请在30秒内回复：",
            "✅ 是 / 需要 / 推送错误日志",
            "❌ 否 / 不需要 / 取消",
            "",
            "30秒内未回复将不推送错误日志"
        ]
        
        return '\n'.join(message)
    
    async def _cleanup_waiting_status(self):
        """30秒后清理等待状态"""
        await asyncio.sleep(30)
        
        current_time = time.time()
        expired_targets = []
        
        for target, status in self.waiting_for_confirm.items():
            if current_time - status["start_time"] >= 30:
                expired_targets.append(target)
                logger.info(f"目标 {target} 的30秒等待时间已过，清理等待状态")
        
        for target in expired_targets:
            del self.waiting_for_confirm[target]
    
    async def check_and_send_error_logs(self, target: str, user_response: str) -> bool:
        """检查并发送错误日志"""
        if target not in self.waiting_for_confirm:
            return False
        
        status = self.waiting_for_confirm[target]
        current_time = time.time()
        
        # 检查是否超时
        if current_time - status["start_time"] > 30:
            del self.waiting_for_confirm[target]
            return False
        
        # 检查用户回复是否确认
        confirm_keywords = ["是", "需要", "推送错误日志", "推送", "发送", "yes", "y", "确认"]
        cancel_keywords = ["否", "不需要", "取消", "不推送", "no", "n", "取消推送"]
        
        user_response_lower = user_response.lower()
        
        is_confirm = any(keyword in user_response_lower for keyword in confirm_keywords)
        is_cancel = any(keyword in user_response_lower for keyword in cancel_keywords)
        
        if not is_confirm and not is_cancel:
            return False
        
        if is_cancel:
            await self._send_message_to_target(target, "❌ 已取消推送错误日志")
            del self.waiting_for_confirm[target]
            return True
        
        # 发送错误日志详情
        error_logs = status["error_logs"]
        error_details = self._prepare_error_details(error_logs)
        
        # 分割错误日志消息
        error_parts = self._split_message(error_details)
        
        for part_index, part in enumerate(error_parts):
            await self._send_message_to_target(target, part)
            await asyncio.sleep(1)
        
        del self.waiting_for_confirm[target]
        return True
    
    def _prepare_error_details(self, error_logs: List[Dict]) -> str:
        """准备错误日志详情"""
        if not error_logs:
            return "📭 暂无错误日志"
        
        message = ["🔴 错误日志详情:"]
        
        for i, log in enumerate(error_logs, 1):
            message.append(f"{'─' * 30}")
            message.append(f"❌ {i}. {log['cron_name']} (ID: {log['cron_id']})")
            message.append(f"📋 日志类型: {log.get('log_type', '错误日志')}")
            message.append(f"⏰ 时间: {log.get('timestamp', '未知')}")
            message.append("")
            message.append("📝 错误内容:")
            message.append(f"{'─' * 20}")
            
            log_content = log.get('log', '')
            if log_content:
                lines = log_content.split('\n')
                for line in lines[:50]:  # 最多显示50行
                    if line.strip():
                        message.append(f"    {line}")
                
                if len(lines) > 50:
                    message.append(f"    ... 还有 {len(lines) - 50} 行未显示")
            else:
                message.append("    无日志内容")
            
            message.append(f"{'─' * 20}")
            message.append("")
        
        message.append(f"📊 共 {len(error_logs)} 个错误任务")
        message.append("💡 使用 /ql log <任务ID> 查看完整日志")
        
        return '\n'.join(message)
    
    async def _send_message_to_all_targets(self, message: str, groups: List[str], friends: List[str]):
        """发送消息到所有目标"""
        sent_count = 0
        
        # 发送到群组
        for group_target in groups:
            try:
                formatted_target = self._format_target(group_target, "GroupMessage")
                if not formatted_target:
                    continue
                
                await self._send_message_to_target(formatted_target, message)
                sent_count += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"发送到群 {group_target} 失败: {str(e)}")
        
        # 发送到好友
        for friend_target in friends:
            try:
                formatted_target = self._format_target(friend_target, "FriendMessage")
                if not formatted_target:
                    continue
                
                await self._send_message_to_target(formatted_target, message)
                sent_count += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"发送到好友 {friend_target} 失败: {str(e)}")
        
        return sent_count
    
    async def _send_message_to_target(self, target: str, message: str):
        """发送消息到单个目标"""
        try:
            mc = MessageChain().message(message)
            await self.plugin.context.send_message(target, mc)
            logger.info(f"✅ 已发送消息到: {target}")
        except Exception as e:
            logger.error(f"❌ 发送消息到 {target} 失败: {str(e)}")
            raise
    
    def _split_message(self, message: str, max_length: int = 2000) -> List[str]:
        """分割消息，避免超过长度限制"""
        if len(message) <= max_length:
            return [message]
        
        parts = []
        current_part = []
        current_length = 0
        
        lines = message.split('\n')
        for line in lines:
            line_length = len(line) + 1
            
            if current_length + line_length > max_length:
                parts.append('\n'.join(current_part))
                current_part = [line]
                current_length = line_length
            else:
                current_part.append(line)
                current_length += line_length
        
        if current_part:
            parts.append('\n'.join(current_part))
        
        # 为每个部分添加页码
        if len(parts) > 1:
            for i, part in enumerate(parts):
                parts[i] = f"📄 消息部分 {i + 1}/{len(parts)}\n{part}"
        
        return parts
    
    def _is_error_log(self, log_content: str) -> bool:
        """判断是否为错误日志"""
        if not log_content:
            return False
        
        log_lower = log_content.lower()
        
        error_keywords = [
            'error', 'fail', 'failed', 'exception', 'uncaught', 'crash',
            'traceback', 'stack', 'errno', 'eperm', 'eacces', 'econn',
            '语法错误', '执行失败', '运行错误', '脚本错误', '异常',
            'command failed', 'not found', 'no such file', 'cannot',
            'permission denied', 'connection refused', 'timeout',
            'invalid', 'missing', 'undefined', 'null pointer'
        ]
        
        for keyword in error_keywords:
            if keyword in log_lower:
                return True
        
        return False
    
    def _extract_log(self, cron_id: int, cron_name: str, log_content: str, is_error_log: bool = False) -> Optional[Dict]:
        """提取日志内容"""
        try:
            if not log_content:
                return None
            
            lines = log_content.split('\n')
            max_lines = self.config.get("log_error_display_lines", 50)
            
            if is_error_log:
                if max_lines == 0:
                    recent_log = log_content
                    log_type = "完整错误日志"
                else:
                    error_lines = []
                    for i, line in enumerate(lines):
                        line_lower = line.lower()
                        if any(keyword in line_lower for keyword in ['error', 'fail', 'exception', 'traceback', '语法错误', '执行失败']):
                            start = max(0, i - 5)
                            end = min(len(lines), i + 6)
                            error_lines.extend(lines[start:end])
                    
                    if error_lines:
                        seen = set()
                        unique_lines = []
                        for line in error_lines:
                            if line not in seen:
                                seen.add(line)
                                unique_lines.append(line)
                        
                        recent_log = '\n'.join(unique_lines)
                        log_type = "错误上下文"
                    else:
                        display_lines = min(len(lines), max_lines)
                        recent_log = '\n'.join(lines[-display_lines:])
                        log_type = f"最后{display_lines}行日志"
            else:
                display_lines = min(len(lines), 10)
                recent_log = '\n'.join(lines[-display_lines:])
                log_type = f"最后{display_lines}行日志"
            
            return {
                'cron_id': cron_id,
                'cron_name': cron_name,
                'log': recent_log,
                'full_log': log_content,
                'is_error': is_error_log,
                'log_type': log_type,
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
        except Exception as e:
            logger.error(f"提取日志失败 (任务{cron_id}): {e}")
            return None
    
    def _prepare_summary_message(self, logs: List[Dict], error_logs: List[Dict] = None) -> str:
        """准备汇总消息"""
        if not logs:
            return "📭 暂无任务执行日志"
        
        success_count = 0
        error_count = 0
        warning_count = 0
        
        for log in logs:
            if log.get('is_error', False):
                error_count += 1
            elif log.get('log', '').lower().find('warn') >= 0:
                warning_count += 1
            else:
                success_count += 1
        
        display_count = self.config.get("log_schedule_display_count", 10)
        actual_display = min(len(logs), display_count)
        message = [
            f"⏰ 青龙面板任务执行日志汇总",
            f"📅 时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"📊 统计: 共 {len(logs)} 个任务（显示前{actual_display}个）",
            f"✅ 成功: {success_count} 个",
            f"⚠️ 警告: {warning_count} 个",
            f"❌ 错误: {error_count} 个",
            "─" * 30
        ]
        
        for i, log in enumerate(logs, 1):
            if i > display_count:
                break
                
            if log.get('is_error', False):
                status = "❌"
            elif log.get('log', '').lower().find('warn') >= 0:
                status = "⚠️"
            else:
                status = "✅"
            
            task_info = f"{status} {i}. {log['cron_name']} (ID: {log['cron_id']})"
            if log.get('is_error', False):
                task_info += " - 错误日志"
            message.append(task_info)
        
        if len(logs) > display_count:
            message.append(f"... 还有 {len(logs) - display_count} 个任务未显示")
        
        message.extend([
            "─" * 30,
            f"💡 当前显示设置: 显示前{display_count}个任务",
            f"💡 错误日志显示: {self.config.get('log_error_display_lines', 50)} 行 (0=完整日志)",
            f"💡 使用 /ql schedule count <数量> 修改显示数量",
            f"💡 使用 /ql schedule errors <行数> 修改错误日志显示行数"
        ])
        
        return '\n'.join(message)
    
    def _format_target(self, target_str: str, default_message_type: str) -> Optional[str]:
        """格式化目标字符串为标准格式: platform:message_type:session_id"""
        try:
            if not target_str or not str(target_str).strip():
                return None
            
            target_str = str(target_str).strip()
            
            # 如果已经是标准格式，直接返回
            if target_str.count(':') >= 2:
                parts = target_str.split(':', 2)  # 只分割成3部分
                platform = parts[0]
                message_type = parts[1]
                session_id = parts[2]
                
                # 验证消息类型是否正确
                if message_type not in ["GroupMessage", "FriendMessage"]:
                    logger.warning(f"消息类型 {message_type} 无效，使用默认类型 {default_message_type}")
                    message_type = default_message_type
                
                return f"{platform}:{message_type}:{session_id}"
            
            # 如果是纯数字（QQ号/群号）
            if target_str.isdigit():
                platform = "aiocqhttp"
                session_id = target_str
                return f"{platform}:{default_message_type}:{session_id}"
            
            # 其他格式，尝试解析
            logger.warning(f"目标格式不标准，尝试解析: {target_str}")
            platform = "aiocqhttp"
            session_id = target_str
            return f"{platform}:{default_message_type}:{session_id}"
            
        except Exception as e:
            logger.error(f"格式化目标失败: {target_str}, 错误: {e}")
            return None
    
    async def send_manual_push(self):
        """手动执行推送"""
        logger.info("开始手动推送定时日志...")
        await self._send_scheduled_logs()
    
    async def get_schedule_status(self) -> str:
        """获取定时推送状态"""
        enabled = self.config.get("log_schedule_enabled", True)
        schedule_time = self.config.get("log_schedule_time", "08:00,18:00")
        groups = self.config.get("log_schedule_groups", [])
        friends = self.config.get("log_schedule_friends", [])
        display_count = self.config.get("log_schedule_display_count", 10)
        error_lines = self.config.get("log_error_display_lines", 50)
        
        status = [
            f"📅 定时日志推送状态",
            f"状态: {'✅ 启用' if enabled else '❌ 禁用'}",
            f"推送时间: {schedule_time}",
            f"显示数量: {display_count} 个任务",
            f"错误日志: {error_lines} 行 ({'完整显示' if error_lines == 0 else '限制显示'})",
            f"推送群组: {len(groups)} 个",
            f"推送好友: {len(friends)} 个",
            f"日志保留: {self.config.get('log_retention_days', 7)} 天"
        ]
        
        if enabled:
            next_time = datetime.datetime.now() + datetime.timedelta(seconds=self._calculate_sleep_time())
            status.append(f"下次推送: {next_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return '\n'.join(status)
    
    async def get_detailed_logs(self, limit: int = 5) -> str:
        """获取详细日志"""
        try:
            display_count = self.config.get("log_schedule_display_count", 10)
            crons = await self.plugin.ql_api.get_crons()
            if not crons:
                return "📭 暂无定时任务"
            
            actual_limit = min(limit, display_count)
            message = [f"📋 最近任务执行详情 (显示前 {actual_limit} 个):"]
            
            for i, cron in enumerate(crons[:actual_limit], 1):
                cron_id = cron.get('id')
                cron_name = cron.get('name', f'任务{cron_id}')
                
                success, log_content = await self.plugin.ql_api.get_cron_log(cron_id)
                if success and log_content:
                    log_lower = log_content.lower()
                    if any(keyword in log_lower for keyword in ['error', 'fail', 'failed']):
                        status = "❌"
                    elif any(keyword in log_lower for keyword in ['warn', 'warning']):
                        status = "⚠️"
                    else:
                        status = "✅"
                    
                    lines = log_content.strip().split('\n')
                    last_lines = lines[-5:] if len(lines) > 5 else lines
                    
                    message.append(f"{status} {i}. {cron_name} (ID: {cron_id})")
                    message.append("   最近执行:")
                    for line in last_lines:
                        if line.strip():
                            message.append(f"     {line}")
                else:
                    message.append(f"❓ {i}. {cron_name} (ID: {cron_id})")
                    message.append("   暂无日志或获取失败")
                
                message.append("")
                
            message.append(f"💡 共 {len(crons)} 个任务，显示前 {actual_limit} 个")
            return '\n'.join(message)
            
        except Exception as e:
            return f"获取详细日志失败: {e}"
    
    async def update_display_count(self, count: int):
        """更新显示数量"""
        if count < 1:
            return "❌ 显示数量必须大于0"
        elif count > 50:
            return "⚠️ 显示数量最多50个，已设置为50"
        
        self.config["log_schedule_display_count"] = min(count, 50)
        return f"✅ 已设置定时推送显示数量为: {min(count, 50)} 个任务"
    
    async def update_error_lines(self, lines: int):
        """更新错误日志显示行数"""
        if lines < 0:
            return "❌ 行数不能为负数"
        elif lines > 500:
            return "⚠️ 行数最多500行，已设置为500"
        
        self.config["log_error_display_lines"] = min(lines, 500)
        lines_text = "完整错误日志" if lines == 0 else f"{min(lines, 500)} 行"
        return f"✅ 已设置错误日志显示为: {lines_text}"


@register("astrbot_plugin_qinglong_manage", "tension", "青龙面板管理插件", "1.3.3")
class QinglongPlugin(Star):
    """AstrBot 青龙插件主类"""
    
    PAGE_SIZE = 10
    
    def __init__(self, context: Context, config: dict):
        """初始化插件"""
        super().__init__(context)
        self.config = config
        self.context = context
        
        # 确保配置项是列表类型
        config_keys = ["log_push_groups", "log_push_friends", 
                      "log_schedule_groups", "log_schedule_friends"]
        for key in config_keys:
            if key not in config or not isinstance(config.get(key), list):
                config[key] = []
        
        # 清理配置中的空值
        for key in config_keys:
            if key in config and isinstance(config[key], list):
                config[key] = [item for item in config[key] if item and str(item).strip()]
        
        # 确保数值配置项存在
        if "log_schedule_display_count" not in config:
            config["log_schedule_display_count"] = 10
        if "log_error_display_lines" not in config:
            config["log_error_display_lines"] = 50
        
        # Cookie 自动保存配置默认值
        cookie_defaults = {
            "cookie_auto_enabled": True,
            "cookie_env_prefix": "JD_COOKIE",
            "cookie_enabled_groups": [],
            "cookie_match_regex": DEFAULT_COOKIE_REGEX,
            "cookie_min_pairs": 2,
            "cookie_reply_enabled": True,
        }
        for key, default in cookie_defaults.items():
            if key not in config:
                config[key] = default
        # 确保列表类型配置
        if not isinstance(config.get("cookie_enabled_groups"), list):
            config["cookie_enabled_groups"] = []
        
        # 京东短信验证码登录配置默认值
        sms_defaults = {
            "sms_login_enabled": True,
            "sms_enabled_groups": [],
            "sms_cooldown_seconds": 60,
            "sms_session_timeout": 300,
            "sms_reply_enabled": True,
            "jd_sms_app_id": 20019,
            "jd_sms_scene_id": 8,
            "jd_sms_send_url": "https://plogin.m.jd.com/cgi/ml/sendCode",
            "jd_sms_check_url": "https://plogin.m.jd.com/cgi/ml/checkCode",
            "jd_sms_cookie_url": "https://plogin.m.jd.com/cgi/ml/getCookie",
        }
        for key, default in sms_defaults.items():
            if key not in config:
                config[key] = default
        if not isinstance(config.get("sms_enabled_groups"), list):
            config["sms_enabled_groups"] = []

        # 浏览器登录助手配置默认值（真实 Chromium + 打码平台识别验证码）
        browser_defaults = {
            "jd_browser_enabled": True,
            "jd_browser_headless": True,
            "jd_browser_auto_install": True,
            "jd_browser_max_concurrent": 1,
            "jd_browser_max_retry": 4,
            "jd_browser_rotate_px_per_deg": 1.0,
            "jd_browser_rotate_direction": 1,
            "jd_captcha_username": "",
            "jd_captcha_password": "",
            "jd_captcha_api_url": "http://api.ttshitu.com/predict",
            "jd_captcha_rotate_typeid": "29",
            "jd_captcha_track_typeid": "48",
            "jd_captcha_gap_typeid": "33",
        }
        for key, default in browser_defaults.items():
            if key not in config:
                config[key] = default
        
        ql_host = config.get("qinglong_host", "http://localhost:5700")
        ql_client_id = config.get("qinglong_client_id", "")
        ql_client_secret = config.get("qinglong_client_secret", "")
        
        self.ql_api = QinglongAPI(ql_host, ql_client_id, ql_client_secret)
        self.log_monitor = TaskLogMonitor(self.ql_api, self, config)
        self.schedule_manager = LogScheduleManager(self, config)
        self.jd_sms = JDSmsLogin(config)
        self.browser_login = BrowserLoginHelper(config, self)
        self.last_task_log = None
        self.log_check_task = None
        self.check_interval = 30
        # 京东短信登录状态：uid -> {phone, uuid, sms_key, sent_at}
        self.sms_sessions: Dict[str, Dict] = {}
        self.sms_uid_cooldown: Dict[str, float] = {}    # uid -> 上次发码时间
        self.sms_phone_cooldown: Dict[str, float] = {}  # phone -> 上次发码时间
        self.sms_intents: Dict[str, float] = {}         # uid -> 触发"登录"的时间（必须先登录才能发手机号）
        
        logger.info("青龙面板插件已加载 (v1.5.15)")
        logger.info(f"  Host: {ql_host}")
        logger.info(f"  实时推送功能: {'启用' if config.get('log_push_enabled', True) else '禁用'}")
        logger.info(f"  定时推送功能: {'启用' if config.get('log_schedule_enabled', True) else '禁用'}")
        
        # 显示推送配置信息
        display_count = config.get("log_schedule_display_count", 10)
        error_lines = config.get("log_error_display_lines", 50)
        schedule_groups = config.get("log_schedule_groups", [])
        schedule_friends = config.get("log_schedule_friends", [])
        
        logger.info(f"  定时推送设置: 显示{display_count}个任务，错误日志{error_lines}行")
        logger.info(f"  定时推送群组: {len(schedule_groups)} 个")
        logger.info(f"  定时推送好友: {len(schedule_friends)} 个")
        
        # 检查配置格式并转换为标准格式
        self._fix_config_format()
        
        # 启动定时推送任务
        if config.get("log_schedule_enabled", True):
            asyncio.create_task(self.schedule_manager.start_schedule())
            logger.info("  定时推送: 已启用")
    
    def _fix_config_format(self):
        """修复配置格式"""
        config_keys = ["log_push_groups", "log_push_friends", 
                      "log_schedule_groups", "log_schedule_friends"]
        
        for key in config_keys:
            if key in self.config and isinstance(self.config[key], list):
                fixed_list = []
                for item in self.config[key]:
                    if item and str(item).strip():
                        # 尝试格式化（键名以 friends 结尾的是好友配置）
                        if key.endswith("friends"):
                            formatted = self.schedule_manager._format_target(item, "FriendMessage")
                        else:
                            formatted = self.schedule_manager._format_target(item, "GroupMessage")
                        
                        if formatted:
                            fixed_list.append(formatted)
                            logger.info(f"  格式化配置 {key}: {item} -> {formatted}")
                        else:
                            logger.warning(f"  无法格式化配置项: {item}")
                
                self.config[key] = fixed_list
    
    def _start_log_check_task(self):
        """启动日志检查任务"""
        async def check_logs():
            while True:
                try:
                    await self._check_and_send_logs()
                except Exception as e:
                    logger.error(f"检查日志时发生错误: {e}")
                await asyncio.sleep(self.check_interval)
        
        if self.log_check_task is None or self.log_check_task.done():
            self.log_check_task = asyncio.create_task(check_logs())
            logger.info("日志检查任务已启动")
    
    async def _check_and_send_logs(self):
        """检查并发送待处理的日志"""
        self.log_monitor.clear_old_logs(max_age_minutes=60)
        
        pending_logs = self.log_monitor.get_pending_logs()
        if not pending_logs:
            return
        
        logger.info(f"发现 {len(pending_logs)} 条待发送日志")
        
        for log_entry in pending_logs:
            await self._notify_log_available(log_entry)
    
    async def _notify_log_available(self, log_entry: Dict):
        """通知用户有可用的日志"""
        cron_id = log_entry.get('cron_id')
        cron_name = log_entry.get('cron_name')
        timestamp = log_entry.get('timestamp')
        
        logger.info(f"任务 {cron_id} ({cron_name}) 的日志已就绪，时间: {timestamp}")
        
        if self.config.get("log_save_to_file", False):
            await self._save_log_to_file(log_entry)
    
    async def _save_log_to_file(self, log_entry: Dict):
        """将日志保存到文件"""
        try:
            import os
            log_dir = "data/qinglong_logs"
            os.makedirs(log_dir, exist_ok=True)
            
            filename = f"{log_dir}/task_{log_entry['cron_id']}_{int(time.time())}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(log_entry['message'])
            
            logger.info(f"日志已保存到文件: {filename}")
        except Exception as e:
            logger.error(f"保存日志到文件失败: {e}")
    
    def remove_log_by_id(self, cron_id: int):
        """从待发送队列中移除指定ID的日志（代理方法）"""
        self.log_monitor.remove_log(cron_id)
    
    @filter.command("ql")
    async def ql_command(self, event: AstrMessageEvent):
        '''青龙面板管理命令'''
        if not self.ql_api:
            yield event.plain_result("❌ 插件未正确初始化，请检查配置")
            return
        
        parts = event.message_str.strip().split()
        command = parts[1].lower() if len(parts) > 1 else "help"
        
        handlers = {
            "help": self._handle_help,
            "envs": self._handle_envs,
            "list": self._handle_envs,
            "add": self._handle_add_env,
            "update": self._handle_update_env,
            "delete": self._handle_delete_env,
            "enable": self._handle_enable_env,
            "disable": self._handle_disable_env,
            "ls": self._handle_crons,
            "run": self._handle_run_cron,
            "stop": self._handle_stop_cron,
            "log": self._handle_cron_log,
            "cron": self._handle_cron_action,
            "info": self._handle_info,
            "push": self._handle_push_config,
            "lastlog": self._handle_last_log,
            "pending": self._handle_pending_logs,
            "sendlog": self._handle_send_log,
            "schedule": self._handle_schedule,
            "cookie": self._handle_cookie_cmd,
            "sms": self._handle_sms_cmd,
        }
        
        handler = handlers.get(command)
        if handler:
            async for result in handler(event, parts):
                yield result
        else:
            yield event.plain_result(f"❌ 未知命令: {command}\n使用 /ql 查看帮助")
                
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_confirm_message(self, event: AstrMessageEvent):
        """处理错误日志推送确认消息"""
        # 函数内代码统一8个空格缩进
        user_response = event.message_str.strip()
        confirm_keywords = ["是", "需要", "推送错误日志", "推送", "发送", "yes", "y", "确认"]
        cancel_keywords = ["否", "不需要", "取消", "不推送", "no", "n", "取消推送"]
        
        # 检查是否是确认或取消关键词
        is_confirm_keyword = user_response in confirm_keywords
        is_cancel_keyword = user_response in cancel_keywords
        
        if not is_confirm_keyword and not is_cancel_keyword:
            return
            
        # 获取当前会话的唯一标识
        target = event.unified_msg_origin
        
        try:
            # 调用调度管理器处理确认
            handled = await self.schedule_manager.check_and_send_error_logs(target, user_response.lower())
            
            if not handled:
                # 如果没有处理（不在等待状态或已超时），忽略消息
                pass
                
        except Exception as e:
            logger.error(f"处理错误日志确认时发生错误: {e}")
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_cookie_auto(self, event: AstrMessageEvent):
        """自动识别群消息中的 Cookie 并保存/更新到青龙环境变量
        
        规则：
        - 仅处理群消息（GroupMessage）
        - 消息中需包含 key=value;key=value 形式的 Cookie 文本
        - 每个用户保存为独立环境变量（前缀_昵称），备注中记录 uid 标记
        - 同一用户再次发送时，自动更新其上次保存的变量，而不是新增
        """
        try:
            # 功能开关
            if not self.config.get("cookie_auto_enabled", True):
                return
            
            # 仅处理群消息
            if not self._is_group_message(event):
                return
            
            # 跳过命令消息
            message_str = (event.message_str or "").strip()
            if not message_str or message_str.startswith("/"):
                return
            
            # 群白名单（配置了才限制）
            enabled_groups = self.config.get("cookie_enabled_groups", [])
            if enabled_groups:
                group_id = self._get_group_id(event)
                if group_id is not None and str(group_id) not in [str(g).strip() for g in enabled_groups]:
                    return
            
            # 提取 Cookie
            cookie = self._extract_cookie(message_str)
            if not cookie:
                return
            
            user_id = self._get_sender_id(event)
            nickname = self._get_sender_name(event)
            group_id = self._get_group_id(event)
            
            logger.info(f"检测到Cookie: 用户={nickname or user_id} (uid={user_id}), 群={group_id}, 长度={len(cookie)}")
            
            success, is_update, env_name, error = await self._save_or_update_cookie(
                user_id=user_id, nickname=nickname, group_id=group_id, cookie=cookie
            )
            
            if not self.config.get("cookie_reply_enabled", True):
                return
            
            masked = self._mask_cookie(cookie)
            if success:
                action = "🔄 已更新" if is_update else "✅ 已保存"
                reply = (
                    f"{action}你的Cookie\n"
                    f"📛 环境变量: {env_name}\n"
                    f"🔑 值: {masked}\n"
                    f"⏰ 时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"
                )
            else:
                reply = f"❌ Cookie保存失败: {error}\n请检查青龙面板配置或稍后重试"
            
            await self.context.send_message(event.unified_msg_origin, MessageChain().message(reply))
            
        except Exception as e:
            logger.error(f"自动保存Cookie时发生错误: {e}")
            logger.error(traceback.format_exc())
    
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_sms_login(self, event: AstrMessageEvent):
        """京东短信验证码登录：先发送"登录"触发，再发送手机号/验证码完成登录
        
        交互流程：
        1. 群友发送「登录」→ 插件引导发送手机号
        2. 群友发送手机号（11位，1开头）→ 插件调用京东发码接口下发短信验证码
        3. 群友把收到的验证码（4-6位）发到群里 → 插件校验并换取 Cookie
        4. 登录成功后自动保存/更新该用户的青龙环境变量
        
        安全约束（防短信轰炸）：
        - 必须先发送「登录」触发流程，未触发时发手机号不动作
        - 同一发送者限频（sms_cooldown_seconds）
        - 同一手机号限频（sms_cooldown_seconds）
        - 验证码回传必须由发起登录的同一用户发送
        """
        try:
            if not self.config.get("sms_login_enabled", True):
                return
            if not self._is_group_message(event):
                return
            
            message_str = (event.message_str or "").strip()
            if not message_str:
                return
            
            user_id = self._get_sender_id(event)
            
            # 群白名单（配置了才限制）
            enabled_groups = self.config.get("sms_enabled_groups", [])
            if enabled_groups:
                group_id = self._get_group_id(event)
                if group_id is not None and str(group_id) not in [str(g).strip() for g in enabled_groups]:
                    return
            
            # 触发词"登录"：启动短信验证码登录流程
            # 兼容 "/登录" "/登陆"（用户习惯用 / 唤醒机器人）
            trigger_text = message_str[1:].strip() if message_str.startswith("/") else message_str
            if trigger_text in ("登录", "登陆"):
                await self._process_sms_start(event, user_id)
                return
            
            # 其他命令消息跳过
            if message_str.startswith("/"):
                return
            
            # 提取消息中的纯数字部分
            digits = re.sub(r'\D', '', message_str)
            if not digits:
                return
            
            # 手机号：11位且以1开头
            if len(digits) == 11 and digits.startswith("1"):
                await self._process_sms_phone(event, user_id, digits)
                return
            
            # 验证码：4-6位纯数字
            if 4 <= len(digits) <= 6:
                await self._process_sms_code(event, user_id, digits)
        
        except Exception as e:
            logger.error(f"处理短信登录消息时发生错误: {e}")
            logger.error(traceback.format_exc())
    
    async def _process_sms_start(self, event: AstrMessageEvent, user_id: str):
        """处理"登录"触发词：启动短信验证码登录流程"""
        now = time.time()
        self.sms_intents[user_id] = now
        # 清理该用户可能存在的旧登录会话
        self.sms_sessions.pop(user_id, None)
        logger.info(f"用户 {user_id} 触发了京东短信登录流程")
        await self._sms_reply(
            event,
            "📱 好的，开始京东短信验证码登录\n"
            "请发送你的京东绑定手机号（11位数字）"
        )
    
    async def _process_sms_phone(self, event: AstrMessageEvent, user_id: str, phone: str):
        """处理用户发送的手机号：需先触发"登录"才允许发码"""
        now = time.time()
        
        # 必须先发送"登录"触发流程，防止直接对任意手机号发码
        intent_time = self.sms_intents.get(user_id, 0)
        intent_timeout = int(self.config.get("sms_session_timeout", 300))
        if now - intent_time > intent_timeout:
            await self._sms_reply(
                event,
                "ℹ️ 如需京东登录，请先发送「登录」两个字开始流程"
            )
            return
        
        cooldown = int(self.config.get("sms_cooldown_seconds", 60))
        
        # 同一发送者限频
        last_uid = self.sms_uid_cooldown.get(user_id, 0)
        if now - last_uid < cooldown:
            remain = int(cooldown - (now - last_uid))
            await self._sms_reply(event, f"⏳ 发送过于频繁，请 {remain} 秒后再试")
            return
        
        # 同一手机号限频（防短信轰炸）
        last_phone = self.sms_phone_cooldown.get(phone, 0)
        if now - last_phone < cooldown:
            remain = int(cooldown - (now - last_phone))
            await self._sms_reply(event, f"⏳ 该手机号发送过于频繁，请 {remain} 秒后再试")
            return
        
        # 清理该用户可能存在的旧会话
        self.sms_sessions.pop(user_id, None)

        browser_login = getattr(self, "browser_login", None)
        if browser_login is not None and self.config.get("jd_browser_enabled", True):
            # 浏览器助手发码（真实 Chromium + 打码平台破解验证码）
            session_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
            ok, msg = await browser_login.start_sms_login(session_id, phone)
            if not ok:
                logger.warning(f"京东浏览器发码失败: 手机号={phone[:3]}****{phone[7:]}, 原因={msg}")
                await self._sms_reply(
                    event,
                    f"❌ 验证码发送失败: {msg}\n"
                    f"可能需要配置打码平台账号，或稍后重试"
                )
                return
            self.sms_sessions[user_id] = {
                "phone": phone,
                "browser_session": session_id,
                "sent_at": now,
            }
            self.sms_uid_cooldown[user_id] = now
            self.sms_phone_cooldown[phone] = now
            self.sms_intents.pop(user_id, None)  # 已进入发码阶段，清除登录意图

            timeout_min = max(int(self.config.get("sms_session_timeout", 300)) // 60, 1)
            masked_phone = phone[:3] + "****" + phone[7:]
            logger.info(f"京东验证码已发送(浏览器): 用户={user_id}, 手机号={masked_phone}")
            await self._sms_reply(
                event,
                f"📱 验证码已发送至 {masked_phone}\n"
                f"请将收到的验证码发到群里完成登录\n"
                f"⏰ {timeout_min} 分钟内有效"
            )
            return

        # 回退：旧 HTTP 接口（京东已风控，一般不生效）
        uuid_str = str(uuid.uuid4())
        ok, msg, info = await self.jd_sms.send_code(phone, uuid_str)
        if not ok:
            logger.warning(f"京东发码失败: 手机号={phone[:3]}****{phone[7:]}, 原因={msg}")
            await self._sms_reply(
                event,
                f"❌ 验证码发送失败: {msg}\n可能是接口风控或参数变化，可稍后重试或联系管理员检查日志"
            )
            return
        
        sms_key = info.get("smsKey", "") or ""
        self.sms_sessions[user_id] = {
            "phone": phone,
            "uuid": uuid_str,
            "sms_key": sms_key,
            "sent_at": now,
        }
        self.sms_uid_cooldown[user_id] = now
        self.sms_phone_cooldown[phone] = now
        self.sms_intents.pop(user_id, None)  # 已进入发码阶段，清除登录意图
        
        timeout_min = max(int(self.config.get("sms_session_timeout", 300)) // 60, 1)
        masked_phone = phone[:3] + "****" + phone[7:]
        logger.info(f"京东验证码已发送: 用户={user_id}, 手机号={masked_phone}")
        await self._sms_reply(
            event,
            f"📱 验证码已发送至 {masked_phone}\n"
            f"请将收到的验证码发到群里完成登录\n"
            f"⏰ {timeout_min} 分钟内有效"
        )
    
    async def _process_sms_code(self, event: AstrMessageEvent, user_id: str, code: str):
        """处理用户发送的验证码：校验并换取 Cookie，更新青龙环境变量"""
        session = self.sms_sessions.get(user_id)
        if not session:
            return  # 无进行中的登录流程，静默忽略
        
        now = time.time()
        timeout = int(self.config.get("sms_session_timeout", 300))
        if now - session["sent_at"] > timeout:
            self.sms_sessions.pop(user_id, None)
            await self._sms_reply(event, "⏰ 验证码已过期，请重新发送手机号获取验证码")
            return
        
        phone = session["phone"]

        cookie = ""
        browser_session = session.get("browser_session")
        browser_login = getattr(self, "browser_login", None)
        if browser_session and browser_login is not None:
            # 浏览器登录流程：输入验证码 → 登录 → 提取 Cookie
            ok, msg, cookie = await browser_login.submit_sms_code(browser_session, code)
            if not ok:
                logger.warning(f"京东浏览器登录失败: 用户={user_id}, 原因={msg}")
                await self._sms_reply(event, f"❌ 登录失败: {msg}\n请检查验证码是否正确，或重新发送手机号获取新验证码")
                return
        else:
            # 回退：旧 HTTP 接口流程
            ok, msg, info = await self.jd_sms.check_code(
                phone, code, session["uuid"], session.get("sms_key", "")
            )
            if not ok:
                logger.warning(f"京东验证码校验失败: 用户={user_id}, 原因={msg}")
                await self._sms_reply(event, f"❌ 验证码校验失败: {msg}\n请检查验证码是否正确，或重新发送手机号获取新验证码")
                return

            ticket = info.get("ticket", "")
            if not ticket:
                self.sms_sessions.pop(user_id, None)
                await self._sms_reply(event, "❌ 未获取到登录凭证（ticket），请重新发送手机号重试")
                return

            ok2, msg2, info2 = await self.jd_sms.get_cookie(ticket)
            if not ok2:
                self.sms_sessions.pop(user_id, None)
                await self._sms_reply(
                    event,
                    f"❌ 获取Cookie失败: {msg2}\n可能被风控拦截，请稍后重试"
                )
                return

            cookie = info2.get("cookie", "")
            if not cookie:
                self.sms_sessions.pop(user_id, None)
                await self._sms_reply(event, "❌ 获取到的Cookie为空，请重新发送手机号重试")
                return
        
        # 复用 Cookie 保存/更新逻辑：按用户保存独立变量，同用户再登录自动更新
        nickname = self._get_sender_name(event)
        group_id = self._get_group_id(event)
        success, is_update, env_name, error = await self._save_or_update_cookie(
            user_id=user_id, nickname=nickname, group_id=group_id, cookie=cookie
        )
        self.sms_sessions.pop(user_id, None)
        
        masked_phone = phone[:3] + "****" + phone[7:]
        if success:
            action = "🔄 已更新" if is_update else "✅ 已保存"
            masked = self._mask_cookie(cookie)
            logger.info(f"京东短信登录成功: 用户={nickname or user_id}, 变量={env_name}")
            pin = self._extract_pin(cookie)
            pin_text = f"👤 京东账号: {pin}\n" if pin else ""
            await self._sms_reply(
                event,
                f"{action}你的京东Cookie\n"
                f"📛 环境变量: {env_name}\n"
                f"🔑 值: {masked}\n"
                f"{pin_text}"
                f"📱 手机号: {masked_phone}"
            )
        else:
            await self._sms_reply(event, f"❌ Cookie保存到青龙失败: {error}\n请检查青龙面板配置")
    
    async def _sms_reply(self, event: AstrMessageEvent, text: str):
        """发送短信登录相关回复（受回复开关控制）"""
        if self.config.get("sms_reply_enabled", True):
            await self.context.send_message(event.unified_msg_origin, MessageChain().message(text))
    
    def _is_group_message(self, event: AstrMessageEvent) -> bool:
        """判断消息是否为群消息（兼容 unified_msg_origin 与 message_obj 两种判断）"""
        umo = event.unified_msg_origin or ""
        if "GroupMessage" in umo:
            return True
        if "FriendMessage" in umo:
            return False
        try:
            mobj = getattr(event, "message_obj", None)
            mtype = getattr(mobj, "message_type", None)
            if mtype is None and isinstance(mobj, dict):
                mtype = mobj.get("message_type")
            mtype_str = str(mtype or "").lower()
            if mtype_str:
                if any(k in mtype_str for k in ("group", "群")):
                    return True
                if any(k in mtype_str for k in ("private", "friend", "c2c", "私聊")):
                    return False
        except Exception:
            pass
        return False
    
    def _get_sender_id(self, event: AstrMessageEvent) -> str:
        """获取发送者ID"""
        try:
            return str(event.get_sender_id())
        except Exception:
            pass
        try:
            return str(event.message_obj.sender.user_id)
        except Exception:
            return "unknown"
    
    def _get_sender_name(self, event: AstrMessageEvent) -> str:
        """获取发送者昵称"""
        try:
            name = event.get_sender_name()
            if name:
                return str(name).strip()
        except Exception:
            pass
        try:
            return str(event.message_obj.sender.nickname or "").strip()
        except Exception:
            return ""
    
    def _get_group_id(self, event: AstrMessageEvent) -> Optional[str]:
        """获取群号"""
        try:
            if event.message_obj and event.message_obj.group_id:
                return str(event.message_obj.group_id)
        except Exception:
            pass
        umo = event.unified_msg_origin or ""
        if "GroupMessage" in umo:
            parts = umo.split(":")
            if parts:
                return parts[-1]
        return None
    
    def _extract_cookie(self, text: str) -> Optional[str]:
        """从消息文本中提取 Cookie，无法识别时返回 None"""
        if not text:
            return None
        
        regex = self.config.get("cookie_match_regex", DEFAULT_COOKIE_REGEX)
        try:
            match = re.search(regex, text)
        except re.error:
            logger.warning("Cookie匹配正则无效，使用默认正则")
            match = re.search(DEFAULT_COOKIE_REGEX, text)
        
        if not match:
            return None
        
        cookie = match.group(0).strip().strip(';').strip()
        
        # 校验键值对数量，防止误触发
        min_pairs = max(int(self.config.get("cookie_min_pairs", 2)), 1)
        pairs = [p for p in cookie.split(';') if '=' in p and p.split('=', 1)[1].strip()]
        if len(pairs) < min_pairs:
            return None
        
        return cookie
    
    def _mask_cookie(self, cookie: str) -> str:
        """掩码 Cookie 值，避免在群内暴露完整凭证"""
        parts = [p for p in cookie.split(';') if p.strip()]
        masked = []
        for p in parts:
            if '=' in p:
                k, v = p.split('=', 1)
                v = v.strip()
                if not v:
                    masked.append(f"{k}=****")
                elif len(v) <= 4:
                    masked.append(f"{k}={v[0]}****")
                else:
                    masked.append(f"{k}={v[:4]}***({len(v)}位)")
            else:
                masked.append(p.strip())
        return ';'.join(masked)
    
    def _extract_pin(self, cookie: str) -> str:
        """从 Cookie 中提取京东账号标识 pt_pin，用于区分同一用户的多个账号"""
        if not cookie:
            return ""
        for part in cookie.split(';'):
            part = part.strip()
            if part.lower().startswith('pt_pin='):
                return part.split('=', 1)[1].strip()
        return ""
    
    def _build_cookie_remark(self, user_id: str, group_id: Optional[str], pin: str = "") -> str:
        """构建 Cookie 环境变量的备注信息（uid 标识发送者，pin 标识京东账号）"""
        now_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        remark = f"AstrBot自动Cookie | {COOKIE_REMARK_TAG} | uid:{user_id}"
        if pin:
            remark += f" | pin:{pin}"
        if group_id:
            remark += f" | group:{group_id}"
        remark += f" | 更新:{now_str}"
        return remark
    
    async def _find_user_cookie_env(self, user_id: str, prefix: str, pin: str = "") -> Optional[Dict]:
        """查找用户已保存的 Cookie 环境变量
        
        匹配规则（同一用户可拥有多个京东账号）：
        - 先按 uid + pin 精确匹配（再次登录同一账号时更新原变量）
        - 若 pin 为空或未匹配到：该用户仅有 1 个无 pin 标记的旧版变量时，视为同一账号更新并补 pin
        - 该用户已有多个变量但当前 pin 不匹配：返回 None，走新建逻辑
        """
        envs = await self.ql_api.get_envs("")
        uid_tag = f"uid:{user_id}"
        candidates = []
        for env in envs:
            name = env.get('name', '') or ''
            remarks = env.get('remarks', '') or ''
            if name.startswith(prefix) and COOKIE_REMARK_TAG in remarks and uid_tag in remarks:
                candidates.append(env)
        
        if not candidates:
            return None
        
        if pin:
            pin_tag = f"pin:{pin}"
            for env in candidates:
                if pin_tag in (env.get('remarks', '') or ''):
                    return env
            # 兼容升级前的旧变量：该用户只有 1 个变量且备注无 pin -> 视为同一账号
            old_vars = [e for e in candidates if 'pin:' not in (e.get('remarks', '') or '')]
            if len(candidates) == 1 and old_vars:
                return old_vars[0]
            return None
        
        # 无 pin 信息（如非京东 Cookie）：仅该用户 1 个变量时更新它
        if len(candidates) == 1:
            return candidates[0]
        return None
    
    async def _save_or_update_cookie(
        self, user_id: str, nickname: str, group_id: Optional[str], cookie: str
    ) -> Tuple[bool, bool, str, str]:
        """保存或更新用户的 Cookie
        
        同一用户可挂多个京东账号：按 pt_pin 区分，同一账号再次登录更新原变量，
        不同账号各自新建独立变量。
        返回: (是否成功, 是否更新而非新增, 环境变量名, 错误信息)
        """
        prefix = str(self.config.get("cookie_env_prefix", "JD_COOKIE")).strip() or "JD_COOKIE"
        pin = self._extract_pin(cookie)
        
        # 构建环境变量名：前缀_昵称（清理非法字符，避免超长）
        display_name = nickname or user_id
        clean_name = re.sub(r'[^\w\u4e00-\u9fa5]', '_', display_name)[:20]
        env_name = f"{prefix}_{clean_name}"
        remark = self._build_cookie_remark(user_id, group_id, pin)
        
        # 按 uid + pin 查找该用户的该账号 -> 更新（同一账号再次登录时走这里）
        existing = await self._find_user_cookie_env(user_id, prefix, pin)
        if existing:
            env_name = existing.get('name', env_name)
            success, msg = await self.ql_api.update_env(
                existing.get('id'), env_name, cookie, remark
            )
            if success:
                logger.info(f"已更新用户 {nickname or user_id} 的Cookie变量: {env_name} (pin={pin or '未知'})")
                return True, True, env_name, ""
            return False, True, env_name, msg
        
        # 名称冲突处理：同名已被他人占用时追加序号
        all_envs = await self.ql_api.get_envs("")
        used_names = set(e.get('name', '') for e in all_envs)
        base_name = env_name
        suffix = 2
        while env_name in used_names:
            env_name = f"{base_name}_{suffix}"
            suffix += 1
        
        success, msg = await self.ql_api.add_env(env_name, cookie, remark)
        if success:
            logger.info(f"已保存用户 {nickname or user_id} 的Cookie变量: {env_name} (pin={pin or '未知'})")
            return True, False, env_name, ""
        return False, False, env_name, msg
    
    async def _handle_cookie_cmd(self, event: AstrMessageEvent, parts: list):
        """处理 Cookie 自动保存相关命令"""
        if len(parts) < 3:
            yield event.plain_result(
                "🍪 Cookie自动保存功能:\n"
                "/ql cookie status - 查看状态\n"
                "/ql cookie list - 查看已保存的Cookie变量\n"
                "/ql cookie enable - 启用自动保存\n"
                "/ql cookie disable - 禁用自动保存"
            )
            return
        
        subcommand = parts[2].lower()
        
        if subcommand == "status":
            enabled = self.config.get("cookie_auto_enabled", True)
            prefix = self.config.get("cookie_env_prefix", "JD_COOKIE")
            groups = self.config.get("cookie_enabled_groups", [])
            reply = (
                f"🍪 Cookie自动保存状态:\n"
                f"状态: {'🟢 已启用' if enabled else '🔴 已禁用'}\n"
                f"变量前缀: {prefix}\n"
                f"保存方式: 每人可挂多个账号，同一账号再发自动更新\n"
                f"允许的群: {', '.join(str(g) for g in groups) if groups else '全部群'}"
            )
            yield event.plain_result(reply)
        
        elif subcommand == "list":
            prefix = str(self.config.get("cookie_env_prefix", "JD_COOKIE")).strip() or "JD_COOKIE"
            envs = await self.ql_api.get_envs("")
            cookie_envs = [
                e for e in envs
                if (e.get('name', '') or '').startswith(prefix)
                and COOKIE_REMARK_TAG in (e.get('remarks', '') or '')
            ]
            if not cookie_envs:
                yield event.plain_result("🍪 暂无已保存的Cookie变量")
                return
            
            result = f"🍪 已保存的Cookie变量 (共 {len(cookie_envs)} 个):\n\n"
            for env in cookie_envs:
                value = self._mask_cookie(env.get('value', '') or '')
                remarks = env.get('remarks', '') or ''
                pin = ""
                for field in remarks.split("|"):
                    field = field.strip()
                    if field.startswith("pin:"):
                        pin = field[4:]
                        break
                pin_text = f"  👤 京东账号: {pin}\n" if pin else ""
                result += f"📛 {env.get('name')}\n"
                result += f"  ID: {env.get('id')}\n"
                result += f"  值: {value}\n"
                result += pin_text
                result += f"  备注: {remarks}\n\n"
            yield event.plain_result(result)
        
        elif subcommand == "enable":
            self.config["cookie_auto_enabled"] = True
            yield event.plain_result("✅ 已启用Cookie自动保存\n用户在群内发送Cookie后将自动保存到青龙环境变量")
        
        elif subcommand == "disable":
            self.config["cookie_auto_enabled"] = False
            yield event.plain_result("✅ 已禁用Cookie自动保存")
        
        else:
            yield event.plain_result(f"❌ 未知的Cookie子命令: {subcommand}")
    
    async def _handle_sms_cmd(self, event: AstrMessageEvent, parts: list):
        """处理京东短信验证码登录相关命令"""
        if len(parts) < 3:
            yield event.plain_result(
                "📱 京东短信验证码登录:\n"
                "/ql sms status - 查看状态\n"
                "/ql sms enable - 启用\n"
                "/ql sms disable - 禁用\n\n"
                "使用方式：\n"
                "1. 在群里发送「登录」两个字开始流程\n"
                "2. 按提示发送手机号，如 13800138000\n"
                "3. 收到短信后，把验证码发到群里（如 123456）\n"
                "4. 登录成功后自动保存/更新你的京东Cookie\n\n"
                "⚠️ 同一手机号/用户有限频，防止被滥用"
            )
            return
        
        subcommand = parts[2].lower()
        
        if subcommand == "status":
            enabled = self.config.get("sms_login_enabled", True)
            groups = self.config.get("sms_enabled_groups", [])
            cooldown = self.config.get("sms_cooldown_seconds", 60)
            active = len(self.sms_sessions)
            browser_on = self.config.get("jd_browser_enabled", True)
            captcha_user = (self.config.get("jd_captcha_username") or "").strip()
            captcha_ok = "✅ 已配置" if captcha_user else "❌ 未配置（验证码将无法破解）"
            yield event.plain_result(
                f"📱 京东短信登录状态:\n"
                f"状态: {'🟢 已启用' if enabled else '🔴 已禁用'}\n"
                f"浏览器登录: {'🟢 开启' if browser_on else '🔴 关闭'}\n"
                f"打码平台: {captcha_ok}\n"
                f"允许的群: {', '.join(str(g) for g in groups) if groups else '全部群'}\n"
                f"发码间隔: {cooldown} 秒\n"
                f"进行中的登录: {active} 个"
            )
        
        elif subcommand == "enable":
            self.config["sms_login_enabled"] = True
            yield event.plain_result("✅ 已启用京东短信验证码登录\n群友发送手机号即可开始")
        
        elif subcommand == "disable":
            self.config["sms_login_enabled"] = False
            yield event.plain_result("✅ 已禁用京东短信验证码登录")
        
        else:
            yield event.plain_result(f"❌ 未知的短信登录子命令: {subcommand}")
    
    async def _handle_help(self, event: AstrMessageEvent, parts: list):
        """显示帮助信息"""
        help_text = """📦 青龙面板管理插件 v1.5.15

📋 环境变量:
/ql envs [关键词] [页码] - 查看环境变量
/ql add <名称> <值> [备注] - 添加
/ql update <名称> <值> - 更新（按名称）
/ql update id:<ID> <值> - 更新（按ID）
/ql delete <名称> - 删除
/ql enable/disable <名称> - 启用/禁用

⏰ 定时任务:
/ql ls [页码] - 查看任务列表
/ql run <任务ID> - 执行任务（自动监控并保存日志）
/ql run <任务ID> silent - 执行任务（静默模式，不保存日志）
/ql stop <任务ID> - 停止任务
/ql log <任务ID> - 查看日志
/ql cron enable/disable <任务ID> - 启用/禁用
/ql cron pin/unpin <任务ID> - 置顶/取消
/ql cron delete <任务ID> - 删除任务

🔔 日志功能:
/ql lastlog - 查看最近一次任务日志
/ql pending - 查看待发送的日志列表
/ql sendlog <任务ID> - 发送指定任务的日志到当前聊天
/ql push status - 查看实时推送状态
/ql push enable/disable - 启用/禁用实时推送
/ql push add group <目标> - 添加实时推送群（支持多种格式：群号、机器人:GroupMessage:群号）
/ql push remove group <目标> - 移除实时推送群
/ql push add friend <目标> - 添加实时推送好友（支持多种格式：QQ号、机器人:FriendMessage:QQ号）
/ql push remove friend <目标> - 移除实时推送好友

⏰ 定时推送:
/ql schedule status - 查看定时推送状态
/ql schedule enable/disable - 启用/禁用定时推送
/ql schedule logs [数量] - 查看详细任务日志（默认5个）
/ql schedule push - 手动执行定时推送
/ql schedule count <数量> - 设置定时推送显示的任务数量（1-50）
/ql schedule errors <行数> - 设置错误日志显示行数(0=完整日志，最大500)
/ql schedule add group <目标> - 添加定时推送群（支持多种格式）
/ql schedule remove group <目标> - 移除定时推送群
/ql schedule add friend <目标> - 添加定时推送好友（支持多种格式）
/ql schedule remove friend <目标> - 移除定时推送好友
/ql schedule time <时间> - 设置推送时间，如 08:00,18:00

📊 系统信息:
/ql info - 查看系统信息

🍪 Cookie自动保存:
群内直接发送 Cookie（如 pt_key=xxx;pt_pin=xxx）自动保存到青龙环境变量，
同一账号再次发送自动更新；同一人可挂多个账号，互不覆盖
/ql cookie status - 查看状态
/ql cookie list - 查看已保存的Cookie变量（含京东账号）
/ql cookie enable/disable - 启用/禁用

📱 京东短信登录:
群里发送「登录」→按提示发手机号→把验证码发到群里，自动登录并更新你的Cookie
/ql sms status - 查看状态
/ql sms enable/disable - 启用/禁用"""
        yield event.plain_result(help_text)
    
    async def _handle_last_log(self, event: AstrMessageEvent, parts: list):
        """查看最近一次任务日志"""
        if not self.last_task_log:
            yield event.plain_result("📭 暂无最近任务日志")
            return
        
        log = self.last_task_log
        yield event.plain_result(log['message'])
    
    async def _handle_pending_logs(self, event: AstrMessageEvent, parts: list):
        """查看待发送的日志列表"""
        self.log_monitor.clear_old_logs(max_age_minutes=60)
        
        pending_logs = self.log_monitor.get_pending_logs()
        if not pending_logs:
            yield event.plain_result("📭 暂无待发送的日志")
            return
        
        result = f"📋 待发送日志列表 (共 {len(pending_logs)} 条):\n\n"
        for i, log in enumerate(pending_logs, 1):
            sent_mark = "✅" if log.get('sent') else "⏳"
            result += f"{sent_mark} {i}. 任务ID: {log['cron_id']} - {log['cron_name']}\n"
            result += f"   时间: {log['timestamp']}\n"
            result += f"   状态: {'已发送' if log.get('sent') else '待发送'}\n"
            result += f"   命令: /ql sendlog {log['cron_id']}\n\n"
        
        result += "💡 使用 /ql sendlog <任务ID> 查看具体日志"
        yield event.plain_result(result)
    
    async def _handle_send_log(self, event: AstrMessageEvent, parts: list):
        """发送指定任务的日志到当前聊天"""
        if len(parts) < 3:
            yield event.plain_result("使用方法: /ql sendlog <任务ID>")
            return
        
        try:
            cron_id = int(parts[2])
        except ValueError:
            yield event.plain_result("❌ 任务ID必须是数字")
            return
        
        target_log = self.log_monitor.get_pending_log_by_id(cron_id)
        
        if target_log:
            self.log_monitor.mark_log_as_sent(cron_id)
            yield event.plain_result(target_log['message'])
            return
        
        cron_info = await self.ql_api.get_cron_by_id(cron_id)
        if not cron_info:
            yield event.plain_result(f"❌ 未找到ID为 {cron_id} 的任务")
            return
        
        cron_name = cron_info.get('name', f'任务{cron_id}')
        
        success, log_content = await self.ql_api.get_cron_log(cron_id)
        
        if not success:
            yield event.plain_result(f"❌ 获取任务日志失败: {log_content}")
            return
        
        if not log_content:
            yield event.plain_result(f"📝 任务 {cron_id} 暂无日志")
            return
        
        message = (
            f"🚀 青龙任务执行日志\n"
            f"📝 任务名称: {cron_name}\n"
            f"🔢 任务ID: {cron_id}\n"
            f"⏰ 时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}\n"
            f"📋 执行日志:\n"
            f"{'─' * 20}\n"
        )
        
        if len(log_content) > 1000:
            log_content = "【日志过长，只显示最后1000字符】\n...\n" + log_content[-1000:]
        
        message += log_content
        yield event.plain_result(message)
    
    async def _handle_envs(self, event: AstrMessageEvent, parts: list):
        """查看环境变量列表"""
        search_value = ""
        page = 1
        
        if len(parts) > 2:
            if parts[2].isdigit():
                page = int(parts[2])
            else:
                search_value = parts[2]
                if len(parts) > 3 and parts[3].isdigit():
                    page = int(parts[3])
        
        envs = await self.ql_api.get_envs(search_value)
        
        if not envs:
            msg = f"❌ 未找到包含 '{search_value}' 的环境变量" if search_value else "📭 暂无环境变量"
            yield event.plain_result(msg)
            return
        
        total = len(envs)
        start = (page - 1) * self.PAGE_SIZE
        page_envs = envs[start:start + self.PAGE_SIZE]
        
        if not page_envs:
            yield event.plain_result(f"❌ 页码超出范围 (共 {(total + self.PAGE_SIZE - 1) // self.PAGE_SIZE} 页)")
            return
        
        search_info = f" (搜索: {search_value})" if search_value else ""
        result = f"📋 环境变量列表{search_info} (第 {page} 页，共 {total} 个):\n\n"
        
        for env in page_envs:
            status = "🟢" if env.get('status') == 0 else "🔴"
            value = env.get('value', '')
            result += f"{status} {env.get('name')}\n"
            result += f"  ID: {env.get('id')}\n"
            result += f"  值: {value[:50]}{'...' if len(value) > 50 else ''}\n"
            if env.get('remarks'):
                result += f"  备注: {env.get('remarks')}\n"
            result += "\n"
        
        total_pages = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        if page < total_pages:
            next_cmd = f"/ql envs {search_value} {page + 1}" if search_value else f"/ql envs {page + 1}"
            result += f"💡 使用 {next_cmd} 查看下一页"
        
        yield event.plain_result(result)
    
    async def _handle_add_env(self, event: AstrMessageEvent, parts: list):
        """添加环境变量"""
        if len(parts) < 4:
            yield event.plain_result("使用方法: /ql add <变量名> <变量值> [备注]")
            return
        
        name, value = parts[2], parts[3]
        remarks = " ".join(parts[4:]) if len(parts) > 4 else ""
        
        success, msg = await self.ql_api.add_env(name, value, remarks)
        yield event.plain_result(f"{'✅' if success else '❌'} {msg}: {name}")
    
    async def _handle_update_env(self, event: AstrMessageEvent, parts: list):
        """更新环境变量"""
        if len(parts) < 4:
            yield event.plain_result("使用方法:\n/ql update <变量名> <值>\n/ql update id:<ID> <值>")
            return
        
        name_or_id = parts[2]
        value = " ".join(parts[3:])
        
        if name_or_id.startswith("id:"):
            try:
                env_id = int(name_or_id[3:])
            except ValueError:
                yield event.plain_result(f"❌ 无效的ID格式: {name_or_id}")
                return
            
            all_envs = await self.ql_api.get_envs("")
            target_env = next((e for e in all_envs if e.get('id') == env_id), None)
            
            if not target_env:
                yield event.plain_result(f"❌ 未找到ID为 {env_id} 的环境变量")
                return
            
            success, msg = await self.ql_api.update_env(env_id, target_env.get('name'), value, target_env.get('remarks', ''))
            if success:
                yield event.plain_result(f"✅ 更新成功\nID: {env_id}\n名称: {target_env.get('name')}")
            else:
                yield event.plain_result(f"❌ 更新失败: {msg}")
            return
        
        envs = await self.ql_api.get_envs(name_or_id)
        
        if not envs:
            yield event.plain_result(f"❌ 未找到环境变量: {name_or_id}")
            return
        
        if len(envs) > 1:
            result = f"⚠️ 找到 {len(envs)} 个名为 '{name_or_id}' 的变量:\n\n"
            for env in envs:
                result += f"ID: {env.get('id')} - {env.get('remarks', '无备注')}\n"
            result += f"\n💡 使用 /ql update id:{envs[0].get('id')} <新值> 精确更新"
            yield event.plain_result(result)
            return
        
        env = envs[0]
        success, msg = await self.ql_api.update_env(env['id'], name_or_id, value, env.get('remarks', ''))
        yield event.plain_result(f"{'✅' if success else '❌'} {msg}: {name_or_id}")
    
    async def _handle_delete_env(self, event: AstrMessageEvent, parts: list):
        """删除环境变量"""
        if len(parts) < 3:
            yield event.plain_result("使用方法: /ql delete <变量名>")
            return
        
        name = parts[2]
        envs = await self.ql_api.get_envs(name)
        
        if not envs:
            yield event.plain_result(f"❌ 未找到环境变量: {name}")
            return
        
        success, msg = await self.ql_api.delete_env(envs[0]['id'])
        yield event.plain_result(f"{'✅' if success else '❌'} {msg}: {name}")
    
    async def _handle_enable_env(self, event: AstrMessageEvent, parts: list):
        """启用环境变量"""
        if len(parts) < 3:
            yield event.plain_result("使用方法: /ql enable <变量名>")
            return
        
        name = parts[2]
        envs = await self.ql_api.get_envs(name)
        
        if not envs:
            yield event.plain_result(f"❌ 未找到环境变量: {name}")
            return
        
        success, msg = await self.ql_api.enable_env([env['id'] for env in envs])
        yield event.plain_result(f"{'✅' if success else '❌'} {msg}: {name}")
    
    async def _handle_disable_env(self, event: AstrMessageEvent, parts: list):
        """禁用环境变量"""
        if len(parts) < 3:
            yield event.plain_result("使用方法: /ql disable <变量名>")
            return
        
        name = parts[2]
        envs = await self.ql_api.get_envs(name)
        
        if not envs:
            yield event.plain_result(f"❌ 未找到环境变量: {name}")
            return
        
        success, msg = await self.ql_api.disable_env([env['id'] for env in envs])
        yield event.plain_result(f"{'✅' if success else '❌'} {msg}: {name}")
    
    async def _handle_crons(self, event: AstrMessageEvent, parts: list):
        """查看定时任务列表"""
        page = 1
        if len(parts) > 2 and parts[2].isdigit():
            page = int(parts[2])
        
        crons = await self.ql_api.get_crons()
        
        if not crons:
            yield event.plain_result("📭 暂无定时任务")
            return
        
        total = len(crons)
        start = (page - 1) * self.PAGE_SIZE
        page_crons = crons[start:start + self.PAGE_SIZE]
        
        if not page_crons:
            yield event.plain_result(f"❌ 页码超出范围 (共 {(total + self.PAGE_SIZE - 1) // self.PAGE_SIZE} 页)")
            return
        
        result = f"📋 定时任务列表 (第 {page} 页，共 {total} 个):\n\n"
        for cron in page_crons:
            status = "🟢" if cron.get('status') == 0 else "🔴"
            cmd = cron.get('command', '')
            result += f"{status} {cron.get('name', '未命名')}\n"
            result += f"  ID: {cron.get('id')}\n"
            result += f"  命令: {cmd[:50]}{'...' if len(cmd) > 50 else ''}\n"
            result += f"  定时: {cron.get('schedule', '无')}\n\n"
        
        total_pages = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        if page < total_pages:
            result += f"💡 使用 /ql ls {page + 1} 查看下一页"
        
        yield event.plain_result(result)
    
    async def _handle_run_cron(self, event: AstrMessageEvent, parts: list):
        """执行定时任务（新增日志监控功能）"""
        if len(parts) < 3:
            yield event.plain_result("使用方法: /ql run <任务ID> [silent]")
            return
        
        try:
            cron_id = int(parts[2])
        except ValueError:
            yield event.plain_result("❌ 任务ID必须是数字")
            return
        
        cron_info = await self.ql_api.get_cron_by_id(cron_id)
        if not cron_info:
            yield event.plain_result(f"❌ 未找到ID为 {cron_id} 的任务")
            return
        
        cron_name = cron_info.get('name', f'任务{cron_id}')
        
        silent_mode = len(parts) > 3 and parts[3].lower() == "silent"
        
        success, msg = await self.ql_api.run_cron([cron_id])
        if success:
            if not silent_mode and self.config.get("log_push_enabled", True):
                await self.log_monitor.start_monitor(cron_id, cron_name)
                
                groups = self.config.get("log_push_groups", [])
                friends = self.config.get("log_push_friends", [])
                
                if groups or friends:
                    result_msg = f"✅ 已启动任务: {cron_name} (ID: {cron_id})\n🔔 执行完成后将自动保存日志"
                    if groups:
                        result_msg += f"\n📢 推送群: {len(groups)} 个"
                    if friends:
                        result_msg += f"\n👤 推送好友: {len(friends)} 个"
                    result_msg += f"\n💡 使用 /ql pending 查看待发送日志"
                else:
                    result_msg = f"✅ 已启动任务: {cron_name} (ID: {cron_id})\n🔔 执行完成后将保存日志，使用 /ql pending 查看待发送日志"
            elif silent_mode:
                result_msg = f"✅ 已启动任务: {cron_name} (ID: {cron_id}) - 静默模式"
            else:
                result_msg = f"✅ 已启动任务: {cron_name} (ID: {cron_id})\n💡 日志功能已禁用，使用 /ql push enable 启用"
        else:
            result_msg = f"❌ 执行失败: {msg}"
        
        yield event.plain_result(result_msg)
    
    async def _handle_stop_cron(self, event: AstrMessageEvent, parts: list):
        """停止定时任务"""
        if len(parts) < 3:
            yield event.plain_result("使用方法: /ql stop <任务ID>")
            return
        
        try:
            cron_id = int(parts[2])
        except ValueError:
            yield event.plain_result("❌ 任务ID必须是数字")
            return
        
        success, msg = await self.ql_api.stop_cron([cron_id])
        yield event.plain_result(f"{'✅ 已停止任务' if success else '❌ 停止失败'}: {cron_id}")
    
    async def _handle_cron_log(self, event: AstrMessageEvent, parts: list):
        """查看任务日志"""
        if len(parts) < 3:
            yield event.plain_result("使用方法: /ql log <任务ID>")
            return
        
        try:
            cron_id = int(parts[2])
        except ValueError:
            yield event.plain_result("❌ 任务ID必须是数字")
            return
        
        success, log_content = await self.ql_api.get_cron_log(cron_id)
        
        if not success:
            yield event.plain_result(f"❌ 获取日志失败: {log_content}")
            return
        
        if not log_content:
            yield event.plain_result(f"📝 任务 {cron_id} 暂无日志")
            return
        
        if len(log_content) > 1000:
            log_content = "...\n" + log_content[-1000:]
        
        yield event.plain_result(f"📝 任务 {cron_id} 日志:\n\n{log_content}")
    
    async def _handle_cron_action(self, event: AstrMessageEvent, parts: list):
        """定时任务操作（启用/禁用/置顶/删除）"""
        if len(parts) < 4:
            yield event.plain_result("使用方法:\n/ql cron enable/disable <任务ID>\n/ql cron pin/unpin <任务ID>\n/ql cron delete <任务ID>")
            return
        
        action = parts[2].lower()
        try:
            cron_id = int(parts[3])
        except ValueError:
            yield event.plain_result("❌ 任务ID必须是数字")
            return
        
        actions = {
            "enable": (self.ql_api.enable_cron, "启用"),
            "disable": (self.ql_api.disable_cron, "禁用"),
            "pin": (self.ql_api.pin_cron, "置顶"),
            "unpin": (self.ql_api.unpin_cron, "取消置顶"),
            "delete": (self.ql_api.delete_cron, "删除"),
        }
        
        if action not in actions:
            yield event.plain_result(f"❌ 未知操作: {action}\n支持: enable, disable, pin, unpin, delete")
            return
        
        func, action_name = actions[action]
        success, msg = await func([cron_id])
        icon = "📌" if action in ("pin", "unpin") else ("✅" if success else "❌")
        yield event.plain_result(f"{icon} {action_name}任务 {cron_id}: {msg}")
    
    async def _handle_info(self, event: AstrMessageEvent, parts: list):
        """查看系统信息"""
        system_info = await self.ql_api.get_system_info()
        
        if not system_info:
            yield event.plain_result("❌ 获取系统信息失败")
            return
        
        result = "📊 青龙面板系统信息:\n\n"
        
        if 'version' in system_info:
            result += f"🖥️ 版本: {system_info['version']}"
            if 'branch' in system_info:
                result += f" ({system_info['branch']})"
            result += "\n"
        
        if 'isInitialized' in system_info:
            status = "✅ 已初始化" if system_info['isInitialized'] else "⚠️ 未初始化"
            result += f"📌 状态: {status}\n"
        
        yield event.plain_result(result)
    
    async def _handle_push_config(self, event: AstrMessageEvent, parts: list):
        """处理实时推送配置命令"""
        if len(parts) < 3:
            yield event.plain_result("使用方法:\n"
                                   "/ql push status - 查看状态\n"
                                   "/ql push enable/disable - 启用/禁用\n"
                                   "/ql push add group <目标> - 添加推送群（支持多种格式）\n"
                                   "/ql push remove group <目标> - 移除推送群\n"
                                   "/ql push add friend <目标> - 添加推送好友（支持多种格式）\n"
                                   "/ql push remove friend <目标> - 移除推送好友")
            return
        
        action = parts[2].lower()
        
        if action == "status":
            enabled = self.config.get("log_push_enabled", True)
            groups = self.config.get("log_push_groups", [])
            friends = self.config.get("log_push_friends", [])
            
            status_msg = f"🔔 实时日志推送状态\n"
            status_msg += f"状态: {'✅ 启用' if enabled else '❌ 禁用'}\n"
            status_msg += f"推送群配置 ({len(groups)} 个):\n"
            for group in groups:
                status_msg += f"  • {group}\n"
            if not groups:
                status_msg += "  无\n"
            
            status_msg += f"推送好友配置 ({len(friends)} 个):\n"
            for friend in friends:
                status_msg += f"  • {friend}\n"
            if not friends:
                status_msg += "  无\n"
            
            status_msg += f"超时设置: {self.config.get('log_push_timeout', 60)} 秒\n"
            
            if enabled and (groups or friends):
                status_msg += f"\n📢 推送说明:\n"
                status_msg += f"• 任务执行完成后，日志会自动保存到队列\n"
                status_msg += f"• 使用 /ql pending 查看所有待发送日志\n"
                status_msg += f"• 使用 /ql sendlog <任务ID> 查看具体日志\n"
            else:
                status_msg += f"\n💡 提示: 使用 /ql push enable 启用推送功能\n"
                status_msg += f"      使用 /ql push add group <目标> 添加推送群\n"
                status_msg += f"      使用 /ql push add friend <目标> 添加推送好友"
            
            yield event.plain_result(status_msg)
        
        elif action == "enable":
            self.config["log_push_enabled"] = True
            self._start_log_check_task()
            yield event.plain_result("✅ 已启用实时日志推送功能")
        
        elif action == "disable":
            self.config["log_push_enabled"] = False
            if self.log_check_task and not self.log_check_task.done():
                self.log_check_task.cancel()
                self.log_check_task = None
            yield event.plain_result("✅ 已禁用实时日志推送功能")
        
        elif action in ["add", "remove"] and len(parts) >= 5:
            target_type = parts[3].lower()
            target_str = " ".join(parts[4:])
            
            if not target_str or not target_str.strip():
                yield event.plain_result("❌ 目标不能为空")
                return
            
            config_key = f"log_push_{'groups' if target_type == 'group' else 'friends'}"
            target_list = self.config.get(config_key, [])
            
            if action == "add":
                # 格式化目标
                if target_type == "group":
                    formatted_target = self.schedule_manager._format_target(target_str, "GroupMessage")
                else:
                    formatted_target = self.schedule_manager._format_target(target_str, "FriendMessage")
                
                if not formatted_target:
                    yield event.plain_result(f"❌ 目标格式无效: {target_str}")
                    return
                
                if formatted_target not in target_list:
                    target_list.append(formatted_target)
                    self.config[config_key] = target_list
                    yield event.plain_result(f"✅ 已添加{ '群' if target_type == 'group' else '好友'}到实时推送配置:\n{formatted_target}")
                else:
                    yield event.plain_result(f"⚠️ { '群' if target_type == 'group' else '好友'}已在实时推送配置中:\n{formatted_target}")
            else:
                # 移除时尝试多种格式
                found = False
                for target in target_list[:]:
                    # 检查是否匹配原始格式或格式化后的格式
                    if target_str == target or target_str in target:
                        target_list.remove(target)
                        found = True
                        self.config[config_key] = target_list
                        yield event.plain_result(f"✅ 已从实时推送配置中移除{ '群' if target_type == 'group' else '好友'}:\n{target}")
                        break
                
                if not found:
                    yield event.plain_result(f"⚠️ { '群' if target_type == 'group' else '好友'}不在实时推送配置中:\n{target_str}")
        
        else:
            yield event.plain_result("❌ 无效的命令格式")
    
    async def _handle_schedule(self, event: AstrMessageEvent, parts: list):
        """处理定时推送相关命令"""
        if len(parts) < 3:
            yield event.plain_result("使用方法:\n"
                                   "/ql schedule status - 查看定时推送状态\n"
                                   "/ql schedule enable/disable - 启用/禁用定时推送\n"
                                   "/ql schedule logs [数量] - 查看详细任务日志\n"
                                   "/ql schedule push - 手动执行定时推送\n"
                                   "/ql schedule count <数量> - 设置定时推送显示的任务数量（1-50）\n"
                                   "/ql schedule errors <行数> - 设置错误日志显示行数(0=完整日志，最大500)\n"
                                   "/ql schedule add group <目标> - 添加定时推送群（支持多种格式）\n"
                                   "/ql schedule remove group <目标> - 移除定时推送群\n"
                                   "/ql schedule add friend <目标> - 添加定时推送好友（支持多种格式）\n"
                                   "/ql schedule remove friend <目标> - 移除定时推送好友\n"
                                   "/ql schedule time <时间> - 设置推送时间，如 08:00,18:00")
            return
        
        subcommand = parts[2].lower()
        
        if subcommand == "status":
            status_text = await self.schedule_manager.get_schedule_status()
            yield event.plain_result(status_text)
        
        elif subcommand == "enable":
            self.config["log_schedule_enabled"] = True
            await self.schedule_manager.start_schedule()
            yield event.plain_result("✅ 已启用定时日志推送")
        
        elif subcommand == "disable":
            self.config["log_schedule_enabled"] = False
            await self.schedule_manager.stop_schedule()
            yield event.plain_result("✅ 已禁用定时日志推送")
        
        elif subcommand == "logs":
            limit = self.config.get("log_schedule_display_count", 10)
            if len(parts) > 3 and parts[3].isdigit():
                limit = min(int(parts[3]), 20)
            logs_text = await self.schedule_manager.get_detailed_logs(limit)
            yield event.plain_result(logs_text)
        
        elif subcommand == "push":
            yield event.plain_result("⏳ 开始手动推送定时日志...")
            await self.schedule_manager.send_manual_push()
            yield event.plain_result("✅ 手动推送完成")
        
        elif subcommand == "count" and len(parts) >= 4:
            try:
                count = int(parts[3])
                result = await self.schedule_manager.update_display_count(count)
                yield event.plain_result(result)
            except ValueError:
                yield event.plain_result("❌ 数量必须是数字")
        
        elif subcommand == "errors" and len(parts) >= 4:
            try:
                lines = int(parts[3])
                result = await self.schedule_manager.update_error_lines(lines)
                yield event.plain_result(result)
            except ValueError:
                yield event.plain_result("❌ 行数必须是数字")
        
        elif subcommand in ["add", "remove"] and len(parts) >= 5:
            target_type = parts[3].lower()
            target_str = " ".join(parts[4:])
            
            if not target_str or not target_str.strip():
                yield event.plain_result("❌ 目标不能为空")
                return
            
            config_key = f"log_schedule_{'groups' if target_type == 'group' else 'friends'}"
            target_list = self.config.get(config_key, [])
            
            if subcommand == "add":
                # 格式化目标
                if target_type == "group":
                    formatted_target = self.schedule_manager._format_target(target_str, "GroupMessage")
                else:
                    formatted_target = self.schedule_manager._format_target(target_str, "FriendMessage")
                
                if not formatted_target:
                    yield event.plain_result(f"❌ 目标格式无效: {target_str}")
                    return
                
                if formatted_target not in target_list:
                    target_list.append(formatted_target)
                    self.config[config_key] = target_list
                    yield event.plain_result(f"✅ 已添加{ '群' if target_type == 'group' else '好友'}到定时推送配置:\n{formatted_target}")
                else:
                    yield event.plain_result(f"⚠️ { '群' if target_type == 'group' else '好友'}已在定时推送配置中:\n{formatted_target}")
            else:
                # 移除时尝试多种格式
                found = False
                for target in target_list[:]:
                    if target_str == target or target_str in target:
                        target_list.remove(target)
                        found = True
                        self.config[config_key] = target_list
                        yield event.plain_result(f"✅ 已从定时推送配置中移除{ '群' if target_type == 'group' else '好友'}:\n{target}")
                        break
                
                if not found:
                    yield event.plain_result(f"⚠️ { '群' if target_type == 'group' else '好友'}不在定时推送配置中:\n{target_str}")
        
        elif subcommand == "time" and len(parts) >= 4:
            time_str = " ".join(parts[3:])
            time_parts = time_str.split(",")
            valid = True
            for t in time_parts:
                try:
                    hour, minute = map(int, t.strip().split(":"))
                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                        valid = False
                        break
                except:
                    valid = False
                    break
            
            if valid:
                self.config["log_schedule_time"] = time_str
                await self.schedule_manager.stop_schedule()
                if self.config.get("log_schedule_enabled", True):
                    await self.schedule_manager.start_schedule()
                yield event.plain_result(f"✅ 已设置定时推送时间为: {time_str}")
            else:
                yield event.plain_result("❌ 时间格式错误，请使用 HH:MM 格式，多个时间用逗号分隔")
        
        else:
            yield event.plain_result("❌ 无效的命令格式")
    
    async def terminate(self):
        """插件卸载时调用"""
        await self.schedule_manager.stop_schedule()
        
        if self.log_check_task and not self.log_check_task.done():
            self.log_check_task.cancel()
        
        browser_login = getattr(self, "browser_login", None)
        if browser_login is not None:
            await browser_login.close_all()
        
        await self.jd_sms.close()
        await self.ql_api.close()
        logger.info("青龙面板插件已卸载")