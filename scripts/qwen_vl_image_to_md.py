from __future__ import annotations

import argparse
import os
from pathlib import Path

from document_vlm_artifact_utils import write_document_vlm_result


DEFAULT_MODEL = "Qwen/Qwen2.5-VL-3B-Instruct"
TOOL_CACHE = Path(
    os.environ.get(
        "EBOOK_CONVERTER_TOOL_CACHE",
        Path.home() / ".cache" / "ebook-markdown-pipeline",
    )
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Qwen2.5-VL on one image and write Markdown.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default=os.environ.get("QWEN_VL_MODEL", DEFAULT_MODEL))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=1200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    image = args.input.resolve()
    output = args.output.resolve()
    raw_dir = (args.output_dir or output.parent / "qwen_vl_raw").resolve()

    configure_local_cache(create_dirs=not args.dry_run)
    if args.dry_run:
        print(f"model={args.model}")
        print(f"input={image}")
        print(f"output={output}")
        print(f"document_vlm_result={raw_dir / 'document-vlm-result.json'}")
        return 0

    import torch
    from qwen_vl_utils import process_vision_info
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    output.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

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
    write_qwen_vl_sidecar(raw_dir, image, output, text, model=args.model, max_new_tokens=args.max_new_tokens)
    print(str(output))
    return 0


def write_qwen_vl_sidecar(raw_dir: Path, source: Path, output: Path, markdown: str, *, model: str, max_new_tokens: int) -> Path:
    return write_document_vlm_result(
        raw_dir / "document-vlm-result.json",
        backend="qwen_vl",
        source=source,
        markdown_path=output,
        markdown=markdown,
        mode="qwen2.5-vl",
        raw_dir=raw_dir,
        command=["qwen_vl_image_to_md", "--model", str(model), "--max-new-tokens", str(max_new_tokens)],
        status="review",
    )


def configure_local_cache(*, create_dirs: bool = True) -> None:
    os.environ.setdefault("HOME", str(TOOL_CACHE / "vlm-home"))
    os.environ.setdefault("USERPROFILE", str(TOOL_CACHE / "vlm-home"))
    os.environ.setdefault("XDG_CACHE_HOME", str(TOOL_CACHE / "vlm-cache"))
    os.environ.setdefault("HF_HOME", str(TOOL_CACHE / "huggingface"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(TOOL_CACHE / "huggingface" / "transformers"))
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if create_dirs:
        for key in ("HOME", "USERPROFILE", "XDG_CACHE_HOME", "HF_HOME", "TRANSFORMERS_CACHE"):
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
