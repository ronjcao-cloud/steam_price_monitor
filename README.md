# Steam Price Monitor（独立容器版）

轻量 Steam 国区价格监控，跑在飞牛 NAS 的 Docker 里。降价 / 跌破目标价 / 转免费时，
通过**飞书**或**钉钉**自定义机器人推消息（可同时推两个）。

剥离自 [Sakura520222/steam_price_monitor](https://github.com/Sakura520222/steam_price_monitor)
（原项目是 AstrBot 插件，无法独立运行），保留国区价格查询的核心逻辑，去掉聊天框架、
大模型翻译、matplotlib 图表等依赖。

## 功能

- 每 N 小时查一次 Steam 国区价格（默认 6 小时）
- 降价 / 跌破目标价 / 转免费 → 推送；涨价默认不打扰（可配置）
- 可选：自动监控 Steam **愿望清单**里尚未拥有的游戏
- 可选：消息里附带 ITAD **国区史低**参考价
- 状态持久化在 `data/state.json`，容器重启不丢基线
- **纯出站**：不监听任何端口，无数据库、无反向代理需求

## 快速开始（NAS 上）

```bash
# 1. 准备配置
cd Steam-Pricing/config
cp config.yaml.example config.yaml
vi config.yaml          # 填飞书和/或钉钉，改 games 列表

# 2. 构建并启动
cd ..
docker compose up -d --build

# 3. 看日志
docker compose logs -f steam-price-monitor
```

**首次运行只记录基线价，不会推送**——这是正常的，之后有变动才推。想立刻验证通道通不通，
见下面「验证推送通道」。

### 飞牛 NAS 图形界面做法

不想敲命令的话：**Docker → Compose → 新建项目**，把 `docker-compose.yml` 内容粘进去、
项目路径选到本目录即可。首次创建会触发构建。

> 国内网络提示：拉 `python:3.12-slim` 或装 PyPI 依赖慢/失败时，改
> `docker-compose.yml` 里 `build.args` 两行注释中的镜像源（daocloud 基础镜像 + 清华 PyPI）。

## 一次性准备：推送机器人

### 飞书

1. 建一个只有你自己的群（或拉到已有群）
2. 群设置 → 群机器人 → 添加机器人 → **自定义机器人**
3. 安全设置建议选**签名校验**，记下 secret
4. 复制 webhook（形如 `https://open.feishu.cn/open-apis/bot/v2/hook/xxxx`）
5. 填到 `config/config.yaml` 的 `feishu:` 段

### 钉钉

1. 群设置 → 智能群助手 → 添加机器人 → **自定义（通过 Webhook 接入）**
2. 安全设置三选一，**推荐「加签」**：
   - **加签** → 把密钥填到 `dingtalk.secret`
   - **自定义关键词** → 把关键词填到 `dingtalk.keyword`，程序会自动加到每条消息开头
     （不填会被钉钉以 `errcode 310000` 拒收）
   - IP 地址段 → 不用管（本程序纯出站，但 NAS 的公网出口 IP 会变，不推荐）
3. 复制 webhook 里的 `access_token=xxxx` 那段，填到 `dingtalk.access_token`

两个通道都填就会**同时推**；只填一个就只推那一个。一个都不填会启动报错。

## 验证推送通道

```bash
docker compose exec steam-price-monitor python -c "
from app.config import Config
from app.notifier import build_notifier
c = Config.load('/config/config.yaml')
n = build_notifier(c)
print('通道:', type(n).__name__)
print('发送结果:', n.send_text('✅ Steam 价格监控已上线'))
"
```

返回 `True` 且群里收到消息就说明通了。

## 改关注列表

编辑 `config/config.yaml`，然后：

```bash
docker compose restart steam-price-monitor
```

游戏 appid 从商店链接取：`https://store.steampowered.com/app/1091500/` → `1091500`。

## 配置项速查

| 配置 | 说明 |
| --- | --- |
| `feishu.webhook_url` / `secret` | 飞书机器人；也可用环境变量 `FEISHU_WEBHOOK_URL` / `FEISHU_SECRET` |
| `dingtalk.access_token` / `secret` / `keyword` | 钉钉机器人；也可用 `DINGTALK_TOKEN` / `DINGTALK_SECRET` / `DINGTALK_KEYWORD` |
| `monitor.interval_minutes` | 轮询间隔（分钟），默认 360 |
| `monitor.notify_on_rise` | 涨价是否通知，默认 `false` |
| `steam.api_key` / `id` / `sync_hours` | 填了就自动监控愿望清单；`id` 可填 17 位数字或自定义 ID |
| `itad.api_key` | 填了消息里多一行「国区史低」 |
| `games[]` | 手动关注列表，`target_price` 是心理价位 |

环境变量优先级高于配置文件，适合把密钥放在 NAS 的环境变量里而不落盘。

## 排错

| 现象 | 原因 / 处理 |
| --- | --- |
| 启动就报「至少配置一个推送通道」 | `config.yaml` 里飞书和钉钉都没填 |
| 钉钉返回 `errcode 310000` | 安全设置选了关键词但没配 `keyword`，或关键词不在消息里 |
| 钉钉返回 `errcode 310000` 且提示 sign | 加签密钥不对；确认 `dingtalk.secret` 填的是「加签」的密钥 |
| 飞书返回 `code 19021` | 签名校验开了但 `feishu.secret` 没填或填错 |
| 一直不推送 | 首次只记基线；之后只在**降价**、**跌破目标价**、**刚变成免费**这三种情况推。价格没变就不推 |
| 免费游戏会不会每轮都推 | 不会。「转为免费」只在「原本不免费 → 变成免费」那一次推。已经免费的游戏后续轮次静默，否则每 6 小时骚扰一次 |
| 日志显示 `无价格信息` | 该游戏国区未上架或未发售 |
| 容器反复重启，日志 `PermissionError: [Errno 13] Permission denied: 'app/app/__init__.py'` | 构建上下文里的文件权限是 `000`（从 Windows 打包 zip 再解压到 NAS 上很常见）。Dockerfile 里的 `chmod -R a+rX /app` 就是为这种情况准备的，请勿删除 |
| 日志偶发 `The handshake operation timed out` / `The read operation timed out` | 国内访问 Steam 偶发超时，程序自带重试（价格 2 次、库同步 3 次退避）。偶发一条不影响监控，连续超时才会记 warning |
| 日志 `拉取已拥有游戏失败（不影响愿望清单同步）` | 解析 steamid 失败（填自定义 ID 时需要 `api.steampowered.com`）。愿望清单照样会爬，只是无法排除已拥有的游戏 |

## 安全说明

- 程序**只走出站**：请求 Steam 商店 API、ITAD、飞书/钉钉 webhook，不监听任何端口
- NAS 的 IPv6 防火墙、Tailscale/WireGuard 等**入站规则完全不用动**
- webhook 地址 / secret 等价于群聊发言权限，不要提交到 git、不要外发
- `config/config.yaml` 已在 `.gitignore` 里排除
- 容器以非 root 用户（uid 1000）运行

## 目录结构

```
Steam-Pricing/
├── app/
│   ├── main.py            # 主循环、消息组装、状态持久化
│   ├── config.py          # 配置加载与校验
│   ├── steam_client.py    # Steam 国区价格 API
│   ├── steam_library.py   # 愿望清单 / 已拥有游戏同步（可选）
│   ├── itad_client.py     # ITAD 史低查询（可选）
│   └── notifier.py        # 飞书 / 钉钉 webhook 推送
├── config/
│   ├── config.yaml.example
│   └── config.yaml        # 你自己填（不入库）
├── data/
│   └── state.json         # 运行时自动生成
├── reference/             # 原 AstrBot 插件的文件，仅供对照，不参与运行
├── Dockerfile
└── docker-compose.yml
```

## 本机部署记录（飞牛 NAS）

| 项 | 值 |
| --- | --- |
| 宿主机目录 | `/vol1/1000/Docker/steam-price-monitor` |
| Compose 项目名 | `steam-price-monitor` |
| 容器 | `steam-price-monitor`，`restart: unless-stopped` |
| 镜像 | `steam-price-monitor:latest` |
| 状态文件 | `data/state.json`（卷挂载，重建容器不丢基线） |
| 推送通道 | 飞书（已实际验证送达） |

**改完 `app/` 下的代码要重建镜像才生效**：光点「重新部署」只会复用旧镜像层。
正确顺序是先删容器、再删旧镜像、再构建，否则跑的还是老代码。

当前每轮监控 15 个游戏 = 手动 2 个 + 愿望清单 14 个（《艾尔登法环》两边都有，去重后 15）。
