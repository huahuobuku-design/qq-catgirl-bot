# QQ猫娘 · 炸毛小恶魔

通过 **Chat Completions API + OneBot v11 正向 WebSocket** 接入QQ群的角色聊天机器人。

活泼、傲娇、容易炸毛，也会被一句夸奖哄好。支持短句连发、按群保存情绪、用户自备表情包和本地试聊。

## 功能

- **只通过 API 调用模型**：先在本地新建并保存API档案，再选择使用；不依赖其他应用的账号登录。
- **档案保存后只读**：可以选择、查看摘要或删除，不能编辑；更换地址、模型、Key及其他参数时必须新建档案。
- **短句连发**：通常1～3条，每条尽量6～20字，程序上限28字；气泡间隔约0.8秒。每轮连同等待提示及图片最多4条。
- **情绪延续**：按群保存愤怒、委屈和简单的捉弄次数。被夸后会软化，重启保留数值状态。
- **自行导入表情包**：支持PNG/JPG/GIF/WebP，按描述和情绪选图、避免近期重复。仓库不附带任何素材；空图库仍能聊天。
- **运行反馈**：生成较慢时先发等待提示；API超时、鉴权和限流等错误显示在控制台。不用随机台词掩盖调用失败。
- **谨慎的默认设置**：空白名单不回复任何群；默认只响应@机器人或含“猫娘”的文字；普通成员不能切换静音。

## 安装与启动

需要 **Python 3.11+**、可用的模型API，以及你自行安装、登录并配置好的 OneBot v11 客户端。桌面控制台还需要 Python 的 tkinter。

Windows：安装Python（包含Python Launcher和tkinter），解压源码，双击 `INSTALL.bat`。以后双击 `START.bat`。

其他系统或手动安装：

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python panel.py
```

Linux如缺少tkinter，需安装发行版提供的Python Tk包。无桌面环境可直接运行 `python bot.py`。

## 第一次配置

1. 在控制台点“新建档案”，填写档案名称、API地址（平台提供的 `/v1` 地址或完整 `/chat/completions` 地址）、模型ID和API Key，核对后保存。
2. 点“本地试聊”检查模型。此处不会向QQ发送消息。
3. 在你自己的OneBot客户端中登录QQ，启用**正向WebSocket服务器**，本机地址通常为 `ws://127.0.0.1:3001`。两端Token需一致。
4. 填入允许回复的群号，多个群用逗号分隔，点“检查QQ”。
5. 点“开启群回复”，在群里发送“猫娘你好”或@机器人。

程序会在首次运行时生成被Git忽略的 `config.json`，也可复制 `config.example.json` 后手动编辑。它只保存选中的 `engine.profile_id`，不保存内嵌API参数。未保存档案、未选档案或在用档案已被删除时不能调用API。修改群聊配置需重启群回复。

API档案保存在本机 `data/api_profiles/`，包含Key的明文文件不会提交Git。没有编辑功能，也不会用环境变量覆盖已保存的Key；Key轮换或更换模型需新建档案。删除正在使用的档案会停止群回复。文件完整性校验用于发现意外编辑，不是密钥加密，也不能阻止电脑所有者直接操作文件。

无桌面环境可运行 `python profiles.py create` 交互式建档，用 `python profiles.py list` 查看ID，再把ID填入 `config.json` 的 `engine.profile_id`。`python profiles.py delete <ID>` 可删除档案。不通过命令行参数传递Key。

## 常用配置

| 配置 | 默认与说明 |
|---|---|
| `groups.whitelist` | 空列表，不回复任何群；填入真实群号后启用 |
| `groups.allow_all` | `false`；显式设为true且白名单为空时允许全部群 |
| `reply.trigger` | `mention_or_keyword`；`all`则回复指定群中的所有有效文字 |
| `reply.keywords` | `["猫娘"]`，可添加其他唤醒词 |
| `administration.admin_ids` | 额外允许管理机器人的QQ号；群主/管理员也可管理 |
| `administration.allow_member_controls` | `false`，不开放普通成员静音/唤醒 |
| `engine.profile_id` | 必须选择已在本地保存的API档案 |
| `privacy.log_message_content` | `false`，默认不把聊天原文写入日志 |

群管理命令：“猫娘闭嘴”“猫娘说话”。回复概率、合并窗口、冷却和消息上限可在 `reply` 下调整。

建档时可设置总超时（默认30秒，包含并发排队）、输出Token上限（默认400）、温度、JSON模式（默认关闭）及是否遵循代理环境变量。保存后这些参数同样不可编辑。

## 表情包与人格

将自己的图片放到 `stickers/`，使用描述图意的文件名或情绪子目录，然后点击“导入表情包”，或运行：

```sh
python import_stickers.py
```

详见 [表情包说明](stickers/README.md)。所有模型API共用同一套选图流程；API只收到候选描述，不接收图片像素。图片ID会在本地校验，模型不能指定任意文件或网络地址。

修改 `persona_devil.md` 可调整人格。猫娘的身份、耳朵和尾巴属于角色对白；角色设定不赋予现实操作能力，程序不执行模型生成的命令。

## 能力边界

- 目前只处理群聊文字，不支持私聊、看图、语音、联网检索或自动管理群成员。
- “记忆”是近期上下文、情绪数值和有限捉弄次数，不是长期事实记忆。
- 模型根据描述选表情，可能选得不贴切；关键词情绪规则也可能误判。
- 依赖API平台、网络及OneBot客户端，模型输出风格和延迟不能保证一致。
- 管理员角色依赖OneBot事件的 `sender.role`；客户端不提供角色时请配置 `admin_ids`。
- 支持兼容Chat Completions的文字模型。不同服务商的参数、模型ID和JSON支持有差异，错误提示以实际接口响应为准。

## 开发与验证

```sh
python -m unittest discover -s tests -v
```

测试覆盖只读API建档、保存前禁止使用、删除在用档案后停止服务、档案意外修改检测、API回复与选图、鉴权/限流错误、超时取消、空图库、GIF导入、短句拆分、管理员权限、单实例锁，以及模拟OneBot到API再到文字/GIF发送的完整流程。测试不要求付费密钥，也不会给真实QQ群发消息。

GitHub Actions配置了Windows/Linux与Python 3.11/3.12测试；本地测试通过不代表远端工作流已经通过。

## 隐私与许可证

运行数据、配置和用户素材不会加入Git；近期群聊与候选图片描述会发送到你选择的API平台，详情见 [SECURITY.md](SECURITY.md)。

代码采用 [MIT License](LICENSE)。用户导入的素材由用户自行准备，其权利归各自作者，MIT代码许可证不适用于用户图片。项目不打包QQ/OneBot客户端、登录数据或第三方表情包。

欢迎通过Issue反馈脱敏复现步骤，贡献说明见 [CONTRIBUTING.md](CONTRIBUTING.md)。
