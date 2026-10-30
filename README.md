# 游戏资产工作台

供人类和外部 Agent 协作的本地 2D 动画工作台。用户确认要求、检查候选并微调像素；Agent 从 HTTP 接口读取任务并回传结果。项目从零建立，不依赖旧工程。

## 启动

运行根目录的 `start.cmd`，或在 PowerShell 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

首次启动会自动选择兼容的 Windows Python 3.11+，创建项目内的 `.venv`，并安装 `backend/requirements.txt`。首次安装需要网络，完成后固定使用 `.venv/Scripts/python.exe`，无需激活 Anaconda，也不会向全局 Python 安装包。MSYS2 Python 会被跳过；若没有兼容解释器，启动器会给出明确提示。可以用 `-PythonExecutable '完整的python.exe路径'` 指定首次创建环境的解释器。

打开 http://127.0.0.1:18765 。已有且未过期的前端构建会直接复用；缺少构建或源码更新时才需要 Node.js 和 npm。前端已在 Node.js 24 上验证（边界测试使用其内置 TypeScript 支持）。终端中 Ctrl+C 停止服务。

可用参数：`-Port 18766` 更换端口，`-Rebuild` 强制构建前端，`-SkipBuild` 使用现有构建，`-SetupOnly` 准备依赖后退出。`start.cmd` 会把这些参数传给 PowerShell。第二次启动在依赖完整、清单未变时不会重新联网安装。

`.venv` 仅包含本地运行环境，不应复制到其他电脑或提交源码。如果移动项目后环境失效，重命名 `.venv` 再启动即可重建，项目素材保存在单独的 `data/`。

默认数据存放在本项目 `data/`，停止服务后备份整个目录。设置环境变量 `WORKBENCH_DATA_DIR` 可改用其他目录。不要只复制数据库而漏掉图片。浏览器刷新与服务重启不会主动清除数据。

## 使用流程

新建项目和角色后，创建动作并设置画布、pivot、身体标尺、帧数与时长。可先加载明确标记的程序测试素材，验证编辑操作，再导入自己的参考和生成结果。

确认规格后创建任务。外部 Agent 读取任务包，上传 PNG 并提交候选版本。用户比较、采用和标记问题；少量问题可直接用像素工具修补。验收与采用是两件事，只有确认接受的版本才用于正式导出。

角色和特效分别计时。固定帧数导出遇到中途特效变化时需要明确接受采样损失；保留时间变化的导出会增加合成帧。分层导出则保留独立时序，游戏需要按 manifest 播放。

程序测试素材不是 AI 生成结果。v0.1 不连接付费生成服务或视觉质检模型，也不读取根目录的密钥。上下文由结构化规格组装，后续可加入模型建议，但已确认的任务不会被静默改写。

## Agent 接入

首次使用可打开 [交互式协作说明](docs/agent-collaboration/interactive.html)，或在工作台中点击“Agent 协作说明”。网页提供可点击流程图、交接文本生成器和版本冲突演练，可直接在浏览器打开，无需联网。

2026-10-30 已完成一次真实 PixelLab 生成与首帧限域返工，由 Codex 获授权代演用户验收。本机记录位于 `outputs/agent-trial-20261030/`，保留动画对照页、实际流程图、验收记录与正式导出包；生成素材和本地任务证据不随源码仓库发布。

当前采用手动交接：创建任务后，将任务 ID 和交接说明发给同机 Agent；Agent 提交候选后，先处理页面上未保存的修改，再点击“刷新 / 重连”，到“版本”页检查。创建任务不会自动唤醒 Agent，提交成功也不会自动采用或验收。

服务运行时可访问 `/docs` 查看后端 OpenAPI。接口统一以 `/api` 开头，完整形状见 `docs/api-contract.md`。`scripts/agent_client.py` 是一个无需第三方 Python 依赖的命令行入口：

```powershell
.\.venv\Scripts\python.exe scripts/agent_client.py health
.\.venv\Scripts\python.exe scripts/agent_client.py bundle TASK_ID --output runtime/task.json --download-images
.\.venv\Scripts\python.exe scripts/agent_client.py upload path/to/frame.png
.\.venv\Scripts\python.exe scripts/agent_client.py submit TASK_ID path/to/result.json
```

结果必须绑定任务基础版本，使用上传后返回的 image_id。提交只创建候选，不自动覆盖用户当前版本。局部修订必须遵守任务允许的帧和矩形区域。下载的任务包可能含本地图片 URL，远程 Agent 需要可达的传输方式；本项目默认不向外网开放。

## 开发与验收

后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18765
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe scripts/verify_workbench.py
```

前端另开终端：

```powershell
npm.cmd --prefix frontend run dev
npm.cmd --prefix frontend run build
node --experimental-strip-types --test frontend/src/geometry.test.ts
```

开发页面默认 http://127.0.0.1:5173 ，将 `/api` 代理到 18765。最终构建由后端同源托管。

设计基线见 `docs/design.md`，接口见 `docs/api-contract.md`，本轮实际完成情况及限制见 `docs/verification.md`。以验收记录为准，不把待实现条目当成已交付功能。
