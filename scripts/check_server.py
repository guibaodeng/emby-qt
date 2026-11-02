"""服务器能力探测：登录后打印版本、账号策略、媒体库与播放能力。

用法：
    EMBY_SERVER=https://emby.example.com EMBY_USER=name EMBY_PASS=secret \
        .venv/bin/python scripts/check_server.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embyqt.api import EmbyClient, EmbyError
from embyqt.net import detect_proxy


def main() -> int:
    server = os.environ.get("EMBY_SERVER", "https://emby.medi4.org")
    user = os.environ.get("EMBY_USER", "")
    password = os.environ.get("EMBY_PASS", "")
    if not user or not password:
        print("请通过 EMBY_USER / EMBY_PASS 环境变量提供账号")
        return 2

    proxy = detect_proxy()
    print(f"系统代理：{proxy.describe() if proxy else '未使用代理'}")
    client = EmbyClient(server, "capability-probe", proxy=proxy)
    try:
        profile = client.login(user, password)
    except EmbyError as exc:
        print(f"登录失败：{exc}")
        return 1

    print(f"服务器：{server}")
    policy = profile.get("Policy") or {}
    print(f"用户：{profile.get('Name')}（{'管理员' if policy.get('IsAdministrator') else '普通用户'}）")
    for key in (
        "EnableMediaPlayback",
        "EnableVideoPlaybackTranscoding",
        "EnableAudioPlaybackTranscoding",
        "EnablePlaybackRemuxing",
        "EnableContentDownloading",
        "RemoteClientBitrateLimit",
        "SimultaneousStreamLimit",
    ):
        print(f"  {key}: {policy.get(key)}")

    info = client.server_info()
    print(f"版本：{info.get('ServerName')} · Emby {info.get('Version')} · {info.get('Id')}")

    views = client.get_views()
    print(f"媒体库（{len(views)}）：")
    for view in views:
        count = ""
        try:
            data = client.get_items(
                parent_id=str(view.get("Id")),
                include_types="Movie,Series,BoxSet,Video",
                limit=1,
            )
            count = f"  {data.get('TotalRecordCount', 0)} 项"
        except EmbyError:
            pass
        print(f"  - {view.get('Name')} <{view.get('CollectionType')}>{count}")

    item = None
    for view in views:
        if view.get("CollectionType") == "movies":
            data = client.get_items(
                parent_id=str(view.get("Id")),
                include_types="Movie",
                limit=1,
            )
            if data.get("Items"):
                item = data["Items"][0]
                break
    if item:
        print(f"样例：{item.get('Name')}")
        playback = client.playback_info(str(item["Id"]))
        for source in playback.get("MediaSources", []):
            print(
                "  直连播放:",
                source.get("SupportsDirectPlay"),
                "直连串流:",
                source.get("SupportsDirectStream"),
                "转码:",
                source.get("SupportsTranscoding"),
                "容器:",
                source.get("Container"),
            )
    client.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
