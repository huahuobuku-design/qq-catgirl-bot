# 参与开发

Python 3.11+，安装 `requirements.txt`，运行 `python -m unittest discover -s tests -v`。

测试使用模拟API和OneBot，不要求真实密钥，不向真实QQ群发送消息。涉及API适配、消息合并、管理员权限、超时取消、表情包解析的修改请补相应测试。

提交前检查 `git diff --cached`。不要加入 config.json、data/、本地图片、虚拟环境、聊天日志或真实账号信息。用合成消息和临时生成图片复现问题。

此项目仅实现 Chat Completions API 接入；新增服务商适配须沿用短消息与图片ID的统一回复格式。
