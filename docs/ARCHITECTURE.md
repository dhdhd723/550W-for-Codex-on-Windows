# 实现架构与官方应用边界

本启动器运行自己的 Python/Qt 进程与 WebEngine 渲染进程，官方桌面应用保留独立进程、安装文件、签名与数据。唯一交接是 Windows 已注册的启动入口，以及对目标窗口的只读识别、响应检查、显示/恢复和前台请求。

## 代码与资源

| 文件 | 责任 |
| --- | --- |
| `main.py` | 参数、配置覆盖、轮转日志、诊断入口、顶层错误处理 |
| `launcher/config.py` | 启动器自己的 LocalAppData 配置、严格校验、原子保存 |
| `launcher/windows.py` | 当前用户应用包发现、AUMID 激活、PE GUI 检查、Win32 主窗口判定、聚焦 |
| `launcher/state.py` | 动画完成与窗口响应的双门条件，只执行一次退出 |
| `launcher/app.py` | Qt 窗口、后台发现、消息桥、淡出、错误回退、单实例与设置 |
| `scripts/extract-animation.mjs` | 原稿定点提取与品牌改写，生成本地动画资源 |
| `web/source/550C-source.html` | 上游原稿归档；不在官方应用内加载 |
| `web/source/enhance-original.js` | 上游增强层归档，用于对照原配色与内容增强 |
| `web/animation.css`、`animation.js`、`index.html` | 从原稿派生的布局、笔画、阶段和动画主体 |
| `web/launcher.css`、`launcher.js`、`palettes.css` | 独立启动/等待/跳过桥接、退出状态与配色 |
| `web/audio/boot.mp3` | 用户提供的最新 MP3，本地单次播放；来源/公开分发许可未独立核验 |

动画原稿可脱离 DSH 播放。DSH 的 Cordis profile 补丁、宿主 `index-inject`、React 设置行、桌面标题栏注入和更新接口不适用于此进程，不移植到官方 Codex。无需推断官方客户端框架或内部插件机制。

0.2.4 的动画内容层统一使用虚构模型名 550W，包括日志 `[550W]`、终端 `550W CORE TERMINAL`、`550W-ROOT` / `550W-CTRL` / `550W-QUANTUM-0` 和代码流 `CA_550W` 等；最终大横牌使用原式 `SYSTEM IS REWRITTEN`。这些名称仅属于本地开屏剧情。启动器的真实目标仍是官方 Codex，配置字段、应用发现、AUMID 激活与窗口识别不随动画文案改名。

## 启动与就绪判定

1. `main.py` 读取默认配置/保存配置，再应用显式命令行参数。
2. Qt `QLockFile` 抢占当前用户的启动器锁；重复启动通过 `QLocalSocket` 请求既有启动器显示，再退出。预览独立于正式启动锁。
3. `Splash` 在鼠标所在屏幕（或主屏幕）先显示原稿底色窗口，接着加载本地 HTML。后台线程并行发现/激活官方应用。
4. 默认发现通过 `Get-StartApps`、`Get-AppxPackage` 与应用清单读取当前用户注册入口；仅接受匹配 OpenAI/Codex 包和主 GUI 的记录。实际安装目录仅用于识别/读取 PE 信息，不写入。
5. 已有合格主窗口则复用；否则调用 Windows `explorer.exe shell:AppsFolder\<AUMID>`。手动 EXE 路径需存在且 PE 子系统为 GUI；不接受 CLI。手动目标表示用户自行选择的 GUI，不是额外的发行者签名认证。
6. `EnumWindows` 选取可见、启用、未被 DWM 隐藏、非拥有者弹窗且尺寸合格的目标主窗口；按已知主程序路径或包族 + 主程序名匹配身份。最小化窗口允许作为恢复目标。
7. 仅向已识别窗口发送有 100 ms 上限的 `WM_NULL`，并检查挂起状态。后台要求同一窗口约 350 ms 稳定存在，以 200 ms 间隔观察。
8. `Gate` 在“动画完成/被跳过”与“目标窗口稳定响应”都为真时开始退出。点击/Esc 仅解除动画门，官方窗口未就绪仍等待。
9. 先让页面内容在 200 ms 内淡入原底色，再让原生窗口透明度在 420 ms 内淡出；退出时重新识别目标并请求显示/恢复/前台。

`WM_NULL`、可见和稳定窗口都是操作系统层的代理判定，**不是官方登录、网络、工作区或 Codex agent readiness API**。没有已验证的内部就绪协议，也没有强制进入 Codex 模式的已验证公开入口。部分官方版本显示名/标题为 ChatGPT，识别不依赖标题是否出现 Codex。

## JavaScript 与 Qt 协调

独立页面通过 `console.info('LAUNCHER:' + JSON.stringify(...))` 发出 `loaded`、`animation_done`、`skip`、错误等事件。自定义 `QWebEnginePage.javaScriptConsoleMessage` 只解释该专用前缀下的 JSON。Qt 通过 `runJavaScript` 调用本页面固定 `window.launcher` 方法；字符串参数使用 JSON 编码。

没有使用 WebChannel 暴露文件系统或操作系统调用给页面。页面为 off-the-record profile；请求拦截只允许 `file`、`data`、`qrc`、`about`，关闭远程资源访问/弹窗，拒绝远程导航。页面不连接官方应用的 DOM、认证、网络或调试协议。

当前版本沿用 0.2.3 引入的音频流程：在动画 `start` 调用前请求播放最新 MP3，不等待 logo 的 `finished` 回调，保持原速，禁止循环。音频的完成 Promise 在起播时创建；原最后阶段在显示完成牌前等待它结束，`ended` 后显示最终大横牌 `SYSTEM IS REWRITTEN` 并复位声音。音频失败或绝对截止超时释放等待；截止从起播计算，仍在 Qt 的 22 秒动画看门狗范围内。原生停声先取消 show，再释放完成 Promise；点击/Esc 在同一任务内停声并取消，await 返回后重新检查取消状态，避免恢复完成牌。原四步倒计时由每步 160 ms 放慢至 800 ms，其他阶段内部节奏保持；在完成牌前等待整段声音自然结束，保留原完成牌驻留；完整模式等待官方窗口时不播声音。简易模式没有完成牌，先进入等待时剩余音频可继续播完，退出时淡出。

实现使用网页 `HTMLAudioElement`，没有 Qt Multimedia 播放器。Qt 显式允许本地页面自动播放；`Splash.stop_audio()` 在跳过、渲染故障、启动失败/超时、关闭和交接完成时先把该页面原生静音，再在 JavaScript 仍可用时调用 `stopAudio()` 复位。这样页面脚本异常不会留下自己的开屏声音；不操作官方应用的音频或系统全局静音。

## 异常与清理

- 主进程等待官方窗口的硬超时来自 `timeout_seconds`（20–300 秒），默认 90 秒。
- 页面在 10 秒内未初始化时，将动画视为完成并继续等待官方窗口；简易/完整动画另有 8/22 秒脚本看门狗。
- 脚本错误、加载失败或 WebEngine 渲染进程终止走动画回退，不结束官方应用。
- 启动失败/超时关闭自己的片头，提示窗口保留日志路径并在 8 秒后关闭。
- Ctrl+Q 关闭启动器；不会关闭已经唤起的官方应用。正常完成或错误结束时停止后台探测、释放本机服务与锁。
- 无强制前台绕过：只调用 `ShowWindowAsync`、`SetForegroundWindow`，再读实际前台结果；Windows 拒绝时提示用户点击任务栏。

`QLockFile` 利用 PID 存活信息恢复崩溃遗留锁；Qt 异常退出也不会更改官方程序文件。代码防护存在并不代表每种崩溃方式都已实测，覆盖以 `VERIFICATION.md` 为准。

## 屏幕、DPI 与构建

Qt 6 使用 `PassThrough` 缩放取整与屏幕逻辑尺寸；动画窗口置于鼠标所在屏幕。屏幕被移除时回到当前主屏幕。对多显示器/不同硬件 DPI 的实际表现必须按测试报告的范围解读。

`build.ps1` 用 PyInstaller 的 Qt WebEngine hooks 打包所需 helper、DLL、资源包与语言包，采用 `onedir` 保持依赖目录可读取/替换，构建后检查关键资源。WebEngine 在冷启动时需要载入较大运行时；先出现底色与 HTML 动画首帧并不是相同时刻。未采用对官方安装目录、资源、应用签名或启动代码的任何注入/补丁。

0.3.0 使用 `_internal/edition.json` 固定目录包的模式和声音开关，配置与锁保存在各自的数据目录。简洁版不给音频对象设置 src，也不等待音频；包内没有 MP3。
