from enum import Enum
from asyncio import Task
from base64 import b64decode
import json
import asyncio
from aiohttp import ClientWebSocketResponse, WSMessage, WSMsgType, ClientSession

# 要运行的代码的语言。
class Language(Enum):
    Cpp = "cpp"
    Python = "python"


# 由远程端传回消息的类型。
class MsgType(Enum):
    Output = "Output"  # 远程输出
    System = "System"  # 系统消息
    Unknown = "Unknown"  # 未知/不支持


class MsgEvent:
    type: MsgType
    data: bytes

    def __init__(self, type: MsgType, data: bytes):
        self.type, self.data = type, data


class XesRemote:
    __ws: ClientWebSocketResponse
    __echo: bool
    __sended: bool
    __heartbeat: Task
    __host: str

    async def __heartbeat_event(self):
        while 1:
            await asyncio.sleep(10)
            await self.__ws.send_str("2")

    def host(self) -> str:
        return self.__host

    async def send(self, msg: str):
        if len(msg) < 1:
            return
        await self.__ws.send_str("1" + msg)
        self.__sended = True

    async def close(self):
        await self.__ws.close()

    async def receive(self, timeout: float | None = None) -> MsgEvent | WSMessage:
        r = await self.__ws.receive(timeout)
        if r.type == WSMsgType.TEXT:
            d: str = r.data
            match d[0]:
                case "1":
                    if self.__echo or not self.__sended:
                        return MsgEvent(MsgType.Output, b64decode(d[1:]))
                    self.__sended = False
                case "7":
                    return MsgEvent(MsgType.System, b64decode(d[1:]))
                case "3":
                    return await self.receive()
                case "2":
                    return await self.receive()
                case _:
                    return MsgEvent(MsgType.Unknown, d.encode(encoding='utf-8'))
        elif r.type == WSMsgType.CLOSED:
            try:
                self.__heartbeat.cancel()
            except asyncio.CancelledError:
                pass
        return r

    def __aiter__(self):
        return self

    async def __anext__(self) -> MsgEvent:
        r = await self.receive()
        if isinstance(r, WSMessage):
            raise StopAsyncIteration()
        else:
            return r

    def __init__(self, ws: ClientWebSocketResponse, host: str, echo: bool = False):
        self.__ws, self.__host, self.__echo, self.__sended = ws, host, echo, False
        self.__heartbeat = asyncio.get_event_loop().create_task(
            self.__heartbeat_event()
        )


async def create(
    session: ClientSession,
    lang: Language,
    content: str,
    args: list[str] = list(),
    echo: bool = False,
) -> XesRemote:
    ws = await session.ws_connect("wss://codedynamic.xueersi.com/api/compileapi/ws/run")
    await ws.send_json({})
    await ws.send_str(
        "7{}".format(
            json.dumps(
                {
                    "xml": content,
                    "type": "run",
                    "lang": lang.value,
                    "original_id": 1,
                    "args": args,
                }
            )
        )
    )
    return XesRemote(ws, ws._response.headers["server"], echo)


async def main():
    async with ClientSession() as c:
        a = await create(
            c,
            Language.Cpp,
            """
    #include<iostream>
    int main() {
        std::cout << "Hello World";
    }
    """,
            [],
            True,
        )
        async for i in a:
            print(i.data.decode(encoding="utf-8"))


asyncio.run(main())
