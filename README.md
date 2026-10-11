# Codex 550W Launcher

为 Windows 上的官方 Codex 播放一段 550W 开屏动画。启动器使用 PySide6 + Qt WebEngine 渲染本地 HTML/CSS/JavaScript，同时唤起官方客户端；动画完成、主窗口可响应后，片头淡出并切换到官方窗口。全程不修改官方安装文件。

动画基于 [dsh-550c-boot](https://github.com/yannicksong0106/dsh-550c-boot) 的 550C 原稿，保留 CRT 终端、SVG 绘制、布局和节点动画。中心标识及虚构模型名称为 **550W**，完整版最终大横牌为 `SYSTEM IS REWRITTEN`。

| Windows 包 | 播放内容 |
| --- | --- |
| **550W简洁版** | 约 4 秒标识绘制，无音频 |
| **550W完整版** | 约 16 秒完整终端与节点剧情，使用当前启动音频 |

两版支持琥珀、绿色、青色、白色，以及点击或 Esc 跳过。窗口未就绪时继续等待；失败或超时会提示并关闭启动器自己的动画。

0.3.2 保留了红色 0 的清晰轮廓与纯透明度淡出，并修正最终横牌的宽度，避免文字被裁切；原 SVG 轮廓与绘制时序保留。

解压并保留整个目录，双击 `550W简洁版.exe` / `550W完整版.exe` 或 `Run.cmd`。不要单独移动 EXE，`_internal` 资源需要一起保留。官方 Codex 需事先安装并能独立启动。`Preview.cmd` 用于预览，`Settings.cmd` 用于设置，`Create-Shortcut.cmd` 用于创建快捷方式。

源码运行：安装 Python 3.11–3.14，执行 `Install.cmd`，再执行 `Run.cmd`。构建使用 `Build.cmd`。构建会生成 `dist/550W简洁版.zip` 与 `dist/550W完整版.zip`。各版本的实际验证范围见 [验证说明](docs/VERIFICATION.md)；窗口响应检查不代表官方登录、联网或工作区已经完成，Windows 也可能限制后台聚焦。

动画中的固件、节点、证书、经纬度和会话日志均为虚构演示内容，不代表 Codex 实际执行这些操作。启动器不上传遥测；本地配置和日志可能包含程序路径，详情见 [PRIVACY.md](PRIVACY.md)。

项目署名：**dhdhd723**。原动画与 HTML 原稿：**[Voidpoket](https://github.com/Voidpoket)**；上游插件工程、提取与增强：**[Ziyang Song](https://github.com/yannicksong0106)**。

新增启动器代码、脚本和原创新文档按 [LICENSE](LICENSE) 所述范围采用 MIT。该授权不覆盖原动画、550W 改编素材、音频或打包依赖。原动画和当前用户音频的公开再发布许可尚未确认；上游工程的 MIT 通知和其他依赖许可分别保留。详见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) 与 [授权说明](docs/LICENSING.md)。保留署名不能替代授权。

本项目为独立启动器，与 OpenAI 没有官方关联。

下载两个 Windows 目录包：[Releases](https://github.com/dhdhd723/550W-for-Codex-on-Windows/releases)。GitHub 会规范化中文附件名，因此下载附件采用 `550W-Brief.zip`（简洁版）和 `550W-Full.zip`（完整版）；解压后的文件夹和 EXE 仍分别叫 `550W简洁版` 与 `550W完整版`，本机构建的 ZIP 也保留中文名。完整包需一起保留 `_internal`，简洁包不包含 MP3。两版的偏好分开保存。
