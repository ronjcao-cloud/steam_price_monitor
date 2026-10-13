"""Steam 国区价格查询。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

STORE_API = "https://store.steampowered.com/api/appdetails"


@dataclass
class PriceInfo:
    appid: int
    name: str
    is_free: bool
    current: float      # 当前售价（人民币元）
    original: float     # 原价（人民币元）
    discount: int       # 折扣百分比
    currency: str = "CNY"


class SteamClient:
    def __init__(self, timeout: float = 20.0):
        self._client = httpx.Client(timeout=timeout, headers={
            "User-Agent": "steam-price-monitor/1.0 (+https://github.com/)",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }, verify=False)
        import warnings
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    def close(self) -> None:
        self._client.close()

    def get_cn_price(self, appid: int, retries: int = 2) -> PriceInfo | None:
        """查国区价格。失败返回 None（网络错、无价格、游戏不存在等）。"""
        data = None
        for attempt in range(retries + 1):
            try:
                resp = self._client.get(
                    STORE_API,
                    params={"appids": appid, "cc": "cn", "l": "schinese"},
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                log.warning("请求 appdetails 失败 appid=%s 第%d次: %s", appid, attempt + 1, e)
                if attempt < retries:
                    time.sleep(3 * (attempt + 1))
        if data is None:
            return None

        node = data.get(str(appid)) or {}
        if not node.get("success"):
            log.warning("Steam 返回失败 appid=%s（可能国区未上架）", appid)
            return None

        game = node.get("data") or {}
        name = game.get("name", f"AppID {appid}")

        if game.get("is_free"):
            return PriceInfo(appid, name, True, 0.0, 0.0, 100, "FREE")

        ov = game.get("price_overview")
        if not ov:
            # 未发售 / 无定价
            log.info("无价格信息 appid=%s (%s)，可能未发售", appid, name)
            return None

        return PriceInfo(
            appid=appid,
            name=name,
            is_free=False,
            current=ov["final"] / 100,
            original=ov["initial"] / 100,
            discount=int(ov.get("discount_percent", 0)),
            currency=ov.get("currency", "CNY"),
        )
