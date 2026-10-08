# todo

已经确认当前项目的代码使用AI生成，所以很多地方是非常混乱的，并且AI创建一些莫名其妙的理论，自圆其说。

实际上设计上并不好。

## test_godot_adapter.py

文件中有3个测试用例无法通过：

1. test_compatibility_import_rejects_real_decode_error_text
2. test_import_rejects_real_decode_error_text_without_blanket_error_matching
3. test_cli_writes_artifacts_and_returns_quality_failure

全部修改，使用真实环境。

## 工作路径确认

强制所有调用都必须从项目根路径开始调用。

## 原文档记录

这与“使用框架生成游戏”是两条独立路径。若要新增或修改模型封装、Operator或 Pipeline Runner，请从[`agent_skills/develop_harness/README.md`](agent_skills/develop_harness/README.md)开始，并先运行其中定义的 CPU smoke harness，再使用模型权重或 GPU。
