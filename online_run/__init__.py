import asyncio
import re
import json
import time
from . import xes
from aiohttp import ClientSession, WSMessage
from typing import Literal

from graia.ariadne import Ariadne
from graia.ariadne.event.message import GroupMessage, MessageEvent
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image
from graia.ariadne.message.parser.twilight import (
    Twilight,
    UnionMatch,
    WildcardMatch,
    MatchResult,
)
from graia.saya import Channel
from graia.saya.builtins.broadcast import ListenerSchema

# from kayaku import create
# from loguru import logger

from library.decorator.blacklist import Blacklist
from library.decorator.function_call import FunctionCall
from library.decorator.distribute import Distribution
from library.decorator.switch import Switch
from library.util.dispatcher import PrefixMatch

from library.decorator.timer import timer

from library.util.image import render_md
from library.util.message import send_message
from library.util.misc import seconds_to_string

channel = Channel.current()


@channel.use(
    ListenerSchema(
        listening_events=[GroupMessage],
        inline_dispatchers=[
            Twilight(
                [
                    PrefixMatch(),
                    UnionMatch("cpp", "python") @ "run_type",
                    WildcardMatch().flags(re.S) @ "raw",
                ]
            )
        ],
        decorators=[
            Switch.check(channel.module),
            Blacklist.check(),
            Distribution.distribute(),
            FunctionCall.record(channel.module),
        ],
    )
)
async def execute_command(
    app: Ariadne, event: MessageEvent, run_type: MatchResult, raw: MatchResult
):
    run_type: Literal["cpp"] | Literal["python"] = run_type.result.display.strip()
    raw: str = raw.result.display.strip()
    idx: int = raw.find("\n")
    code = ""
    stdin = ""
    if idx != -1 and raw[0] == '"':
        try:
            stdin = json.loads(raw[0:idx])
            code = raw[idx + 1 :]
            if not isinstance(stdin, str):
                return await send_message(
                    event, MessageChain("你不会以为我会给你转成str吧？"), app.account
                )
        except BaseException:
            stdin = ""
            code = raw
    else:
        stdin = ""
        code = raw
    stdout, time_cost = await execute(run_type, code, stdin)
    image = await render(stdout, time_cost)
    await send_message(event, MessageChain(Image(data_bytes=image)), app.account)


async def _execute(
    run_type: Literal["cpp"] | Literal["python"], code: str, stdin: str
) -> str:
    s = ""
    async with ClientSession() as session:
        c = await xes.create(
            session,
            xes.Language.Cpp if run_type == "cpp" else xes.Language.Python,
            code,
            [],
        )
        s += f"[Host {c.host()}]\n"
        await c.send(stdin)
        try:
            while msg := await c.receive(10):
                if isinstance(msg, WSMessage):
                    break
                else:
                    match msg.type:
                        case xes.MsgType.System:
                            s += f"[System {msg.data.decode(encoding='utf-8')}]\n"
                        case xes.MsgType.Output:
                            s += msg.data.decode(encoding="utf-8")
                        case xes.MsgType.Unknown:
                            s += f"[Unknown {msg.data.decode(encoding='utf-8')}]\n"
        except TimeoutError:
            await c.close()
            s += "\n[Timeout]"

    return s


@timer(channel.module)
async def execute(
    run_type: Literal["cpp"] | Literal["python"], code: str, stdin: str
) -> tuple[str, float]:
    start_time = time.perf_counter()
    stdout = await _execute(run_type, code, stdin)
    return stdout, time.perf_counter() - start_time


async def render(stdout: str, time_used: float) -> bytes:
    # config: EricConfig = create(EricConfig)
    _time_int = int(time_used)
    _time_float = time_used - _time_int
    time_str = f"{seconds_to_string(_time_int)} {_time_float} 毫秒"

    md = f"""
# 代码执行完毕

## 执行耗时

```text
{time_str}
```

## 返回

```text
{stdout}
```
"""
    return await render_md(md)
