# 聊天截图重建 / Chat Screenshot Rebuilder

`chat_screenshot_rebuilder.py` 复用截图成书的 OCR、图片排序和重复检测能力，把聊天截图整理成可复查的说话人分离记录。

## 快速使用

直接处理图片或图片目录：

```powershell
python chat_screenshot_rebuilder.py build <input> <output-dir> --recursive
```

复用已经生成的 `pages.jsonl`，不重复 OCR：

```powershell
python chat_screenshot_rebuilder.py from-pages <pages.jsonl> <output-dir>
```

可指定说话人名称：

```powershell
python chat_screenshot_rebuilder.py build <input> <output-dir> --my-label "我" --other-label "客户"
```

## 输出

- `chat.md`: 适合阅读的聊天记录。
- `chat.jsonl`: 每条消息一行，保留说话人、坐标、来源截图、置信度和复查标记。
- `review.md`: 未知说话人、缺少坐标、疑似重复等复查项。
- `pages.jsonl`: 原始 OCR 页面和文本块，便于追溯。

## 当前能力边界

- 默认按聊天截图坐标判断：左侧是“对方”，右侧是“我”。
- 时间和明确的系统通知单独保存，不归入说话人。
- 相邻截图首尾完全重叠的消息会自动去重；模糊重复只标记，不自动删除。
- 缺少 OCR 坐标时保留文字，但说话人标为“未知”。
- 群聊昵称、引用回复、转发记录、表情、语音、红包和复杂主题仍需人工复查。

## Agent 调用

MCP/HTTP 工具名为 `rebuild_chat_screenshots`。必填参数是 `input` 和 `output`；可选参数包括 `ocr_provider`、`title`、`my_label`、`other_label` 和 `speaker_mode`。
