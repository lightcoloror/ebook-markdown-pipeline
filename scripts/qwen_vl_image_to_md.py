from __future__ import annotations

import argparse
import os
from pathlib import Path


DEFAULT_MODEL = "Qwen/Qwen2.5-VL-3B-Instruct"
TOOL_CACHE = Path(r"D:\used-by-codex\tools")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Qwen2.5-VL on one image and write Markdown.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default=os.environ.get("QWEN_VL_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-new-tokens", type=int, default=1200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_local_cache()
    if args.dry_run:
        print(f"model={args.model}")
        print(f"input={args.input}")
        print(f"output={args.output}")
        return 0

    import torch
    from qwen_vl_utils import process_vision_info
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    image = args.input.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        args.model,
        torch_dtype=dtype,
        device_map="auto",
    )
    processor = AutoProcessor.from_pretrained(args.model)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": str(image)},
                {
                    "type": "text",
                    "text": (
                        "请识别这张信息图/图文材料，输出结构化 Markdown。"
                        "保留标题、分区、流程、表格、图例、关键数字和箭头关系。"
                        "不要编造看不清的内容；不确定处标注为[不确定]。"
                    ),
                },
            ],
        }
    ]
    prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[prompt],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    inputs = inputs.to(model.device)
    generated_ids = model.generate(**inputs, max_new_tokens=args.max_new_tokens)
    generated_trimmed = [
        output_ids[len(input_ids) :]
        for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
    ]
    text = processor.batch_decode(
        generated_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()
    output.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(str(output))
    return 0


def configure_local_cache() -> None:
    os.environ.setdefault("HOME", str(TOOL_CACHE / "vlm-home"))
    os.environ.setdefault("USERPROFILE", str(TOOL_CACHE / "vlm-home"))
    os.environ.setdefault("XDG_CACHE_HOME", str(TOOL_CACHE / "vlm-cache"))
    os.environ.setdefault("HF_HOME", str(TOOL_CACHE / "huggingface"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(TOOL_CACHE / "huggingface" / "transformers"))
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    for key in ("HOME", "USERPROFILE", "XDG_CACHE_HOME", "HF_HOME", "TRANSFORMERS_CACHE"):
        Path(os.environ[key]).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
