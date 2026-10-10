# 数据与接口契约 v1

实施依据：TOOLS/ANIMATION_WORKBENCH_DESIGN.md v1.0。先确定契约再实现。

HTTP 根地址 http://127.0.0.1:18765/api/v1。UI 与 Codex 使用同一接口。写请求携带 X-Actor（默认 user）及 expected_revision。过期返回409且不覆盖。对象 ID 使用 UUID；F001 等仅为显示编号。源图片只读，修改生成派生 asset。

Project 含 id/name；Character 含 project_id/name；Action 含 character_id/name；Version 含 action_id/name/revision/state。state 是经过校验的编辑文档：canvas(width,height,pivot_x,pivot_y,ground_y)、body(width,height,reference_rect)、frames(id,duration_ms,status,events,points)、tracks(id,name,kind,visible,locked,export,start_ms,end_behavior,transform,exposures)、issues(id,frame_id,track_id,rect,tag,note,status)、prompt(identity,motion,frame_notes,changes,reference_ids,final_text)、status。

Track exposures 含 id、asset_id、duration_ms、可选transform。transform 包含 dx/dy（整数）、anchor_x/anchor_y（源像素）、scale、rotation（顺时针度数）、flip_x/flip_y、opacity。当前曝光覆盖轨道变换，未设置字段继承轨道值。源锚点→翻转/统一缩放/旋转→canvas pivot+偏移。普通alpha合成，轨道按数组从后向前叠加。

时间为整数毫秒，曝光左闭右开。frames 定义动作时长；各轨道独立曝光，start_ms 后依次播放；结束可hide/hold/loop。合成导出采用各轨道与动作帧边界并集，循环曝光重复边界也参与。固定帧数模式按均匀时间采样，返回可能遗漏变化的说明。

核心路由：

- GET /health、GET /catalog；POST /projects、/characters、/actions：创建目录对象。
- POST /actions/{id}/versions：建立空版本；GET /versions/{id}；PUT /versions/{id}：带revision完整保存；POST /versions/{id}/clone、/undo、/redo。
- POST /assets：multipart project_id+file；GET /assets?project_id=…；GET /assets/{id}/image；POST /assets/{id}/slice：rects或规则grid，返回派生素材及边界警告。
- POST /versions/{id}/pixels：expected_revision、track_id、exposure_id、patches(x,y,rgba)；建立当前曝光副本且加入可撤销历史。
- GET /versions/{id}/render?time_ms=…；GET /versions/{id}/onion；GET /versions/{id}/contact-sheet；GET /versions/{id}/region?time_ms=&x=&y=&width=&height=；GET /versions/{id}/validate。
- POST /generation-requests：不可变方案快照；GET /generation-requests；POST /generation-requests/{id}/claim、/complete、/status。返回素材必须属于同项目，重复complete幂等，快照包含reference文件与最终提示词。
- POST /versions/{id}/convert：expected_revision、track_ids、reference_rect、target_width/height、method、colors、dither；任务输出新素材与统一缩放参数，提交时再次检查revision。
- POST /versions/{id}/export：expected_revision、mode(union/fixed)、count、allow_clip、layers；GET /jobs、/jobs/{id}；POST /jobs/{id}/cancel。导出zip含PNG、图集、manifest、检查报告；GET /jobs/{id}/download。
- GET /versions/{id}/history：操作来源与修订。
- POST /backup：数据库与源/派生/导出文件一起打包；GET /backups/{id}/download。

错误返回detail；服务绑定localhost，拒绝不可信Origin，文件路由仅使用服务生成的ID。每个任务保存进度、状态和错误；重启把running/queued转为interrupted。数据目录可由AW_DATA_DIR设置，测试独立目录；导出不写Unity。

撤销/重做也要求当前revision，恢复文档引用不会覆盖旧asset。版本复制保留帧ID但批注归属于新版本并标为待复查。前端每次保存前发送预期revision，冲突后保留本地编辑并允许另存版本。新增或更新项目数据写入操作日志。
