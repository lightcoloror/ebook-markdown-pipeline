from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Heavy DeepSeek-OCR Transformers runner. Imported only by the wrapper subprocess.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--base-size", type=int, default=1024)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--attention", choices=["auto", "flash_attention_2", "eager", "sdpa"], default="auto")
    parser.add_argument("--no-crop", action="store_true")
    parser.add_argument("--no-test-compress", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = run_inference(args)
    if result is not None:
        print(str(result))
    return 0


def run_inference(args: argparse.Namespace):
    import torch
    from transformers import AutoModel, AutoTokenizer

    use_cuda = args.device == "cuda" or (args.device == "auto" and torch.cuda.is_available())
    dtype = torch.bfloat16 if use_cuda else torch.float32
    attention = args.attention
    if attention == "auto":
        attention = "flash_attention_2" if use_cuda else "eager"
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        args.model,
        trust_remote_code=True,
        use_safetensors=True,
        _attn_implementation=attention,
    ).eval()
    if use_cuda:
        model = model.cuda().to(dtype)
    else:
        model = model.to(dtype)
    return model.infer(
        tokenizer,
        prompt=args.prompt,
        image_file=str(args.input),
        output_path=str(args.output_dir),
        base_size=args.base_size,
        image_size=args.image_size,
        crop_mode=not args.no_crop,
        save_results=True,
        test_compress=not args.no_test_compress,
    )


if __name__ == "__main__":
    raise SystemExit(main())
