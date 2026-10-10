# 帧间工作台协作

修改前阅读ANIMATION_WORKBENCH_DESIGN.md、docs/API_CONTRACT.md、docs/VALIDATION.md。
当前用户已确认完整方案并授权实现，按文档落实，不重复要求确认普通实现选择。
UI和Codex使用同一HTTP接口；不能绕过修订检查或直接写用户SQLite。
保护data与原图，测试用独立AW_DATA_DIR；原图只读，修改生成派生素材。
前端React/TypeScript/Canvas，后端FastAPI/Pillow/SQLite。保持localhost运行。
验证 .venv/Scripts/python -m pytest tests -q 和 frontend/npm run build；实际行为变化增加必要的测试。
报告已验证范围与未验证项；动画动作合理性由用户预览验收。
