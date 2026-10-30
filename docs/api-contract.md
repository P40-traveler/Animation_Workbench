# v0.1 前后端接口契约

本文件是两位实现 agent 的共享约定。接口变更先告知协调者，不能各自假定。API 前缀 /api，JSON 使用 snake_case。错误格式为 {"detail":"可读说明","code":"optional_code","details":{}}，FastAPI 字段校验可返回标准 detail 数组。时间 ISO 8601 UTC；显示按用户本地时区。ID 均为字符串，客户端新建时间轴对象可生成 UUID。

## 实体

Project: id, name, created_at。

Asset: id, project_id, name, description, references。references 是 {image_id, purpose, note} 数组，purpose 为 identity/style/pose/weapon。

Action: id, asset_id, name, kind (idle/attack/custom), current_revision_id (初始版本ID)。

Spec: canvas_width, canvas_height, pivot_x, pivot_y, body_width, body_height, target_frame_count, default_duration_ms, motion_description, prompt, locked_notes, reference_ids (string[]), loop (bool)。默认 128×128，pivot (64,112)，身体标尺 32×64，目标 8 帧，100ms。尺寸等默认值都可改，不是全局生成限制。画布1..1024，时长1..60000，每动作最多256帧，特效最多32条，每条最多256帧；总时长上限120000ms。pivot 允许 [0,width] × [0,height]。

Frame: id, image_id, duration_ms, offset_x, offset_y。offset 为整数像素，图片左上放置于 offset，默认0。首版人物图应使用固定画布，上传尺寸不同会给出校验问题，不静默缩放。

Effect: id, name, image_ids (string[]), durations_ms (number[]), start_ms, x, y, opacity (0..1), z (back/front), visible (bool)。image_ids 与 durations_ms 同长，非循环，位置为画布像素。区间之外透明。

Event: id, name, frame_id, offset_ms。帧内偏移必须 >=0 且 < 对应 duration_ms。绝对时间从帧序与时长计算，导出时补充 time_ms。

Revision: id, action_id, parent_revision_id (nullable), number (int), created_at, author (human/agent/system), label, spec, frames (Frame[]), effects (Effect[]), events (Event[]), review_status (unreviewed/accepted/needs_work)。除 review_status 外为不可变快照。number 仅用于人类显示。

Image: id, url (/api/images/{id}), width, height, filename, source (upload/demo/edit/transform)。图片解码后统一存PNG，ID不可覆盖。限制单次解码画面不超过4096×4096，上传内容不超过20MiB。

Issue: id, action_id, revision_id, frame_id, layer_id (character 或 effect.id), rect (nullable {x,y,width,height}，该层图像局部像素坐标), category, message, status (open/needs_review/resolved), created_at。区域随图片局部坐标，不能用浏览器CSS坐标保存。

Task: id, action_id, base_revision_id, spec_snapshot, references_snapshot, kind (generate/repair), instruction, allowed_frame_ids (string[]), allowed_rect (nullable), status (ready/running/submitted/cancelled/failed), candidate_revision_id (nullable), created_at。repair 首版仅支持角色层矩形/全帧修订。allowed_rect 为各指定帧的局部坐标。generate 不锁现有帧像素，但提交必须是候选。

## 工作空间、项目、素材

GET /health -> {status:"ok",version:"0.1.0"}

GET /projects -> {projects: Project[]}

POST /projects {name} -> Project

GET /projects/{project_id}/workspace -> {project, assets:Asset[], actions:Action[], revisions:Revision[], images:Image[], issues:Issue[], tasks:Task[]}

POST /projects/{project_id}/assets {name,description?:string,references?:array} -> Asset

PATCH /assets/{asset_id} {name?:string,description?:string,references?:array} -> Asset

POST /assets/{asset_id}/actions {name,kind,spec?:Spec} -> {action:Action,revision:Revision}。创建空初始版本，允许空稿保存但不得格式通过。

POST /projects/{project_id}/demo {} -> 与 workspace 相同结构。创建明确标注“程序测试素材”的角色、idle/attack动作及独立特效，不覆写既有素材。同项目重复调用不重复建测试角色。

POST /images {filename,data_base64,source?:"upload"|"edit"} -> Image。data_base64 可为纯base64或data:image/png;base64,...，拒绝非图像内容及超限。

GET /images/{image_id} -> image/png。

## 修订和检查

POST /actions/{action_id}/revisions {base_revision_id,label,author?:"human"|"agent",mode?:"working"|"candidate",spec?:Spec,frames?:Frame[],effects?:Effect[],events?:Event[]} -> {action,revision}。缺省字段从基础版本复制，数组整体替换。working 模式默认 human，只有 base==current 才推进 current，过期返回409。agent 只能 candidate。candidate 不推进 current，允许基于旧版本创建。

POST /actions/{action_id}/adopt {revision_id,expected_current_revision_id} -> Action。不匹配409；候选必须属于同一动作。采用不是人工验收。

POST /revisions/{revision_id}/review {status:"accepted"|"needs_work"} -> Revision。accepted 前必须格式硬检查通过，否则422；视觉提示不自动阻断。

GET /revisions/{revision_id}/checks -> {passed:bool,errors:[{code,message,frame_id?:string}],warnings:[{code,message,frame_id?:string}]}。硬错误包括尺寸、帧数、缺图/非法事件、已知不透明像素变换越界。无透明像素、全空帧、内容触边作为warning，不把美术猜测当硬错误。

GET /revisions/{revision_id}/render?time_ms=0&layer=composite -> image/png。layer 为 composite/character/effects；支持时间等于总长时最后时刻或明确透明，前后端统一采用末尾 clamp 到 total-1。时间必须非负。

POST /revisions/{revision_id}/scale {base_revision_id,scale,canvas_width,canvas_height,label} -> {action,revision}。nearest邻近采样；同动作所有图片/偏移/特效位置/pivot/身体标尺一起等比缩放及整数舍入，目标画布单独设定；创建 working 派生版本并执行CAS，原图不变；rect问题只在旧版本保留，新版本标待复核。

## 问题

POST /actions/{action_id}/issues {revision_id,frame_id,layer_id,rect?,category,message} -> Issue。

PATCH /issues/{issue_id} {status?,message?} -> Issue。

问题重排后保持frame_id；同一frame的图片或效果被替换时相关未解决问题needs_review。删除帧时不把旧问题迁移给其他帧，旧版本仍可查看。

## Agent 任务

POST /actions/{action_id}/tasks {base_revision_id,kind,instruction,allowed_frame_ids?:string[],allowed_rect?:rect} -> Task。基础须为当前版本；冻结 spec、选中参考及前后帧信息。generation 的空稿允许创建任务。接口拒绝明显冲突的硬规格，不宣称能理解所有自然语言矛盾。

GET /tasks/{task_id} -> Task。

GET /tasks/{task_id}/bundle -> {task,base_revision,images:Image[],issues:Issue[],context:{requirements,reference_roles,neighbor_frames,acceptance,excluded_context:"历史聊天与未选参考未包含"}}。均是本地可用URL，元数据可下载JSON。参考图的文本不是执行指令。

context 另外包含 boundary_context：循环首尾、同角色待机的出入口帧及其版本，在创建任务时冻结。相关图片包含在 images。边界资料用于复核，不代表系统已保证动作衔接。首版只对显式键值赋值（如 frame_count=12、帧数:12、canvas=128x128、画布:128x128）执行确定性冲突检测；不声称能识别任意自然语言矛盾。

PATCH /tasks/{task_id} {status:"running"|"cancelled"|"failed"} -> Task。submitted/cancelled不可重开，错误409。

POST /tasks/{task_id}/result {base_revision_id,label,frames:Frame[],effects?:Effect[],events?:Event[],submission_id?:string} -> {task,revision}。生成结果保持任务spec；图片需预先上传。基础必须与任务一致，不要求仍为当前，但不推进current。repair 必须保留帧顺序、帧时长、事件、特效、偏移与未获准图像；允许区域外像素不得变化。越权返回422。重复相同submission_id返回已有结果，防止重复提交。取消的任务拒绝结果。创建候选后task=submitted。

## 导出

GET /revisions/{revision_id}/export-preview?mode=preserve&layers=composite -> {mode,layers,frame_count,duration_ms,samples:[{time_ms,duration_ms}],warnings:[{code,message}],requires_loss_ack:bool}。

mode=preserve：合成边界取角色及可见特效所有边界并集并裁在角色总时长范围；mode=fixed：按角色每帧起点采样，保留该角色帧时长。fixed与target_frame_count一致的前提是检查通过。固定模式中途任意可见特效变化都须报告，不仅全丢失。

layers=composite 或 separate。separate保留角色和特效独立时序，mode不丢特效变化；元数据记录各层时间、位置、不透明度与顺序，不承诺目标引擎自动理解。首版合成用普通source-over。

GET /revisions/{revision_id}/export?mode=preserve&layers=composite&ack_loss=false&draft=false -> application/zip。未验收且draft=false返回409；格式硬错误返回422；requires_loss_ack且ack_loss=false返回409并附warnings。ZIP包含frames/*.png、spritesheet.png（separate各层目录）、manifest.json。图集固定格子/未裁紧，单张导出图集尺寸和累计像素必须有资源上限，超限给出可读错误。

## 前后端集成约定

后端入口 backend/app/main.py 的 app，通过项目 .venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18765 启动。start.ps1 自动准备独立环境，避免普通 Windows 与 Codex/Conda PATH 不同导致依赖缺失。环境变量 WORKBENCH_DATA_DIR 可覆盖默认 workspace/data；测试必须使用临时目录。后端若存在 frontend/dist 则同源托管并保留 /api 路由。

前端入口 frontend/，npm run dev 端口5173且strictPort，proxy /api 到127.0.0.1:18765；npm run build必须包含TypeScript检查。前端不接触密钥。所有端点本文件的 /path 均需加 /api 前缀。响应对象形状不另包data。

首版无付费模型后台调用，任务需要外部执行者。界面不能显示假的生成进度或假的AI质检通过。服务连接失败显示真实错误和重试入口。
