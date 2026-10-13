"""推送通道：飞书自定义机器人 / 钉钉自定义机器人。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Protocol

import httpx

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def send_text(self, text: str) -> bool: ...
    def close(self) -> None: ...


class FeishuNotifier:
    def __init__(self, webhook_url: str, secret: str = ""):
        self._url = webhook_url
        self._secret = secret
        self._client = httpx.Client(timeout=15)

    def close(self) -> None:
        self._client.close()

    def _sign(self, timestamp: str) -> str:
        string_to_sign = f"{timestamp}\n{self._secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def send_text(self, text: str) -> bool:
        body: dict = {"msg_type": "text", "content": {"text": text}}
        if self._secret:
            ts = str(int(time.time()))
            body["timestamp"] = ts
            body["sign"] = self._sign(ts)
        try:
            resp = self._client.post(self._url, json=body)
            resp.raise_for_status()
            payload = resp.json()
            # 飞书成功返回 {"code":0,...} 或 {"StatusCode":0,...}
            code = payload.get("code", payload.get("StatusCode", 0))
            if code not in (0, "0"):
                log.error("飞书返回错误: %s", payload)
                return False
            return True
        except Exception as e:
            log.error("飞书推送失败: %s", e)
            return False


class DingTalkNotifier:
    """钉钉自定义机器人 webhook。

    三种填法任选其一：
    - dingtalk.webhook_url 直接给完整 webhook（含 access_token=...）
    - dingtalk.access_token 只给 token，程序拼官方 send 地址
    安全设置：
    - 选“加签”时填 secret（时间戳用毫秒，且 secret 作 HMAC key）
    - 选“自定义关键词”时填 keyword，会自动加到消息开头，否则钉钉会拒收
      （errcode 310000: keywords not in content）
    """

    SEND_URL = "https://oapi.dingtalk.com/robot/send"

    def __init__(
        self,
        access_token: str = "",
        secret: str = "",
        keyword: str = "",
        webhook_url: str = "",
    ):
        self._secret = secret
        self._keyword = keyword
        self._client = httpx.Client(timeout=15)
        if webhook_url:
            self._url = webhook_url
            self._token = ""
        else:
            self._url = self.SEND_URL
            self._token = access_token

    def close(self) -> None:
        self._client.close()

    def _sign(self, timestamp_ms: str) -> str:
        string_to_sign = f"{timestamp_ms}\n{self._secret}"
        digest = hmac.new(
            self._secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))

    def send_text(self, text: str) -> bool:
        if self._keyword and self._keyword not in text:
            text = f"{self._keyword}\n{text}"
        body: dict = {"msgtype": "text", "text": {"content": text}}
        params: dict[str, str] = {}
        if self._token:
            params["access_token"] = self._token
        if self._secret:
            ts = str(round(time.time() * 1000))
            params["timestamp"] = ts
            params["sign"] = self._sign(ts)
        try:
            resp = self._client.post(self._url, params=params or None, json=body)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errcode") not in (0, "0"):
                log.error("钉钉返回错误: %s", payload)
                return False
            return True
        except Exception as e:
            log.error("钉钉推送失败: %s", e)
            return False


class MultiNotifier:
    """把同一条消息推送到多个通道；单个通道失败不影响其他通道。"""

    def __init__(self, notifiers: list):
        self._notifiers = list(notifiers)

    def send_text(self, text: str) -> bool:
        ok = False
        for n in self._notifiers:
            if n.send_text(text):
                ok = True
        return ok

    def close(self) -> None:
        for n in self._notifiers:
            try:
                n.close()
            except Exception:
                pass


def build_notifier(cfg) -> Notifier:
    """按配置组装推送通道；参数用鸭子类型避免与 config 循环导入。"""
    channels: list = []
    if getattr(cfg, "feishu_webhook", ""):
        channels.append(FeishuNotifier(cfg.feishu_webhook, cfg.feishu_secret))
    if getattr(cfg, "dingtalk_token", "") or getattr(cfg, "dingtalk_webhook", ""):
        channels.append(DingTalkNotifier(
            access_token=cfg.dingtalk_token,
            secret=cfg.dingtalk_secret,
            keyword=cfg.dingtalk_keyword,
            webhook_url=cfg.dingtalk_webhook,
        ))
    if not channels:
        raise ValueError("没有启用任何推送通道（飞书或钉钉至少配一个）")
    if len(channels) == 1:
        return channels[0]
    return MultiNotifier(channels)
