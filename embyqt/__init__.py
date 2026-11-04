"""WhalePlayer —— 基于 Emby REST API 的桌面客户端。"""

__version__ = "1.2.0"

APP_NAME = "WhalePlayer"
APP_TITLE = "WhalePlayer"
ORG_NAME = "WhalePlayer"

# 兼容旧版本的 QSettings 路径，避免升级后丢失登录态和配置。
SETTINGS_ORG = "EmbyQt"
SETTINGS_APP = "EmbyQt"

# 服务器对客户端名做了白名单校验（Cloudflare 层），这里使用被放行的名称，
# 详见 README「服务器限制」一节。
CLIENT_NAME = "Emby for Android"
CLIENT_VERSION = "1.1.0"
DEVICE_NAME = "WhalePlayer Desktop"
