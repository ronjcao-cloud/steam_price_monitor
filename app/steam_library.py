"""Steam 游戏库与愿望清单同步。"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

STEAM_API = "https://api.steampowered.com"
STORE_API = "https://store.steampowered.com"


@dataclass
class SteamLibrary:
    owned_appids: set[int]
    wishlist: dict[int, str]  # appid -> name

    @property
    def watch_appids(self) -> set[int]:
        """愿望清单里且还没买的。"""
        return set(self.wishlist.keys()) - self.owned_appids


class SteamLibraryClient:
    def __init__(self, api_key: str, vanity_or_id: str, timeout: float = 20.0):
        self._key = api_key
        self._id = vanity_or_id  # vanity 名或 17 位 steamid64
        self._steamid: str | None = None
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "steam-price-monitor/1.0"},
            # Windows 本地 CA 证书常缺失；NAS/Linux 容器里证书正常。
            # 这里是公开爬商店页面，不携带敏感凭证，统一放行。
            verify=False,
        )
        import warnings
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str, *, attempts: int = 3, **kwargs) -> httpx.Response:
        """带重试的 GET。

        国内访问 api.steampowered.com 偶发 TLS 握手超时
        （_ssl.c: The handshake operation timed out），单次失败就放弃会白白
        丢掉一整个 sync_library_hours 周期，所以这里退避重试。
        """
        last: Exception | None = None
        for i in range(attempts):
            try:
                return self._client.get(url, **kwargs)
            except Exception as e:  # noqa: BLE001 - 网络异常种类多，统一重试
                last = e
                if i + 1 < attempts:
                    delay = 3 * (i + 1)
                    log.debug("请求 %s 失败（第 %d/%d 次）: %s，%ds 后重试",
                              url, i + 1, attempts, e, delay)
                    time.sleep(delay)
        assert last is not None
        raise last

    def _ensure_steamid(self) -> str:
        if self._steamid:
            return self._steamid
        # 已经是 17 位数字就直接用
        if self._id.isdigit() and len(self._id) == 17:
            self._steamid = self._id
            return self._steamid
        # 否则按 vanity 解析
        r = self._get(
            f"{STEAM_API}/ISteamUser/ResolveVanityURL/v1/",
            params={"key": self._key, "vanityurl": self._id},
        )
        r.raise_for_status()
        data = r.json().get("response", {})
        if data.get("success") != 1:
            raise RuntimeError(f"无法解析 Steam 个人资料名 '{self._id}': {data}")
        self._steamid = data["steamid"]
        log.info("SteamID64 解析为 %s", self._steamid)
        return self._steamid

    def get_owned_appids(self) -> set[int]:
        try:
            sid = self._ensure_steamid()
            r = self._get(
                f"{STEAM_API}/IPlayerService/GetOwnedGames/v1/",
                params={
                    "key": self._key,
                    "steamid": sid,
                    "include_appinfo": "false",
                    "include_played_free_games": "true",
                },
            )
            r.raise_for_status()
            games = r.json().get("response", {}).get("games", [])
            appids = {int(g["appid"]) for g in games}
            log.info("拉取到 %d 个已拥有游戏", len(appids))
            return appids
        except Exception as e:
            # 拿不到已拥有列表不该拖垮整个同步：愿望清单只用 vanity 名爬页面，
            # 根本不依赖 steamid，所以这里退化成空集合继续走。
            log.warning("拉取已拥有游戏失败（不影响愿望清单同步）: %s", e)
            return set()

    def get_wishlist(self) -> dict[int, str]:
        """爬愿望清单 HTML 页面（老 wishlistdata JSON 接口已被 302）。

        页面结构：每个游戏块里有 header.jpg，后面紧跟游戏名和 "Release Date:"。
        """
        # 用 vanity 路径（数字 ID 走 /profiles/）
        paths = []
        if self._id.isdigit() and len(self._id) == 17:
            paths.append(f"{STORE_API}/wishlist/profiles/{self._id}/?p=0&num_per_page=100")
        else:
            paths.append(f"{STORE_API}/wishlist/id/{self._id}/?p=0&num_per_page=100")

        for path in paths:
            try:
                r = self._get(path, follow_redirects=True)
                if r.status_code != 200 or "wishlist" not in r.url.path.lower():
                    log.debug("愿望清单 %s 返回 %s，跳到 %s", path, r.status_code, r.url)
                    continue
                html = r.text
                # 模式：<a href=".../app/1234/Slug?..." class="...">游戏名</a>
                pattern = re.compile(
                    r'/app/(\d+)/[^"?>]+[^>]*>([^<]+)</a>',
                    re.S,
                )
                seen: dict[int, str] = {}
                for m in pattern.finditer(html):
                    try:
                        aid = int(m.group(1))
                    except ValueError:
                        continue
                    if aid in seen:
                        continue
                    name = (m.group(2).strip()
                              .replace("&#x27;", "'")
                              .replace("&amp;", "&")
                              .replace("&quot;", '"')
                              .replace("&nbsp;", " "))
                    seen[aid] = name
                if seen:
                    log.info("爬取愿望清单 %d 个游戏", len(seen))
                    return seen
            except Exception as e:
                log.debug("愿望清单 %s 失败: %s", path, e)
                continue
        log.warning("愿望清单爬取失败——请确认 Steam 隐私设置里'游戏详情'为公开")
        return {}

    def sync(self) -> SteamLibrary:
        owned = self.get_owned_appids()
        wishlist = self.get_wishlist()
        return SteamLibrary(owned_appids=owned, wishlist=wishlist)
