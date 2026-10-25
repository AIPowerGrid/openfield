# Models and runtime setup

OpenReshoot's app code is MIT. That does not relicense model weights, native
ComfyUI nodes, adapters, encoders or source footage. No weights are bundled.
Review the linked publisher terms before downloading or using each component.
These notes identify dependencies, not a guarantee of legal clearance for every
use or territory.

## LTX-2.5 video

The selected app workflow uses these files from
[Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5):

| ComfyUI model directory | Filename |
| --- | --- |
| `diffusion_models` | `ltx-2.5-22b-distilled-transformer-bf16.safetensors` |
| `text_encoders` | `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors` |
| `vae` | `ltx-2.5-video-vae-bf16.safetensors` |
| `vae` | `ltx-2.5-audio-vae-bf16.safetensors` |
| `latent_upscale_models` | `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` |

Also place
`ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors` from the
[official Union Control adapter](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control)
in `models/loras/`. The 2.3-named adapter is intentional: the
[publisher's 2.5 workflow](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/220e1d45aa0469f518e982102fca4dca92a61862/example_workflows/2.5/LTX-2.5_ICLoRA_Union_Control_Distilled.json)
uses that pairing. Install compatible native ComfyUI and
[LTXVideo nodes](https://github.com/Lightricks/ComfyUI-LTXVideo); renaming a
different model to these filenames is not a compatible replacement.

The backbone, projection encoder, VAEs and upscaler remain subject to the
[LTX-2.x terms](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x).
The adapter's own model card links its LTX community terms. The underlying
[Gemma 4 12B model](https://huggingface.co/google/gemma-4-12B-it) is Apache-2.0;
that does not independently relicense Lightricks' projection checkpoint.
The competition-specific permission clarification and its limited scope are
recorded in the project's private notes.

Respect model use restrictions and disclosure/provenance requirements. The app
labels its result panel as AI-made; newly prepared MP4 exports carry
AI-generation title/description tags, and take settings contain `ai_generated`.
These are ordinary metadata, not signed Content Credentials or a legal
compliance certification. Public demonstrations must also clearly disclose AI
generation in their visible context. Do not remove existing provenance markers.

Video has been tested on an RTX PRO 6000 Blackwell with 96 GB VRAM and on
Comfy Cloud. The owned-device test is not a demonstrated minimum VRAM figure.
Cloud rendering needs no local GPU. No NVFP4 video preset is qualified in this
app.
The same two-pass BF16 graph now supports portrait 576x1024 latent dimensions
and square 640x640, yielding 1152x2048 and 1280x1280 respectively. Each completed
one five-second owned-runtime source-guided candle control through the official
SDK, with independent full frame counts and sampled visual review. These do
not establish Cloud compatibility at those shapes, appearance-reference
replacement or a lower-VRAM hardware requirement.
The closing-look path additionally needs native `LTXVAddGuide` and
`LTXVCropGuides`; it uses the same weights, not a new adapter. Its frame-120,
strength-0.7 guidance has three matched owned-runtime tests, a Cloud SDK render,
and an actual browser take using two generated MOSS images. The app checks native
node availability before submitting a closing-look take to an owned runtime.
The same source, opening image and closing image bytes completed on both video
backends; that is portability evidence, not a promise of bit-identical results.

### Additional Starting Modes

Text/image starts use the same LTX-2.5 backbone, encoder, VAEs and upscaler above
without the source-video Union/edge path. Audio mode adds native
`LTXVAudioVAEEncode` and a zero noise mask so supplied audio conditions both
sampling passes. Its normalized sound is used at export rather than substituted
with generated sound. Square text/audio native checks and an actual image-first
browser render pass. This is not the complete Cloud/shape/reference matrix or
proof of lip sync. MOSS/Klein look generation still uses source-video frames;
the other modes currently accept uploaded opening/closing images.

### Single-Pass Speech Profile

The explicit `single-pass-audio` profile reuses the same BF16 backbone, encoder
and VAEs. Its audio path is `LoadAudio` -> `LTXVAudioVAEEncode` -> a zero
`SetLatentNoiseMask` -> `LTXVConcatAVLatent`, before sampling, rather than only
muxing sound onto an independently generated picture. It uses one CFG-1
`euler_ancestral_cfg_pp` sampler with eight fixed manual sigma steps. It does not
load the spatial latent upscaler or run a refinement pass.

An optional opening uses `LTXVImgToVideoInplace` after compression-35 preprocessing.
Audio starts use strength 1; video starts use 0.75 plus the Union Control adapter,
Canny 0.35/0.75 and guide strength 0.85. This is the bounded earlier AIPG Director
speech setup, not a generic motion/identity-strength control. Video starts must
contain usable audio in the chosen window. An optional closing image now adds
`LTXVAddGuide` at the last model frame with strength 0.7, after compression-35
preprocessing. The sampler and crop both receive its conditioning, and the
audio latent remains fixed. Reusing the opening at the end uses this same path;
it does not load BFS, Ripple or a separate identity adapter. This may constrain
motion. Saved takes without a closing image retain the original graph.

The native 121-frame output uses the base canvas above. Export trims to 120 frames
and CPU-resizes 2x with Lanczos, with the supplied five-second audio. Saved
metadata distinguishes native resolution from exported resolution and records
`spatial_refinement: false`. Default and legacy takes remain two-pass. Matched
real studio audio/opening-image renders have native graph/input/output evidence;
see the footage notes for the narrower quality and hardware scope. No lower-VRAM,
Cloud speech-profile or general lip-sync qualification follows from these tests.

## Optional MOSS opening looks

The native MOSS stage uses
[Comfy-Org/MOSS-Image](https://huggingface.co/Comfy-Org/MOSS-Image), which
publishes its repackaged files as Apache-2.0. The original
[MOSS-Image-SFT](https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT) and
[Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) model cards also identify
Apache-2.0. Use the VAE from this exact MOSS pack; a similarly named file from
another release does not establish matching provenance or terms.

All three installed test files matched the publisher's SHA-256 records at
revision `ee64003102c8470ee32501cf883419235db81884`:

| ComfyUI model directory | Filename | SHA-256 |
| --- | --- | --- |
| `diffusion_models` | `moss_image_sft_bf16.safetensors` | `f96738d8116d78b7316b57c663d8c98591ddafab7488f48e3099b7655e34ab6f` |
| `text_encoders` | `qwen3.5_9b_int8_convrot.safetensors` | `32e3787472f708fa5f83624acbf5ef23f7fc89c439e05065ea57cfe5a97f025a` |
| `vae` | `flux2-vae.safetensors` | `868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3` |

The [official native setup guide](https://github.com/OpenMOSS/MOSS-Image/blob/main/comfyui/README.md)
requires a ComfyUI revision containing MOSS support (`e087d8f6` or later), not
merely a similar release number. Its guide notes that v0.41.3 predates that
support. Use `CLIPLoader` type `moss_image`. The native model supplies flow shift
5; do not transplant the old plugin's sampling override into this graph.

The app uses `SkipLayerGuidanceDiTSimple` with single layer 22, no double layers,
and the full sampling interval. This follows the publisher's negative-branch
guidance recommendation. The app checks the node and exact filenames before
accepting a look job. Sampling remains 50 Euler/simple steps, CFG 3. Existing
look exports retain their actual saved guidance settings, including older runs
without layer skipping.

This is source-guided img2img, not a trained instruction or identity editor.
Native MOSS was tested on an RTX 5090 with 32 GB VRAM, separately from the video
runtime. This is tested hardware, not a minimum specification. MOSS Cloud
execution is not yet qualified; the optional stage currently requires an owned
runtime through the official SDK proxy. See the
[configuration](README.md#optional-moss-opening-looks). Image upload still works
without MOSS.

## Optional Klein 4B Cloud looks

`--look-engine klein-cloud` explicitly selects native reference-conditioned
image editing through the official Comfy SDK on Cloud. MOSS remains the default;
there is no automatic fallback. LTX 2.5 remains the video model.

| ComfyUI model directory | Filename |
| --- | --- |
| `diffusion_models` | `flux-2-klein-4b-fp8.safetensors` |
| `text_encoders` | `qwen_3_4b.safetensors` |
| `vae` | `flux2-vae.safetensors` |

The [publisher's exact FP8 model](https://huggingface.co/black-forest-labs/FLUX.2-klein-4b-fp8)
and [Comfy's Klein 4B encoder/VAE pack](https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b)
identify Apache-2.0; the underlying [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B)
does too. Do not substitute Klein 9B or assume that a similarly named VAE from
a non-commercial repository has the same provenance. The Cloud workflow selects
these filenames; it does not independently hash Cloud's hosted weight bytes.
Weights are not bundled or downloaded by this application.

The tested graph uses four steps, Euler, CFG 1 and `ReferenceLatent` on positive
and zeroed-negative conditioning. It creates one image at the normalized source
frame's size. There is no denoise slot, LoRA or partner-model API node. The app
hides the MOSS-only strength selector and rejects a non-null denoise value for
this engine. Exports retain the actual image model, settings and workflow.
Cloud readiness checks access, not model capacity, balance or output quality.
The generic Warm Film/Blue Hour palettes have real still-image comparisons;
those can produce overly dark or saturated looks. Inspect the image rather than
assuming a fixed palette is suitable for every source.

## Product Looks

Product shorts use the same Klein 4B reference graph with the uploaded product
photo as the reference and an empty latent at the look size. Cloud uses
`flux-2-klein-4b-fp8.safetensors`; the owned image runtime uses the publisher's
`flux-2-klein-4b.safetensors` with the same `qwen_3_4b.safetensors` and
`flux2-vae.safetensors`. The app checks those filenames before submitting an
owned look. Optional MOSS refinement chains the MOSS graph above at denoise 0.4
on Klein's decoded image in the same workflow, so it needs the MOSS files too.
Packshots are composed locally with Pillow and FFmpeg from the supplied photo
and the bundled caption font; they involve no model.

## Optional FastH3 Comparison

The owner reports direct permission from MiniMax and authorizes private
FastH3 evaluation. That statement does not relicense the weights for other users
or establish unrestricted public serving rights. The app's MIT license remains
separate from the [MiniMax H3 Community License](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)
and any separately applicable permission. No weights or permission correspondence
are bundled.

The comparison selects
[FastVideo/FastH3-Omni-NVFP4-QAD-Comfy](https://huggingface.co/FastVideo/FastH3-Omni-NVFP4-QAD-Comfy),
not the older native MiniMax H3 model or the separate FastVideo-runtime format.
The installed checkpoint was rehashed and matches
`bf25ee58df65b4dfee349d612f7ac62a2fea0dddd1e68eb37e75c8ce8b166f5a`.
It requires native MiniMax H3 Comfy nodes plus:

| ComfyUI model directory | Filename |
| --- | --- |
| `diffusion_models` | `fasth3_omniref_qad_nvfp4_comfy.safetensors` |
| `text_encoders` | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| `vae` | `minimax_h3_video_vae_fp16.safetensors` |
| `vae` | `minimax_h3_audio_vae_fp32.safetensors` |

The publisher requires Blackwell for accelerated NVFP4. The private runtime
uses isolated dependencies rather than modifying the LTX installation. Two
124-frame square tests through the official SDK completed: text-only and an
appearance image plus reference audio. Both are 768x768 at 24 fps with 32-kHz
stereo audio; timings are recorded as observations, not matched LTX benchmarks.
LTX remains the studio default. There is no Cloud fallback to older H3, no new
public Grid recipe/rate and no identity, exact soundtrack or lip-sync guarantee.
An additional owned-runtime image-reference take reuses a saved LTX take's image,
scene prompt and seed. It passes complete decode, but native resolutions and
image-conditioning roles differ. See the footage notes for its comparison limits
and startup-recovery caveat; it is not a model-speed benchmark or an app-picker
integration.

Two further owned-runtime portrait tests compare text-only and an appearance
image using the same scene description and seed. Each native output is
768x1344, 124 frames at 24 fps, with generated stereo 32-kHz audio. Both fully
decode, and downloaded hashes match their separate native prompt outputs.
Native portrait is not exact 9:16: review copies contain-fit it to 720x1280
without stretching, preserving the generated audio. Sampled reference frames
retain the supplied paper boat and environment more closely; this is not a
general identity-control or speed qualification. No app default, public Grid
model, Cloud balance or production dependency changes follow, and both LTX
workers are restored.

The private helper also accepts an explicit video reference alongside the
appearance image. It binds that reference to the native video slot, not frame
zero, and keeps image/audio/video roles separate. An owner-requested portrait
comparison now covers video-plus-image versus audio-plus-image with the same
portrait, scene description and seed. Both native clips fully decode and match
their native output hashes. Separate disclosed review exports use the supplied
soundtrack; that mux is not evidence of native waveform retention or lip sync.
The supplied human-performance material is private test evidence, not cleared
competition media or a qualified public replacement feature.
The owner rejected both H3 clips for poor mouth timing. Two subsequent LTX-2.5
Distilled BF16 controls use the actual earlier car-scene single-pass graphs:
encoded source audio with zero noise mask, plus a scene opening; the video-guided
case also uses Union Control. Both execute through the SDK and pass native byte,
graph and complete-decode checks. The audio/image result retains appearance
better in sampled frames; video guidance introduces hairstyle drift and garbled
captions. New word-level synchronization remains a human review, not a claim
derived from waveform retention. Neither experiment changes the app defaults.
The later speech-anchor follow-up is also FastH3 Omni NVFP4 QAD, not a separate
"Omni" checkpoint or a standard MiniMax H3 run. It adds native frame-zero audio
and opening-image guides using the same scene opening as LTX. One SDK/native
byte-bound clip and a five-second side-by-side complete; synchronized mouth
motion still needs direct review. Both normal LTX workers are restored.

On 2026-10-23 the owner approved a four-way matched comparison (same prompt and
seed): text to video, animate a photo, a product reference and a talking
portrait with a supplied synthetic voice. FastH3 Omni ran on owned GPU1 with
the Grid worker paused for about 25 minutes and then restored; GPU0 was
untouched. LTX-2.5 ran on Comfy Cloud. All eight clips decode; FastH3 job
times were 210 s (including model load), 129 s, 109 s and 120 s on different
hardware, so they are observations, not a speed benchmark. Text and photo
animation are close. FastH3 builds the product scene in one step from the raw
photo with the right logo but garbled lettering; the LTX path keeps the
lettering because Klein places the product first. FastH3's anchored audio
closely follows the supplied voice; mouth timing still needs owner review.
LTX remains the default.

## Captions and prompt helper

Auto captions run [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
(MIT) on the CPU with the `small` Whisper model (MIT, downloaded once from
Hugging Face into the local cache). Audio is decoded with FFmpeg and never
leaves the machine. The optional prompt helper calls an Ollama model on a
loopback address; the owner's setup uses
[Phi-4-mini](https://ollama.com/library/phi4-mini) (MIT). Without one, the
helper falls back to a template. Neither model is bundled.

## Other software and media

Captions bundle unmodified Noto Sans under SIL OFL 1.1, with its copyright,
source pin and integrity/coverage metadata in `src/aipg_cinema/fonts/`.
The font license is included in wheels and remains separate from the app's MIT
license. Runtime captioning does not fetch fonts or depend on system fonts.

The [official Python SDK](https://github.com/Comfy-Org/comfy-python-sdk) is MIT.
ComfyUI and native node packages retain their own licenses and run separately
from this application. The app retains the upstream workflow-template MIT
notice and Lucide's icon notice in both source and built wheels.

The [footage notes](tests/REAL_FOOTAGE.md) identify each test input's author,
license and changes. Media are not relicensed by the app's MIT license.
ShareAlike sources need their corresponding adaptation terms and attribution
when distributed. Test downloads and generated media are excluded from Git.
