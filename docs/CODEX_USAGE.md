# Codex 协作操作

服务：http://127.0.0.1:18765；所有业务操作通过 /api/v1。写请求设置 X-Actor: codex。
先 GET /catalog 定位版本，再 GET /versions/{id}，读取当前 revision；保存使用 PUT 并携带 expected_revision。
不要直接修改 SQLite 或源素材。遇到409读取新版本并协调修改，不盲目重试覆盖。

## 生成与回传

1. GET /generation-requests 获取 pending 请求或指定请求 ID。
2. POST /generation-requests/{id}/claim，使用 X-Actor: codex。
3. snapshot.prompt.final_text 为实际提示词；snapshot.prompt.reference_ids 通过 GET /assets/{id}/image 获取参考图。快照不随UI后续修改变化。
4. 使用聊天内置图像工具生成；保存结果后通过 POST /assets multipart 上传，字段 project_id 和 file。
5. POST /generation-requests/{id}/complete，JSON {asset_ids:[...],note:"实际生成与未达标之处"}。重复相同回传幂等。
6. 回传不自动替换用户当前图层。用户可在生成记录中加入图层，或明确要求Codex替换指定版本。

## 视觉检查

GET /versions/{id}/render?time_ms=300 获取指定时刻合成 PNG。
GET /versions/{id}/onion?time_ms=300&before=1&after=1&opacity=0.25。
GET /versions/{id}/contact-sheet 联系表；GET /versions/{id}/region?time_ms=300&x=0&y=0&width=64&height=64 获取问题区域。
GET /versions/{id}/validate 提供格式、越界、参考点位移等；不能代替视觉检查。

## 像素与导出

POST /versions/{id}/pixels 使用 track_id、exposure_id、expected_revision、patches:[{x,y,rgba:[r,g,b,a]}]，默认建立当前曝光副本。
POST /versions/{id}/export 提交 expected_revision、mode:"union"或"fixed"、count、layers、allow_clip。
GET /jobs/{id} 读取进度；完成后的 result.download_url 下载 ZIP。manifest记录帧时长、统一pivot、图层时序和事件。

## 数据界限

canvas 和批注坐标左上原点、y向下；图层anchor为源素材坐标，dx/dy相对动作pivot。
frames 是动作主时序，tracks.exposures 是各层自己的时序。状态修改需要一次保存完整state，服务会验证ID与项目引用。
撤销/重做需要最新revision。复制版本保留frame ID但问题待复查。以实际版本ID、revision和帧ID报告验证证据。
