# -*- coding: utf-8 -*-
"""
bot.py — QQ 群猫娘机器人（OneBot v11 / NapCat / Lagrange / go-cqhttp）

特性
  · 群里每条新消息都会回应
  · 消息轰炸时自动合并，只针对「最近的」几条说话，不刷屏
  · API生成短句和表情选择，群白名单与触发策略可配置
  · 自带冷却时间与静音开关，防止被风控

启动
  python bot.py            # 读同目录 config.json
  python bot.py -c x.json  # 指定配置
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import random
import re
import sys
import time
from collections import deque
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import websockets

from catgirl import CatGirl, clip, is_noise, strip_cq

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from configuration import DEFAULT_CONFIG, load_config, validate_config


def setup_logging(level: str = "INFO") -> logging.Logger:
    # 控制台是 GBK(936) 时，日志里若出现 GBK 表示不了的字符（机器人回复可能带 emoji），
    # 会抛 UnicodeEncodeError。这里只把 errors 改成 replace，不动 encoding，
    # 保证中文照常、个别字符降级成 ?，日志永远不会因编码而断。
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    logger = logging.getLogger("catgirl")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(os.path.join(BASE_DIR, "data", "bot.log"), encoding="utf-8", maxBytes=2_000_000, backupCount=3)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


# --------------------------------------------------------------------------
# OneBot v11 客户端
# --------------------------------------------------------------------------

def build_ws_url(base: str, token: str = "") -> str:
    """token 走 query，兼容性最好；也支持调用方直接传完整 URL。"""
    if not token or "access_token=" in base:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}access_token={quote(token, safe='')}"


class OneBot:
    """正向 WebSocket 客户端。收到事件 → 回调；调用 API → 等 echo 响应。"""

    def __init__(self, url: str, token: str = "", logger: Optional[logging.Logger] = None):
        self.url = build_ws_url(url, token)
        self.ws = None
        self.logger = logger or logging.getLogger("catgirl")
        self._echo = 0
        self._pending: Dict[str, asyncio.Future] = {}
        self._recv_task: Optional[asyncio.Task] = None
        self.on_event = None  # 由外部注入 async callable

    async def connect(self) -> None:
        # 注意：本机装了 HTTP_PROXY/HTTPS_PROXY 时，websockets 会把这些代理
        # 也套到 ws://127.0.0.1 上，结果必然 502（NapCat 就在本机，不该过代理）。
        # 所以下面显式传 proxy=None，并且因为各版本参数名不同而逐组降级尝试。
        common = {"ping_interval": 20, "ping_timeout": 20, "max_size": 2 ** 22}
        attempts = (
            {"additional_headers": None, "proxy": None},
            {"additional_headers": None},
            {"extra_headers": None, "proxy": None},
            {"extra_headers": None},
            {"proxy": None},
            {},
        )
        last_err: Optional[Exception] = None
        for extra in attempts:
            kwargs = dict(common)
            kwargs.update(extra)
            # headers 传 None 要删掉；proxy 的 None 是有意义的值，必须留着
            kwargs = {k: v for k, v in kwargs.items()
                      if not (k.endswith("headers") and v is None)}
            try:
                self.ws = await websockets.connect(self.url, **kwargs)
                return
            except TypeError as e:  # 参数不被支持 → 换下一组
                last_err = e
                continue
        if last_err:
            raise last_err
        raise RuntimeError("无法建立 WebSocket 连接")

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            self._recv_task = None
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

    async def call(self, action: str, params: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
        if not self.ws:
            raise ConnectionError("WebSocket 未连接")
        self._echo += 1
        echo = f"e{self._echo}"
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[echo] = fut
        payload = {"action": action, "params": params, "echo": echo}
        await self.ws.send(json.dumps(payload, ensure_ascii=False))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(echo, None)
            raise
        finally:
            self._pending.pop(echo, None)

    async def send_group_msg(self, group_id: int, text: str) -> Optional[int]:
        resp = await self.call("send_group_msg", {"group_id": group_id, "message": text})
        if resp.get("status") != "ok" or resp.get("retcode", 0) != 0:
            raise RuntimeError(f"OneBot 发送失败，retcode={resp.get('retcode')}")
        return (resp.get("data") or {}).get("message_id")

    async def send_group_image(self, group_id: int, path: str) -> Optional[int]:
        from pathlib import Path
        file = Path(path)
        if file.stat().st_size > 1_500_000:
            raise ValueError('表情包超过大小限制')
        encoded = base64.b64encode(file.read_bytes()).decode('ascii')
        segments = [{'type': 'image', 'data': {'file': 'base64://' + encoded,
                                              'sub_type': 1, 'summary': '[猫娘表情]'}}]
        response = await self.call('send_group_msg', {'group_id': group_id, 'message': segments}, timeout=30)
        if response.get('status') != 'ok' or response.get('retcode', 0) != 0:
            raise RuntimeError(f"表情包发送失败，retcode={response.get('retcode')}")
        return (response.get('data') or {}).get('message_id')

    async def pump(self) -> None:
        """一个循环分发：带 echo 的是 API 响应，带 post_type 的是事件。"""
        assert self.ws is not None
        async for raw in self.ws:
            try:
                data = json.loads(raw)
            except Exception:
                continue
            echo = data.get("echo")
            if echo and echo in self._pending:
                fut = self._pending.get(echo)
                if fut and not fut.done():
                    fut.set_result(data)
                continue
            if data.get("post_type") and self.on_event:
                asyncio.create_task(self.on_event(data))


# --------------------------------------------------------------------------
# 每个群一个工作线程
# --------------------------------------------------------------------------

class GroupWorker:
    """
    消息流 → 回复 的核心调度。

    设计要点（对应「新消息都说话」+「消息太多优先回最近的」）：
      · 每条消息都进 inbox，任何一条都不会被丢掉
      · 攒一个很短的合并窗口：1 秒内没人再说话就立刻回（逐条回落，人少时很灵敏）
      · 如果窗口一直被打断，最多等 4 秒就强制开口（不会永远憋着）
      · 一次要处理的消息超过 focus_recent 条时，前面的当背景，只针对最近几条说话
      · 说完还有冷却，避免连发被风控
    """

    def __init__(self, bot: OneBot, cat: CatGirl, cfg: Dict[str, Any], group_id: int,
                 logger: logging.Logger):
        self.bot = bot
        self.cat = cat
        self.cfg = cfg
        self.group_id = group_id
        self.logger = logger

        r = cfg["reply"]
        self.debounce = float(r["debounce_seconds"])
        self.max_wait = float(r["max_wait_seconds"])
        self.ctx_size = int(r["context_size"])
        self.focus_recent = max(1, int(r["focus_recent"]))
        self.min_interval = float(r["min_interval_seconds"])
        self.probability = float(r["probability"])
        self.max_burst = int(r.get("max_burst", 4))

        self.inbox: deque = deque(maxlen=self.ctx_size)
        self._seq = 0
        self._handled = 0
        self._wake = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._last_sent = 0.0
        self.muted = False

    # -- 生产者 -------------------------------------------------------------
    def feed(self, user: str, user_id: int, text: str) -> None:
        self._seq += 1
        self.inbox.append({
            "seq": self._seq,
            "user": user,
            "user_id": user_id,
            "text": text,
            "ts": time.time(),
        })
        self._wake.set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    # -- 消费者 -------------------------------------------------------------
    async def _settle(self) -> None:
        """合并窗口：安静 debounce 秒就动手；被打断最多拖到 max_wait 秒。"""
        deadline = time.monotonic() + self.max_wait
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                return
            window = min(self.debounce, remain)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=window)
                self._wake.clear()
            except asyncio.TimeoutError:
                return

    async def _run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            await self._settle()

            batch = [m for m in self.inbox if m["seq"] > self._handled]
            if not batch:
                continue

            # —— 关键：消息多的时候，只回应最近的一小撮 ——
            if len(batch) > self.focus_recent:
                focus = batch[-self.focus_recent:]
                self.logger.info(
                    f"[群{self.group_id}] 一口气来了 {len(batch)} 条，"
                    f"跳过前面 {len(batch) - len(focus)} 条，只回应最近的 {len(focus)} 条"
                )
            else:
                focus = batch
            self._handled = batch[-1]["seq"]

            if self.muted:
                self.logger.info(f"[群{self.group_id}] 静音中，跳过 {len(batch)} 条")
                continue
            if random.random() > self.probability:
                continue

            history = list(self.inbox)
            acknowledgement_sent = False
            generation = None
            try:
                generation = asyncio.create_task(self.cat.reply(history, focus, scope=str(self.group_id)))
                ready, _ = await asyncio.wait({generation}, timeout=float(self.cfg["reply"].get("ack_after_seconds", 6)))
                if not ready and not self.muted and self.max_burst >= 2:
                    try:
                        await self.bot.send_group_msg(self.group_id, '本喵想一下，等我几秒。')
                        acknowledgement_sent = True
                        self._last_sent = time.monotonic()
                        self.logger.info(f'[群{self.group_id}] 生成超过6秒，已发送等待提示')
                    except Exception as error:
                        self.logger.warning(f'[群{self.group_id}] 等待提示发送失败：{type(error).__name__}')
                text = await generation
            except asyncio.CancelledError:
                if generation:
                    generation.cancel()
                raise
            except Exception as e:
                self.logger.error(f"[群{self.group_id}] 生成回复失败：{e}")
                self.cat.reply_stickers.pop(str(self.group_id), None)
                text = '本喵这边连接卡住了，稍后再试。'
            if not text:
                continue
            if self.muted:
                continue

            # 冷却，防止连发
            gap = self.min_interval - (time.monotonic() - self._last_sent)
            if gap > 0:
                await asyncio.sleep(gap)

            try:
                from stickers import split_short_messages
                scope = str(self.group_id)
                sticker_id = self.cat.reply_stickers.pop(scope, None)
                sticker = self.cat.stickers.get(sticker_id)
                # Reserve one burst slot for the image. max_burst counts all messages.
                slots = max(1, self.max_burst - int(acknowledgement_sent))
                if slots < 2:
                    sticker = None
                bubbles = split_short_messages(text, count=min(3, slots - (1 if sticker else 0)))
                for index, bubble in enumerate(bubbles):
                    if index:
                        await asyncio.sleep(0.8)
                    await self.bot.send_group_msg(self.group_id, bubble)
                text = '\n'.join(bubbles)
                if sticker:
                    try:
                        await asyncio.sleep(0.8)
                        await self.bot.send_group_image(self.group_id, sticker['path'])
                        self.cat.stickers.mark_sent(scope, sticker_id)
                        self.logger.info(f"[群{self.group_id}] 表情包：{sticker['title']}")
                    except Exception as error:
                        self.logger.warning(f"[群{self.group_id}] 表情发送失败，文字已发送：{type(error).__name__}: {error}")
                self._last_sent = time.monotonic()
                self.inbox.append({'seq': self._handled, 'user': self.cat.name,
                                   'user_id': 0, 'text': text, 'ts': time.time()})
                who = ", ".join(clip(m["user"], 10) for m in focus[-2:])
                if self.cfg.get('privacy', {}).get('log_message_content', False):
                    self.logger.info(f"[群{self.group_id}] 回复：{text}")
                else:
                    self.logger.info(f"[群{self.group_id}] 已发出{len(bubbles)}条短消息")
            except Exception as e:
                self.logger.error(f"[群{self.group_id}] 发送失败：{e!r}")


# --------------------------------------------------------------------------
# 总控
# --------------------------------------------------------------------------

class CatGirlBot:
    def __init__(self, cfg: Dict[str, Any], logger: logging.Logger, profile_store=None):
        self.cfg = cfg
        self.logger = logger
        from profiles import ProfileStore, resolve_api_settings
        self.profile_store = profile_store or ProfileStore()
        self.cat = CatGirl(dict(cfg.get("engine") or {}, llm=resolve_api_settings(cfg,self.profile_store), persona=cfg.get("persona") or {}), logger=logger)
        self.bot = OneBot(cfg["onebot_url"], cfg.get("access_token", ""), logger)
        self.bot.on_event = self.on_event
        self.workers: Dict[int, GroupWorker] = {}
        self.self_id = int(cfg.get("self_id") or 0)
        self._seen: deque = deque(maxlen=200)

        wl = cfg["groups"].get("whitelist") or []
        bl = cfg["groups"].get("blacklist") or []
        self.whitelist = {int(x) for x in wl}
        self.blacklist = {int(x) for x in bl}

    # -- 权限 ---------------------------------------------------------------
    def group_allowed(self, gid: int) -> bool:
        if gid in self.blacklist:
            return False
        if self.whitelist:
            return gid in self.whitelist
        return bool(self.cfg["groups"].get("allow_all", False))

    def get_worker(self, gid: int) -> GroupWorker:
        w = self.workers.get(gid)
        if w is None:
            w = GroupWorker(self.bot, self.cat, self.cfg, gid, self.logger)
            w.start()
            self.workers[gid] = w
            self.logger.info(f"新建群工作线程：{gid}")
        return w

    # -- 事件 ---------------------------------------------------------------
    async def on_event(self, ev: Dict[str, Any]) -> None:
        if ev.get("post_type") != "message":
            return
        if ev.get("message_type") != "group":
            return

        gid = int(ev.get("group_id") or 0)
        uid = int(ev.get("user_id") or 0)
        if not gid or not uid:
            return

        sid = int(ev.get("self_id") or 0)
        if sid:
            self.self_id = self.self_id or sid
        if uid == self.self_id:
            return  # 自己的消息不触发自己

        mid = ev.get("message_id")
        if mid is not None and mid in self._seen:
            return  # 重复上报去重
        if mid is not None:
            self._seen.append(mid)

        if not self.group_allowed(gid):
            return

        raw = ev.get("raw_message") or ""
        if not raw:
            message = ev.get("message")
            if isinstance(message, str):
                raw = message
            elif isinstance(message, list):
                raw = "".join(str((segment.get("data") or {}).get("text", ""))
                              for segment in message if isinstance(segment, dict) and segment.get("type") == "text")
        text = strip_cq(raw).strip()
        if is_noise(text):
            return

        sender = ev.get("sender") or {}
        nick = sender.get("card") or sender.get("nickname") or str(uid)

        # Management controls require an explicit administrator or OneBot role.
        management = self.cfg.get('administration', {})
        can_control = (management.get('allow_member_controls', False)
                       or uid in management.get('admin_ids', [])
                       or sender.get('role') in ('owner', 'admin'))
        controls = re.fullmatch(r'(猫娘)?(闭嘴|安静|别说了|别叫了|说话|出来|醒醒|开机|解除静音)', text.replace(' ', ''))
        if controls and not can_control:
            return
        if not controls and self.cfg['reply'].get('trigger') != 'all':
            message = ev.get('message', [])
            mentioned = (isinstance(message, list) and any(
                isinstance(segment, dict) and segment.get('type') == 'at'
                and str((segment.get('data') or {}).get('qq')) == str(self.self_id)
                for segment in message))
            mentioned = mentioned or f'[CQ:at,qq={self.self_id}' in str(ev.get('raw_message', ''))
            if not mentioned and not any(word in text for word in self.cfg['reply'].get('keywords', ['猫娘'])):
                return

        # 群内开关
        w = self.get_worker(gid)
        cmd = text.replace(" ", "")
        if re.fullmatch(r"(猫娘)?(闭嘴|安静|别说了|别叫了)", cmd):
            w.muted = True
            self.logger.info(f"[群{gid}] 静音")
            return
        if re.fullmatch(r"(猫娘)?(说话|出来|醒醒|开机|解除静音)", cmd):
            w.muted = False
            self.logger.info(f"[群{gid}] 解除静音")
            return
        if re.fullmatch(r"(猫娘)?(状态|在干嘛)", cmd):
            w.feed(nick, uid, "猫娘状态")
            return

        if self.cfg.get('privacy', {}).get('log_message_content', False):
            self.logger.info(f"[群{gid}] 收到消息：{clip(text, 40)}")
        else:
            self.logger.info(f"[群{gid}] 收到可回复消息（{len(text)}字）")
        w.feed(nick, uid, text)

    # -- 生命周期 -----------------------------------------------------------
    async def run_forever(self) -> None:
        backoff = 1.0
        while True:
            profile_watch = None
            try:
                try:self.profile_store.load(self.cfg['engine']['profile_id'])
                except ValueError:
                    self.logger.error('在用API档案已删除或失效，群回复已停止')
                    return
                await self.bot.connect()
                async def watch_profile():
                    while True:
                        await asyncio.sleep(1)
                        try:self.profile_store.load(self.cfg['engine']['profile_id'])
                        except ValueError:
                            await self.bot.close()
                            return
                profile_watch=asyncio.create_task(watch_profile())
                self.logger.info('已连接 OneBot')
                backoff = 1.0
                await self.bot.pump()
                self.logger.warning("连接已断开，准备重连…")
            except asyncio.CancelledError:
                raise
            except ConnectionRefusedError as e:
                self.logger.error('QQ 接口连接被拒，请检查客户端登录及监听端口')
                self.logger.error("  NapCat 能收到 QQ 消息也不代表 OneBot 已开启；请检查当前登录账号的正向 WebSocket 服务。")
                self.logger.error("  在 NapCat 中为当前账号启用 127.0.0.1:3001，Token 与猫娘一致；换号后需单独配置。")
                self.logger.error("  若 NapCat 尚未登录，请先启动并登录；只有提示重复登录时才需退出同账号的普通 QQ。")
            except Exception as e:
                self.logger.error(f"连接异常：{type(e).__name__}: {e}")
            finally:
                if profile_watch:
                    profile_watch.cancel()
                    await asyncio.gather(profile_watch,return_exceptions=True)
                await self.bot.close()
                for w in self.workers.values():
                    w.stop()
                self.workers.clear()

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


# --------------------------------------------------------------------------

def _main() -> None:
    ap = argparse.ArgumentParser(description="QQ 群猫娘机器人")
    ap.add_argument("-c", "--config", default=os.path.join(BASE_DIR, "config.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logger = setup_logging("DEBUG" if args.verbose else "INFO")
    cfg = load_config(args.config)

    validate_config(cfg)
    engine_desc = "Chat Completions API"
    logger.info("=" * 52)
    logger.info("  猫娘 QQ 机器人启动中…")
    logger.info('  QQ 接入点已配置（凭据不写入日志）')
    logger.info(f"  说话引擎 {engine_desc}")
    logger.info(f"  群白名单 {sorted(cfg['groups'].get('whitelist') or []) or '显式允许全部群'}")
    logger.info(f"  冷却     {cfg['reply']['min_interval_seconds']}s / 条")
    logger.info("=" * 52)

    bot = CatGirlBot(cfg, logger)
    try:
        asyncio.run(bot.run_forever())
    except KeyboardInterrupt:
        logger.info("收到中断，猫娘下班了喵。")


def main() -> None:
    from runtime_guard import InstanceLock
    guard = InstanceLock(os.path.join(BASE_DIR, "data", "bot.lock"))
    if not guard.acquire():
        print('猫娘回复程序已经运行，本次不重复启动。', flush=True)
        return
    try:
        try:
            _main()
        except (ValueError, OSError) as error:
            print(f'启动失败：{error}', flush=True)
            raise SystemExit(2) from None
    finally:
        guard.close()


if __name__ == "__main__":
    main()
