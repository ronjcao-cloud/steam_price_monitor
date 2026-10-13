"""配置加载与校验。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Game:
    appid: int
    name: str = ""
    target_price: float | None = None


@dataclass
class Config:
    feishu_webhook: str = ""
    feishu_secret: str = ""
    dingtalk_token: str = ""
    dingtalk_secret: str = ""
    dingtalk_keyword: str = ""
    dingtalk_webhook: str = ""
    interval_minutes: int = 360
    notify_on_rise: bool = False
    games: list[Game] = field(default_factory=list)
    steam_api_key: str = ""
    steam_id: str = ""
    sync_library_hours: int = 24
    itad_api_key: str = ""

    @staticmethod
    def load(path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        feishu = raw.get("feishu") or {}
        webhook = feishu.get("webhook_url", "") or os.environ.get("FEISHU_WEBHOOK_URL", "")

        dingtalk = raw.get("dingtalk") or {}
        dt_webhook = dingtalk.get("webhook_url", "") or os.environ.get("DINGTALK_WEBHOOK_URL", "")
        dt_token = dingtalk.get("access_token", "") or os.environ.get("DINGTALK_TOKEN", "")
        dt_secret = dingtalk.get("secret", "") or os.environ.get("DINGTALK_SECRET", "")
        dt_keyword = dingtalk.get("keyword", "") or os.environ.get("DINGTALK_KEYWORD", "")

        if not webhook and not dt_token and not dt_webhook:
            raise ValueError(
                "至少配置一个推送通道：feishu.webhook_url（或 FEISHU_WEBHOOK_URL），"
                "或 dingtalk.access_token / dingtalk.webhook_url"
            )

        monitor = raw.get("monitor") or {}
        steam = raw.get("steam") or {}
        itad = raw.get("itad") or {}
        games_raw = raw.get("games") or []

        games: list[Game] = []
        for g in games_raw:
            appid = g.get("appid")
            if not appid:
                continue
            games.append(Game(
                appid=int(appid),
                name=str(g.get("name", "")),
                target_price=(float(g["target_price"]) if g.get("target_price") is not None else None),
            ))

        steam_api_key = steam.get("api_key", "") or os.environ.get("STEAM_API_KEY", "")
        steam_id = steam.get("id", "") or os.environ.get("STEAM_ID", "")
        if not games and not steam_api_key:
            raise ValueError("要么配置 games 列表，要么配置 steam.api_key 自动同步愿望清单")

        return Config(
            feishu_webhook=webhook,
            feishu_secret=feishu.get("secret", "") or os.environ.get("FEISHU_SECRET", ""),
            dingtalk_token=dt_token,
            dingtalk_secret=dt_secret,
            dingtalk_keyword=dt_keyword,
            dingtalk_webhook=dt_webhook,
            interval_minutes=int(monitor.get("interval_minutes", 360)),
            notify_on_rise=bool(monitor.get("notify_on_rise", False)),
            games=games,
            steam_api_key=steam_api_key,
            steam_id=steam_id,
            sync_library_hours=int(steam.get("sync_hours", 24)),
            itad_api_key=itad.get("api_key", "") or os.environ.get("ITAD_API_KEY", ""),
        )
