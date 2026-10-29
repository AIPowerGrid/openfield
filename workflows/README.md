# Platform-proof workflows

## MiniMax H3 native

`minimax-h3-native.json` is an API-format graph adapted from Comfy Org's
[official benchmark at revision d0e41fe](https://github.com/Comfy-Org/workflow_templates/blob/d0e41fe5423f93db5b5872cf273d7b1af8aa68bc/benchmarks/video_minimax_h3_t2v.json).
Its MIT notice is in `COMFY-TEMPLATES-LICENSE.txt`.

Changes: original non-person product prompt, seed 42, new output prefix, and
removal of the disabled optional lightning-LoRA branch. The base model keeps
the upstream 20-step schedule. Requested duration is 5 seconds; H3's 17k+5 frame
grid rounds that to 124 frames at 24 fps (approximately 5.17 seconds).

```sh
uv run aipg-cinema check workflows/minimax-h3-native.json --output-node 92
```

After API access, applicable model rights and spending have been approved:

```sh
uv run aipg-cinema render workflows/minimax-h3-native.json --output-node 92 --run-dir runs/h3-proof --execute
```

Executed successfully through the official SDK on Comfy Cloud on October 20,
2026: 864x480, 124 frames at 24 fps, with AAC audio. Cloud reported 2 seconds
queued and 45 seconds running. This is the native MiniMax H3 model listed in
Comfy's official model pack. The published competition bonus names MiniMax H3
as the core model; it does not specify a separate "H3 Omni" API SKU. Final entry
eligibility remains subject to all competition and model-license requirements.

## LTX-2.5 native

`ltx-2.5-native.json` adapts the [official native T2V template](https://github.com/Comfy-Org/workflow_templates/blob/d0e41fe5423f93db5b5872cf273d7b1af8aa68bc/templates/video_ltx2_5_t2v.json)
at the same revision and under the same MIT notice. The graph is flattened into
API format manually. The resulting graph has now completed a real Cloud job.
It retains the distilled 8-step first pass, x2 latent upscaler and 3-step
refinement pass. The optional
prompt enhancer and preview-only branches are omitted.

Changes: the same original product prompt, fixed seed 42 for both passes, 121
frames at 24 fps (approximately 5.04 seconds), and a 512x288 first pass targeting
1024x576 output. Both first-pass dimensions are divisible by 32.

```sh
uv run aipg-cinema check workflows/ltx-2.5-native.json --output-node 75
```

After API access, applicable model rights and spending have been approved:

```sh
uv run aipg-cinema render workflows/ltx-2.5-native.json --output-node 75 --run-dir runs/ltx-proof --execute
```

Executed successfully through the official SDK on Comfy Cloud on October 20,
2026: 1024x576, 121 frames at 24 fps, with AAC audio. Cloud reported 2 seconds
queued and 31 seconds running. The teapot changes shape and the generated audio
is nearly silent; successful execution does not imply showcase quality.

Both baselines were downloaded and inspected. They are not matched
quality-comparison presets: their durations and resolutions differ. Run state
and generated media are local and excluded from Git.

## OpenReshoot motion candidates

`aipg_cinema.reshoot.graph` builds API-format motion experiments from the
[native H3 R2V template](https://github.com/Comfy-Org/workflow_templates/blob/d0e41fe5423f93db5b5872cf273d7b1af8aa68bc/templates/video_minimax_h3_r2v.json)
and [LTX-2.3 IC-LoRA template](https://github.com/Comfy-Org/workflow_templates/blob/d0e41fe5423f93db5b5872cf273d7b1af8aa68bc/templates/video_ltx2_3_ic_lora.json).
Both are under the upstream MIT notice retained here; model licenses are separate.

The candidates use the same five-second source content, 768x448 canvas, 24 fps,
seed 42 and content prompt. H3 uses its `ref2va` checkpoint, tagged video input,
20-step beta schedule and `res_multistep` sampler. LTX uses the 2.3 distilled FP8
checkpoint, official Union Control adapter and native Canny guide, with the
upstream eight-step `euler_ancestral` / `linear_quadratic` schedule. The optional
prompt enhancer and first-frame image anchor were omitted in those tests.

The current `ltx25` candidate follows Lightricks' [official 2.5 Union Control
workflow](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/220e1d45aa0469f518e982102fca4dca92a61862/example_workflows/2.5/LTX-2.5_ICLoRA_Union_Control_Distilled.json),
which explicitly pairs the 2.5 backbone with the 2.3-named Union adapter. It uses
the 2.5 distilled BF16 transformer, Gemma 4 projection, separate 2.5 VAEs and
two-stage refinement to 1536x896. This is distinct from the older 2.3 experiment.

All three procedural source cases completed on both candidates. The local run
directory retains the portable graph, normalized source and settings. SDK asset
references replace the portable filename during submission. Generated model audio
is not used: local export combines the rendered frames with the normalized
source soundtrack. These are internal feasibility tests, not proof of general
motion fidelity, model rights for publication, or a finished contest entry.

## FastH3 Omni challenger

`--model fasth3 --backend self-hosted` selects the October 20 FastVideo
[FastH3 Omni NVFP4 QAD Comfy release](https://huggingface.co/FastVideo/FastH3-Omni-NVFP4-QAD-Comfy),
not the earlier native H3 checkpoint above. It uses eight steps, basic guidance,
the simple schedule, video shift 12 and audio shift 3, with the matching reference
encoder and FP16 video VAE. Output is 1536x896 and the same five-second export
window as `ltx25`. Only original/permissioned object footage is used here.

The tested checkpoint is `fasth3_omniref_qad_nvfp4_comfy.safetensors`, model-repo
revision `36dbf15cd11113471114b1040c4f38646c031549`, SHA-256
`bf25ee58df65b4dfee349d612f7ac62a2fea0dddd1e68eb37e75c8ce8b166f5a`.
The installed file hash matches its published digest. Accelerated NVFP4 requires
Blackwell hardware. This release was absent from the checked Cloud catalog, so
the CLI rejects Cloud execution rather than silently substituting older H3.

It inherits the [MiniMax H3 license](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE),
including territorial restrictions. Do not infer unrestricted deployment rights
from open weights or a successful private test. App selection, public rights,
quality and competition-bonus eligibility remain separate decisions.

### Studio Input Evaluation

After the owner reported direct MiniMax permission and requested more tests,
`aipg_cinema.fasth3.graph` adds a separate opt-in comparison graph for text,
appearance-image and reference-audio inputs. It uses the same verified NVFP4
checkpoint, eight-step preset and official SDK/proxy execution. It is not a
video-model selector in the studio and never changes the LTX default.

Appearance images condition identity/appearance; they are not silently inserted
as the opening frame. Reference audio conditions generated sound and is not
promised to be a preserved waveform. The graph explicitly decodes the model's
audio VAE output into the exported video. No opening-frame guide, original-audio
mux, automatic retry, Grid billing or public admission is added.

The bounded comparison uses 124 frames at 24 fps. Offline graph tests cover
1344x768 landscape, 768x1344 portrait-bucket and 768x768 square canvases; only
square has the new native text/reference evidence. The portrait bucket is not
exact 9:16. Do not infer a qualified app format or duration from graph acceptance.
See the [native evidence and limitations](../tests/REAL_FOOTAGE.md#fasth3-studio-input-evaluation).

## LTX-2 effects

`ltx-2-effect.json` is an API-format graph converted from Comfy Org's
[LTX-2 image-to-video LoRA template at revision 86ce86e](https://github.com/Comfy-Org/workflow_templates/blob/86ce86e92ec77e3c3c6d4a754e69cfce37886542/templates/video_ltx2_i2v_lora.json)
("Squish Anything with LTX-2"). Its MIT notice is in `COMFY-TEMPLATES-LICENSE.txt`.

Changes: the subgraph is flattened, the input image is `look` and the output
is `save`, and the photo is pinned again on the upscaled latent (`repin`)
because the template's second pass otherwise redrew the person's face. The
effect LoRA, prompt, seed, size and 121-frame length are set per take by
`src/aipg_cinema/effects.py`. The LoRAs themselves are hosted by Comfy Cloud;
see the source of each in that file.

An identical copy ships inside the package as
`src/aipg_cinema/workflows/ltx-2-effect.json` so installed wheels find it;
keep both copies the same (a test checks).
