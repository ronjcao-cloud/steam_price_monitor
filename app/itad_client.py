"""ITAD (IsThereAnyDeal) 历史低价查询。"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

ITAD_API = "https://api.isthereanydeal.com"


@dataclass
class HistoryLow:
    game_id: str
    price: float
    regular: float
    cut: int
    shop: str
    timestamp: str


class ITADClient:
    def __init__(self, api_key: str, timeout: float = 20.0):
        self._key = api_key
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "steam-price-monitor/1.0"},
            verify=False,
        )
        import warnings
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    def close(self) -> None:
        self._client.close()

    def lookup_appid(self, appid: int) -> str | None:
        try:
            r = self._client.get(
                f"{ITAD_API}/games/lookup/v1",
                params={"key": self._key, "appid": appid},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("found") and data.get("game"):
                gid = data["game"].get("id")
                log.debug("appid %s -> ITAD %s", appid, gid)
                return gid
            log.info("ITAD 未找到 appid=%s", appid)
        except Exception as e:
            log.warning("ITAD lookup 失败 appid=%s: %s", appid, e)
        return None

    def get_history_low(
        self, game_ids: list[str], country: str = "CN"
    ) -> dict[str, HistoryLow]:
        if not game_ids:
            return {}
        result: dict[str, HistoryLow] = {}
        for i in range(0, len(game_ids), 200):
            batch = game_ids[i:i + 200]
            try:
                r = self._client.post(
                    f"{ITAD_API}/games/historylow/v1",
                    params={"key": self._key, "country": country},
                    json=batch,
                )
                r.raise_for_status()
                for item in r.json():
                    low = item.get("low")
                    if not low:
                        continue
                    price_info = low.get("price") or {}
                    regular_info = low.get("regular") or {}
                    result[item["id"]] = HistoryLow(
                        game_id=item["id"],
                        price=float(price_info.get("amount", 0)),
                        regular=float(regular_info.get("amount", 0)),
                        cut=int(low.get("cut", 0)),
                        shop=(low.get("shop") or {}).get("name", ""),
                        timestamp=low.get("timestamp", ""),
                    )
            except Exception as e:
                log.warning("ITAD historylow 失败: %s", e)
        return result
