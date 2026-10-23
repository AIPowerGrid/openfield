# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Single-pass fixed-audio LTX, adapted from the tested AIPG Director graph."""

from .reshoot import node, video_format


def graph(
    prompt: str,
    seed: int = 42,
    *,
    frame_format: str = "portrait",
    opening: bool = False,
    closing: bool = False,
    source_video: bool = False,
) -> dict:
    spec = video_format(frame_format)
    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("Describe the shot in 1-4000 characters.")
    if type(seed) is not int or not 0 <= seed <= 2**63 - 1:
        raise ValueError("Choose a non-negative whole-number seed below 2^63.")
    if closing and not opening:
        raise ValueError("An ending frame requires an opening image.")
    workflow = {
        "backbone": node(
            "UNETLoader",
            unet_name="ltx-2.5-22b-distilled-transformer-bf16.safetensors",
            weight_dtype="default",
        ),
        "clip": node(
            "CLIPLoader",
            clip_name="gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
            type="ltxv",
            device="default",
        ),
        "vae": node("VAELoader", vae_name="ltx-2.5-video-vae-bf16.safetensors"),
        "audio-vae": node("VAELoader", vae_name="ltx-2.5-audio-vae-bf16.safetensors"),
        "positive": node("CLIPTextEncode", clip=["clip", 0], text=prompt),
        "negative": node(
            "CLIPTextEncode",
            clip=["clip", 0],
            text="frozen still image, cuts, changing identity, extra people, distorted face, captions, subtitles, logos, watermark",
        ),
        "condition": node(
            "LTXVConditioning",
            positive=["positive", 0],
            negative=["negative", 0],
            frame_rate=24,
        ),
        "empty": node(
            "EmptyLTXVLatentVideo",
            width=spec.width,
            height=spec.height,
            length=121,
            batch_size=1,
        ),
        "source-audio": node("LoadAudio", audio="source.wav"),
        "encode-audio": node(
            "LTXVAudioVAEEncode", audio=["source-audio", 0], audio_vae=["audio-vae", 0]
        ),
        "audio-mask": node("SolidMask", value=0.0, width=1, height=1),
        "fixed-audio": node(
            "SetLatentNoiseMask", samples=["encode-audio", 0], mask=["audio-mask", 0]
        ),
        "noise": node("RandomNoise", noise_seed=seed),
        "sampler": node("KSamplerSelect", sampler_name="euler_ancestral_cfg_pp"),
        "sigmas": node(
            "ManualSigmas",
            sigmas="1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0",
        ),
        "sample": node(
            "SamplerCustomAdvanced",
            noise=["noise", 0],
            guider=["guider", 0],
            sampler=["sampler", 0],
            sigmas=["sigmas", 0],
            latent_image=["av", 0],
        ),
        "separate": node("LTXVSeparateAVLatent", av_latent=["sample", 0]),
        "crop": node(
            "LTXVCropGuides",
            positive=["condition", 0],
            negative=["condition", 1],
            latent=["separate", 0],
        ),
        "decode": node(
            "VAEDecodeTiled",
            samples=["crop", 2],
            vae=["vae", 0],
            tile_size=512,
            overlap=64,
            temporal_size=128,
            temporal_overlap=32,
        ),
        "video": node(
            "CreateVideo",
            images=["decode", 0],
            audio=["source-audio", 0],
            fps=24,
            bit_depth=8,
        ),
        "save": node(
            "SaveVideo",
            video=["video", 0],
            filename_prefix="aipg-cinema/speech",
            format="auto",
            codec="auto",
            **{"format.codec": "auto"},
        ),
    }
    latent = ["empty", 0]
    if opening:
        workflow.update(
            {
                "look": node("LoadImage", image="look.png"),
                "look-scale": node(
                    "ImageScale",
                    image=["look", 0],
                    upscale_method="lanczos",
                    width=spec.width,
                    height=spec.height,
                    crop="disabled",
                ),
                "look-preprocess": node(
                    "LTXVPreprocess", image=["look-scale", 0], img_compression=35
                ),
                "look-anchor": node(
                    "LTXVImgToVideoInplace",
                    vae=["vae", 0],
                    image=["look-preprocess", 0],
                    latent=latent,
                    strength=0.75 if source_video else 1.0,
                    bypass=False,
                ),
            }
        )
        latent = ["look-anchor", 0]
    positive, negative, model = ["condition", 0], ["condition", 1], ["backbone", 0]
    if source_video:
        workflow.update(
            {
                "source": node("LoadVideo", file="source.mp4"),
                "frames": node("GetVideoComponents", video=["source", 0]),
                "source-window": node(
                    "ImageFromBatch", image=["frames", 0], batch_index=0, length=121
                ),
                "edges": node(
                    "Canny",
                    image=["source-window", 0],
                    low_threshold=0.35,
                    high_threshold=0.75,
                ),
                "model": node(
                    "LTXICLoRALoaderModelOnly",
                    model=model,
                    lora_name="ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors",
                    strength_model=1.0,
                ),
                "guide": node(
                    "LTXAddVideoICLoRAGuide",
                    positive=positive,
                    negative=negative,
                    vae=["vae", 0],
                    latent=latent,
                    image=["edges", 0],
                    frame_idx=0,
                    strength=0.85,
                    latent_downscale_factor=["model", 1],
                    crop="disabled",
                    use_tiled_encode=False,
                    tile_size=256,
                    tile_overlap=64,
                ),
            }
        )
        latent, positive, negative, model = (
            ["guide", 2],
            ["guide", 0],
            ["guide", 1],
            ["model", 0],
        )
    if closing:
        workflow.update(
            {
                "closing": node("LoadImage", image="closing.png"),
                "closing-scale": node(
                    "ImageScale",
                    image=["closing", 0],
                    upscale_method="lanczos",
                    width=spec.width,
                    height=spec.height,
                    crop="disabled",
                ),
                "closing-preprocess": node(
                    "LTXVPreprocess", image=["closing-scale", 0], img_compression=35
                ),
                "closing-guide": node(
                    "LTXVAddGuide",
                    positive=positive,
                    negative=negative,
                    vae=["vae", 0],
                    latent=latent,
                    image=["closing-preprocess", 0],
                    frame_idx=workflow["empty"]["inputs"]["length"] - 1,
                    strength=0.7,
                ),
            }
        )
        latent, positive, negative = (
            ["closing-guide", 2],
            ["closing-guide", 0],
            ["closing-guide", 1],
        )
    workflow["guider"] = node(
        "CFGGuider", model=model, positive=positive, negative=negative, cfg=1.0
    )
    workflow["crop"]["inputs"].update(positive=positive, negative=negative)
    workflow["av"] = node(
        "LTXVConcatAVLatent", video_latent=latent, audio_latent=["fixed-audio", 0]
    )
    return workflow
