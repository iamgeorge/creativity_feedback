import argparse
import os
from pathlib import Path

from PIL import Image
import torch
from transformers import AutoImageProcessor, AutoModelForImageClassification


def make_random_image(path: Path, size: int) -> None:
    data = os.urandom(size * size * 3)
    image = Image.frombytes("RGB", (size, size), data)
    image.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score an image with OCSAI-D Large.")
    parser.add_argument(
        "--model-dir",
        default="ocsai-d-large",
        help="Path to the local OCSAI-D model directory.",
    )
    parser.add_argument(
        "--image",
        default="test_image.png",
        help="Path to the image file to score.",
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="Generate a random image at --image before scoring.",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=224,
        help="Size (pixels) for the generated random image.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Force device (e.g., cpu or cuda). Defaults to auto-detect.",
    )
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    img_path = Path(args.image)

    if args.random:
        make_random_image(img_path, args.size)

    if not img_path.exists():
        raise SystemExit(f"Image not found: {img_path}")

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")

    processor = AutoImageProcessor.from_pretrained(model_dir)
    model = AutoModelForImageClassification.from_pretrained(model_dir).to(device)
    model.eval()

    image = Image.open(img_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt").to(device)

    with torch.no_grad():
        score = model(**inputs).logits.squeeze().item()

    print(f"Image: {img_path}")
    print(f"Device: {device}")
    print(f"Creativity score: {score}")


if __name__ == "__main__":
    main()
