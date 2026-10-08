"""
DepthAnythingModel — depth estimation wrapper producing model-native relative depth.

Reference: https://huggingface.co/docs/transformers/model_doc/depth_anything

Given an RGB PIL image, `infer()` returns an HxW float32 numpy array at the
original image resolution. Values are raw relative-depth predictions and are
not normalized to a fixed range.

Usage:
    from models.tools.image_matting.depth_anything_model import DepthAnythingModel
    model = DepthAnythingModel(model_path="LiheYoung/depth-anything-small-hf")
    depth = model.infer(image)
"""

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from models.tools.base import BaseToolModel


class DepthAnythingModel(BaseToolModel):
    """Thin wrapper around HuggingFace `AutoModelForDepthEstimation`."""

    def _load(self) -> None:
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        # `local_files_only=True`：本仓库不下载模型权重。`model_path` 必须是
        # 一个已存在的本地目录，指向预置的权重。
        self.processor = AutoImageProcessor.from_pretrained(
            self.model_path, local_files_only=True
        )
        self.model = (
            AutoModelForDepthEstimation.from_pretrained(
                self.model_path, local_files_only=True
            )
            .to(self.device)
            .eval()
        )

    @torch.no_grad()
    def infer(self, image: Image.Image, **kwargs) -> np.ndarray:
        """
        Run depth prediction.

        Args:
            image: RGB PIL image.

        Returns:
            HxW float32 numpy array at the original image resolution. Values
            are model-native relative depth and are not normalized.
        """
        self._ensure_loaded()
        img = np.array(image.convert("RGB"))
        h, w = img.shape[:2]
        inputs = {
            k: v.to(self.device)
            for k, v in self.processor(images=img, return_tensors="pt").items()
        }
        depth = self.model(**inputs).predicted_depth
        depth = F.interpolate(
            depth.unsqueeze(1), size=(h, w), mode="bicubic", align_corners=False
        ).squeeze(0).squeeze(0).cpu().numpy()
        return depth.astype(np.float32, copy=False)
