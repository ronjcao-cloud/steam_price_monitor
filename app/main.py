"""Steam 价格监控主程序。"""
from __future__ import annotations

import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Config, Game
from .itad_client import ITADClient
from .notifier import Notifier, build_notifier
from .steam_client import PriceInfo, SteamClient
from .steam_library import SteamLibrary, SteamLibraryClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("monitor")

STATE_PATH = Path("/data/state.json") if Path("/data").exists() else Path("data/state.json")


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("状态文件损坏，重置: %s", e)
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_message(
    game: Game,
    pi: PriceInfo,
    prev: float | None,
    hit_target: bool,
    history_low: float | None = None,
) -> str:
    lines = []
    if pi.is_free:
        lines.append(f"🎉 游戏《{pi.name}》已转为免费！")
    elif hit_target:
        lines.append(f"🎯 游戏《{pi.name}》跌到目标价了！")
    elif prev is not None and pi.current < prev:
        drop = prev - pi.current
        lines.append(f"⬇️ 游戏《{pi.name}》降价 ¥{drop:.2f}")
    else:
        lines.append(f"ℹ️ 游戏《{pi.name}》价格变动")

    lines.append(f"当前价格：¥{pi.current:.2f}")
    if not pi.is_free:
        lines.append(f"原价：¥{pi.original:.2f}")
        if pi.discount:
            lines.append(f"折扣：-{pi.discount}%")
    if history_low is not None:
        lines.append(f"国区史低：¥{history_low:.2f}")
    if prev is not None:
        lines.append(f"上次记录：¥{prev:.2f}")
    if game.target_price is not None:
        lines.append(f"目标价：¥{game.target_price:.2f}")
    lines.append(f"商店：https://store.steampowered.com/app/{pi.appid}")
    return "\n".join(lines)


def build_watch_list(cfg: Config, library: SteamLibrary | None) -> dict[int, Game]:
    watch: dict[int, Game] = {}
    for g in cfg.games:
        watch[g.appid] = g
    if library:
        for appid, name in library.wishlist.items():
            if appid in library.owned_appids or appid in watch:
                continue
            watch[appid] = Game(appid=appid, name=name)
    return watch


def resolve_itad_ids(
    itad: ITADClient | None, watch: dict[int, Game], state: dict
) -> dict[int, str]:
    if not itad:
        return {}
    mapping: dict[int, str] = {}
    need_lookup: list[int] = []
    for appid in watch:
        cached = state.get(str(appid), {}).get("itad_id")
        if cached:
            mapping[appid] = cached
        else:
            need_lookup.append(appid)
    for appid in need_lookup:
        gid = itad.lookup_appid(appid)
        if gid:
            mapping[appid] = gid
            state.setdefault(str(appid), {})["itad_id"] = gid
        time.sleep(0.5)
    if need_lookup:
        save_state(state)
    return mapping


def check_once(
    cfg: Config,
    steam: SteamClient,
    notifier: Notifier,
    state: dict,
    watch: dict[int, Game],
    itad: ITADClient | None = None,
) -> None:
    log.info("===== 开始一轮检查，共 %d 个游戏 =====", len(watch))

    itad_map = resolve_itad_ids(itad, watch, state)
    history_lows: dict[str, float] = {}
    if itad and itad_map:
        lows = itad.get_history_low(list(itad_map.values()), country="CN")
        for gid, hl in lows.items():
            history_lows[gid] = hl.price
        log.info("ITAD 史低获取 %d/%d 个游戏", len(history_lows), len(itad_map))

    for appid, game in watch.items():
        pi = steam.get_cn_price(appid)
        if pi is None:
            continue
        if not game.name:
            game.name = pi.name

        key = str(appid)
        prev = state.get(key, {}).get("last_price")

        should_notify = False
        hit_target = False

        if prev is None:
            log.info("首次记录《%s》基线价 ¥%.2f", pi.name, pi.current)
        else:
            prev_free = bool(state.get(key, {}).get("is_free"))
            if pi.is_free and not prev_free:
                # 只在「刚变成免费」那一次通知。一直免费的游戏如果每轮都推，
                # 就变成 6 小时一次的骚扰了。
                should_notify = True
            elif game.target_price is not None and pi.current <= game.target_price and prev > game.target_price:
                should_notify = True
                hit_target = True
            elif pi.current < prev:
                should_notify = True
            elif pi.current > prev and cfg.notify_on_rise:
                should_notify = True

        hl = history_lows.get(itad_map.get(appid, "")) if itad_map.get(appid) else None

        if should_notify:
            msg = build_message(game, pi, prev, hit_target, history_low=hl)
            ok = notifier.send_text(msg)
            log.info("通知《%s》-> %s", pi.name, "成功" if ok else "失败")

        state[key] = {
            "name": pi.name,
            "last_price": pi.current,
            "original_price": pi.original,
            "discount": pi.discount,
            "is_free": pi.is_free,
            "itad_id": itad_map.get(appid, state.get(key, {}).get("itad_id", "")),
            "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_state(state)
        time.sleep(2)

    log.info("===== 本轮检查完成 =====")


def main() -> int:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config/config.yaml"
    cfg = Config.load(config_path)
    log.info("配置加载完成：手动 %d 个游戏，间隔 %d 分钟，ITAD=%s",
             len(cfg.games), cfg.interval_minutes, bool(cfg.itad_api_key))

    steam = SteamClient()
    notifier = build_notifier(cfg)
    itad = ITADClient(cfg.itad_api_key) if cfg.itad_api_key else None
    state = load_state()

    library_client: SteamLibraryClient | None = None
    library: SteamLibrary | None = None
    last_sync_ts = 0.0
    if cfg.steam_api_key and cfg.steam_id:
        try:
            library_client = SteamLibraryClient(cfg.steam_api_key, cfg.steam_id)
            library = library_client.sync()
            last_sync_ts = time.time()
            log.info("已同步：拥有 %d 个游戏，愿望清单 %d 个，待监控 %d 个",
                     len(library.owned_appids), len(library.wishlist),
                     len(set(library.wishlist) - library.owned_appids))
        except Exception as e:
            log.warning("首次同步库/愿望清单失败，仅用手动配置: %s", e)
            library_client = None

    watch = build_watch_list(cfg, library)

    stop = False
    def _sig(_signum, _frame):
        nonlocal stop
        stop = True
        log.info("收到退出信号")
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        while not stop:
            if library_client and (time.time() - last_sync_ts) > cfg.sync_library_hours * 3600:
                try:
                    library = library_client.sync()
                    watch = build_watch_list(cfg, library)
                    last_sync_ts = time.time()
                    log.info("重新同步完成：待监控 %d 个游戏", len(watch))
                except Exception as e:
                    log.warning("同步库/愿望清单失败（沿用旧列表）: %s", e)

            try:
                check_once(cfg, steam, notifier, state, watch, itad=itad)
            except Exception as e:
                log.exception("本轮检查异常: %s", e)

            for _ in range(cfg.interval_minutes * 60):
                if stop:
                    break
                time.sleep(1)
    finally:
        steam.close()
        if library_client:
            library_client.close()
        if itad:
            itad.close()
        notifier.close()
        save_state(state)
    log.info("已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
