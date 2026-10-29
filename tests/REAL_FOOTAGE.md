# Real-camera quality inputs

These permissioned camera clips supplement our original procedural fixtures.
They are test inputs, not approved submission/showcase media. Downloads, source
metadata, prepared clips and generated takes stay in ignored local run storage.
They are not included in the package or relicensed under the application's MIT
license. No endorsement by their authors is implied.

| Test | Source and author | Source license | Preparation |
| --- | --- | --- | --- |
| Cradle | [Newton's cradle slo mo](https://commons.wikimedia.org/wiki/File:Newton%E2%80%99s_cradle_slo_mo.webm), Nigos | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) | First six seconds; transcode to H.264; remove unreviewed audio |
| Pendulum | [Foucault pendulum utexas motion](https://commons.wikimedia.org/wiki/File:Foucault_pendulum_utexas_motion.webm), Spheroidite | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | First six seconds; transcode to H.264; original has no audio stream |
| Turbines | [Wind turbines in operation](https://commons.wikimedia.org/wiki/File:Wind_turbines_in_operation.webm), Acdixon | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | Crop to top 1280x480 to exclude parked cars; initial tests removed audio; a later technical test retained the source recording |
| Candle | [Blue candle burning](https://commons.wikimedia.org/wiki/File:Blue_candle_burning.webm), Jahobr | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | First five seconds; original is silent, 600x400 |
| Bubble wand | [Soap bubbles being formed by a bubble wand - slow motion - 2022 July 28](https://commons.wikimedia.org/wiki/File:Soap_bubbles_being_formed_by_a_bubble_wand_-_slow_motion_-_2022_July_28.webm), Nesnad | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | First five seconds; original is silent; inspected the selected window for people/brands |
| Forest waterfall | [Bigora waterfall](https://commons.wikimedia.org/wiki/File:Bigora_waterfall.webm), Termininja | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | First five seconds; crop 1440x810 at x=280, y=270; retain recorded audio; a small flag tip remains at the upper edge |
| Lava lamp | [Lava lamp (oT) 07 ies](https://commons.wikimedia.org/wiki/File:Lava_lamp_(oT)_07_ies.ogv), Frank Vincentz | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) | First five seconds; silent; still-image edit rejected before video generation |
| Mountain cloud | [Lenticular cloud over Longs Peak, Colorado (time lapse)](https://commons.wikimedia.org/wiki/File:Lenticular_cloud_over_Longs_Peak,_Colorado_(time_lapse).ogv), Stepleton | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | First five seconds; original has no audio stream |

Original download SHA-1 values from the file-specific Commons records:

```text
cradle    55e68786addbd3d0a1013738ff7918a7d99fb5ca
pendulum  fcc1f6db0c884a005cb8383498c842ae13d427ff
turbines  eb381f13ae9a5b95151d07825f9aa1a4bade20f0
candle    512b5434370414e8458e5b9ecdc1153b0dd2d80a
bubbles   696f2f574942f54dc4b3dbfcacd2ee405ace39f2
waterfall 482e7b2a98cf29615bf5c38286d9bc3e4dd648a0
lava lamp 8b1d61e6688301d4c3d9f3ae42f0f9498d9d40bc
mountain  aa5c798825184c04ab7b3ec19ce74b206bd2f666
```

Verify downloaded originals against Commons metadata, not the SHA-1 values of
subsequently trimmed or transcoded clips. The Commons structured-data CC0 footer
does not replace each media file's own license.

For these sources, inspect motion, framing, consistency and flicker. The initial
three prepared inputs are silent, so those renders cannot establish preservation
of a real soundtrack. The later turbine/audio test is recorded separately below.
The separate procedural audio test and Cloud/browser renders exercise normalized
AAC preservation. Do not describe those as bit-exact original-upload preservation.

Any public adaptation of a ShareAlike source must carry appropriate attribution,
change notices and the applicable ShareAlike terms for the media. Keep those
media terms separate from the app-code license when preparing a submission.

## First LTX-2.5 BF16 results

All three completed through the official SDK and self-hosted proxy on one owned
RTX PRO 6000 Blackwell 96 GB GPU. These are submission-through-download
observations, excluding input preparation and final local export, not a
controlled benchmark or minimum VRAM requirement. No Cloud credits were used for
these three runs; electricity and hardware costs were not measured.

| Clip | Submission through download | Sampled visual assessment |
| --- | --- | --- |
| Cradle | 85.20 s | Warm laboratory setting appears; the outer ball follows the sampled swing positions, but spheres, wires and supports deform |
| Pendulum | 55.34 s | Blue-hour observatory treatment appears; sampled bob positions and overhead framing stay close, while the dial and surroundings change |
| Turbines | 76.72 s | Night treatment appears; approximate placement remains, but blades and thin structures change shape |

Each exported video is 1536x896, 24 fps, 120 frames and five seconds long. Silent
inputs remain silent; model-generated audio is not substituted. Prompts, seeds,
source bytes and workflows are saved with the ignored run evidence.

Assessment used synchronized contact sheets at one-second intervals. This does
not establish collision physics, frame-accurate motion, stable fine geometry or
absence of temporal flicker. These are useful real-camera smoke tests, not three
approved showcase examples. Look-reference and motion-strength ablations are
still needed before freezing the public creative promise.

## Matched control and model checks

The pendulum source was re-rendered with the same content prompt and seed 42.
Normalized source bytes match across these runs. The look frame is the first
frame of our earlier LTX treatment of this permissioned clip, not outside art.

| LTX-2.5 condition | Submission through download |
| --- | --- |
| No look frame, guide 1.0 | 55.34 s |
| Look frame, guide 1.0 | 87.49 s |
| No look frame, guide 0.55 | 117.48 s |
| Look frame, guide 0.55 | 78.07 s |

The opening anchor and guide weight affect the render, but this same-look test
does not prove general style-reference transfer or a predictable improvement
from lowering guide weight. Test a deliberately different, composition-matched
look before exposing the image input. Keep both controls experimental in the
CLI until their user-facing effects are demonstrated. Timings include different
loading/cache states and are not a speed benchmark.

FastH3 Omni NVFP4 QAD is being compared at the same 1536x896 output size and
five-second export window, through the official SDK proxy. Its eight-step
reference workflow is not the older 20-step H3 experiment. Source audio still
comes from the input, never the generated model soundtrack.

The first pendulum result completed in 273.88 seconds. It follows the source
appearance more closely but makes a weaker blue-hour change than LTX. The cradle
result makes a convincing warm laboratory with more coherent-looking spheres
and supports than the LTX treatment. Exact frame-number checks are necessary
when assessing swing timing: an `fps=1` contact sheet can select a different
timestamp from an explicit one-second seek. Do not infer a phase error by mixing
these sampling methods.

| FastH3 condition | Comfy execution | Submission through download |
| --- | --- | --- |
| Pendulum, video reference | 255.46 s | 273.88 s |
| Cradle, video reference | 241.80 s | 245.39 s |
| Pendulum, image plus video | 262.25 s | 487.37 s |

The mixed-reference take queued behind the cradle, so 487.37 seconds is not its
compute duration. Its graph supplies both reference fields according to the
installed native node's dynamic-input schema. The image had an explicit
target-look role and the video had a motion/timing role. It still made a weaker
blue-look transfer than the matched LTX anchor run.
This result applies to the tested ComfyUI/NVFP4 preset, not every FastH3 workflow.
No Cloud credits were spent on these three renders.

Use synchronized comparison videos or explicit frame indices 0, 24, 48, 72 and
96 for inspection at 24 fps. The comparison does not establish frame-perfect
timing, general model superiority or reproducibility across runtimes. The app
remains on LTX while H3 quality, reference-control choices and public deployment
rights are evaluated separately.

Full-frame pendulum diagnostics found 120 distinct decoded frame hashes in each
source, LTX and FastH3 export. Maximum consecutive-frame mean-luma changes were
0.183, 0.703 and 0.381 respectively (8-bit scale). This catches neither local
geometry flicker nor wrong motion: it is not a visual-quality score or evidence
that a clip is flicker-free. Synchronized video review is still required.

## Studio Starting Modes And First Short

The expanded studio uses the same official SDK/proxy and owned LTX-2.5 BF16
runtime. New square controls cover text-only and fixed audio; an actual browser
image-first take and two saved-shot renders form a three-shot short. All sources
are original generated imagery, original prompt text or a synthetic beep track.
No Cloud or billed Grid credits are spent on this slice.

| Native condition | Submission through download | Output |
| --- | --- | --- |
| Text-only paper sailboat | 62.19 s | 1280x1280, 120 exported frames, 5 s |
| Fixed synthetic rhythm audio | 47.40 s | 1280x1280, 120 exported frames, 5 s |
| Image-first browser take | 87.87 s | 1280x1280, 120 exported frames, 5 s |
| Saved reveal shot | 52.48 s | 1280x1280, 120 exported frames, 5 s |
| Saved payoff shot | 55.83 s | 1280x1280, 120 exported frames, 5 s |

These timings include different loading/cache states and are not a benchmark.
Each exports stereo 48-kHz AAC. The audio control supplies a fixed encoded audio
latent in both passes and muxes that supplied sound; its first 240000 samples per
channel have unaligned cosine 0.999682 against the normalized input. The metronome
scene retains its shape in sampled frames, but beat sync/lip sync are unproven.
The text-only boat drifts partly out of frame near the end; preserve that failure.
The image-first result retains the centered boat more usefully in sampled frames.

The real browser image take plays with unmuted generated sound, scrubs past three
seconds using the output clock and survives reload with one unchanged provider
job ID. The subsequent two takes belong to explicit saved shot IDs and project
revisions. Their openings come from the preceding clip's final frame, not an
unproven appearance-reference token. The reveal pulls back from the red boat to
its neon street puddle. The payoff introduces a golden fish/body shape beneath
the boat, but framing/recognizability still need creative review. This is a draft,
not one of three approved submission examples.

The square project exports through the actual browser to a 15-second H.264 MP4.
Independent FFprobe counts 360 frames at 24 fps; video and stereo 48-kHz AAC both
start at zero and present exactly 15 seconds (720000 samples/channel). The
player loads at 1280x1280, plays unmuted and seeks to 11.06 seconds via its native
scrubber. Shot duplicate/reorder/remove operations preserve the three original
takes and restore the original order; they create no native render. Two local
exports retain their separate saved revisions. A real app restart preserves the
full project, three provider job IDs and both completed MP4 hashes.

The mobile header can switch shots without scrolling to the board. At 390x844,
the inspected controls fit the viewport with no horizontal document overflow.
Browser screenshots and receipts stay in ignored run state. CPU tests separately
exercise exact cut ordering, per-shot mute/gain, silent inputs, frame-quantized
trims, wrong-format rejection, export failure cleanup and immutable outputs.
Node handler tests exercise uncertain same-ID submissions, save conflicts,
duplicating/moving/removing without inference and no save loops on reopened
nullable draft fields. These do not replace the unfamiliar-human trial.

## Offline Finishing Browser Evidence

The same three native square shots now have a real browser-created 15-second
finishing export with three timed captions, uploaded original procedural music
and a separate voiceover timing fixture. The latter is synthesized tones, not
spoken narration; it tests placement/fades/mute, not speech intelligibility.
No new video/image inference, Cloud credits or billed Grid calls are involved.

The browser uploads both files, changes timing and fades, mutes/unmutes the
voiceover, selects Bold captions and explicitly exports. Reload restores the
saved text, times, layers and completed export. The player plays unmuted and
seeks to the third cue at ten seconds. Desktop and 390-pixel mobile controls
are inspected; no horizontal document overflow is present. The live overlay
uses an uncaptioned picture with the same final audio mix, so it cannot double
burn captions while editing.

Independent FFprobe counts 360 frames at 24 fps, 1280x1280 H.264 and stereo
48-kHz AAC. Both tracks start at zero and last exactly 15 seconds. Pixel checks
against the clean picture verify visible captions at frames 0/95, 120/215 and
240/335, and no caption at 96/119, 216/239 or 336/359. Decoded audio hashes match
between the clean picture and captioned MP4: the caption pass copies audio.
Existing take files, earlier exports and provider job identities are preserved.
An actual app restart also preserves the saved finishing project, all three
provider receipts, takes, every completed MP4 and both original audio uploads;
the browser reopens the completed finishing view afterward.

CPU tests cover portrait/square/landscape caption bounds, styles, glyph rejection,
exact frame transitions, two-layer timing/gain/fades/loops, short source rejection,
revision-frozen exports and error cleanup. Actual JS handlers cover edits after
autosave acknowledgement, timing input persistence, reload, mute and no hidden
render/export. The font is bundled under its own SIL OFL license. None of these
checks replaces native vertical finishing, spoken narration, three creative
showcases or the unfamiliar-human trial.

## FastH3 Studio Input Evaluation

The owner reports direct MiniMax permission and explicitly requests more tests.
Two native square tests use the already-staged FastH3 Omni NVFP4 QAD runtime
through the official SDK/proxy. Its installed weight digest was independently
rechecked against the pinned release. No Cloud or billed Grid jobs are involved.

| Condition | Submission through download | Independently decoded output |
| --- | --- | --- |
| Text-only red paper boat in a neon pool | 62.13 s | 768x768, 124 frames, 24 fps, stereo 32-kHz AAC |
| Appearance image plus synthetic rhythm reference | 52.86 s | 768x768, 124 frames, 24 fps, stereo 32-kHz AAC |

These are different prompts and cache states, not a controlled speed comparison
against each other or LTX. Picture duration is 124/24 seconds; AAC presentation
duration is 5.166688 seconds, within one 32-kHz sample. Both complete full video
and audio decode. No replacement native job was submitted. A local serializer
error before the second case's submission is preserved; saving its portable
graph before binding SDK assets resolves it. That failed preparation created no
provider job.

The first clip uses only original prompt text. The second uses a centered frame
from our original LTX paper-boat generation and five seconds of our own synthetic
beeps, not outside art, music or likenesses. The text-only result shows a folded
open boat moving through neon water. The reference result retains the red sailboat
and cyan/magenta setting in sampled frames 0, 48 and 96. This is limited appearance
evidence, not all-frame identity fidelity, exact motion preservation or a general
creative-quality pass.

Both results contain model-generated audio. The audio input is a reference;
there is no source-waveform replacement at export. Beat synchronization,
lip sync and exact-source sound preservation have not been demonstrated.
The app's LTX default and public Grid/Gallery capabilities remain unchanged.
The borrowed GPU is restored to its original LTX backend/worker, with the other
GPU's backend PID unchanged. A subsequent browser file-upload attempt stalled;
it dispatched no generation and is not browser qualification of the new input
controls. The test runtime's maximum lifetime stopped H3 during that stall;
LTX was manually restored and its queue/readiness verified afterward.

### Additional matched-image comparison

One further owned-runtime SDK job uses the exact opening-image bytes, scene
prompt and seed 42 from the saved LTX square boat take. FastH3 adds only its
required `<Picture 1>` appearance-role instruction. This is an appearance
reference, not the same conditioning operation as LTX's opening-frame anchor.
LTX's native export is 1280x1280 for 120 frames; FastH3 is 768x768 for 124 frames.
The local, silent side-by-side review scales both to 640x640 and compares the
first 120 frames at 24 fps. Original outputs with sound remain unchanged.

The FastH3 result passes complete video/audio decode and independently reports
124 frames, 24 fps, stereo 32-kHz AAC and a 5.166688-second audio presentation.
Sampled frames retain the centered red sailboat and cyan/magenta environment.
This does not establish superior motion, identity fidelity or overall quality.
Native resolutions and conditioning roles differ, so this is not a controlled
performance benchmark.

The initial local asset check preceded runtime readiness and failed before any
provider submission. The continuation reused the same saved idempotency key
and produced exactly one provider job. Its saved elapsed time includes startup
recovery; do not present that value as model execution speed. Both normal LTX
backends and Grid workers were restored, queues checked empty, and GPU0 process
identities preserved. No Cloud or billed Grid calls were made. This evaluation
does not add FastH3 to the app picker or admit a public Grid model.

### Portrait text / appearance comparison

Two further official-SDK jobs use the same original neon paper-boat scene
description, seed 1234, eight-step NVFP4 graph and native 768x1344 portrait
bucket. The second adds the original generated boat image and its explicit
`<Picture 1>` appearance-role instruction. Neither job supplies reference audio
or video. The extra role instruction and image are the deliberate difference;
this is not a comparison against LTX or the separate FastVideo inference engine.

| Condition | Submission through download | Independently decoded output |
| --- | --- | --- |
| Text only | 108.65 s | 768x1344, 124 frames, 24 fps, stereo 32-kHz AAC |
| Same scene plus appearance image | 187.28 s | 768x1344, 124 frames, 24 fps, stereo 32-kHz AAC |

Both complete full video/audio decode, contain 124 distinct decoded frames and
have audio presentation within one 32-kHz sample of the 124/24-second picture.
SDK-downloaded SHA-256 values independently match their native prompt outputs.
These elapsed observations include loading and transfer; they are not compute
benchmarks or evidence that the reference mode is generally slower.

At frames 0, 48 and 96, the image-reference case stays closer to the supplied
boat shape and cyan/magenta environment. The text-only case builds a different
folded hull and adds visible background sign lettering despite the no-text
prompt. Sampled consistency does not prove every-frame geometry, exact motion,
flicker-free output, arbitrary person identity or lip sync. Both soundtracks
are model-generated, not an exact-source-audio test.

Native 768x1344 is not exact 9:16. Separate 720x1280 review copies resize the
picture proportionally and add ten pixels above and below; generated audio is
copied, and the native files remain unchanged. Original inputs, prompts, seeds,
graphs, provider IDs, native hashes and decode proof stay in ignored local
evidence. Exactly two new provider jobs run, with no Cloud or billed Grid calls.
The temporary runtime and tunnel are closed; both normal LTX workers recover,
with the other GPU's service process identities unchanged. This does not add
FastH3 to the app picker or qualify a public Grid rollout.

### Private performance comparison

The subsequent private owner-supplied performance comparison is not submission
footage. Two official-SDK FastH3 portrait jobs bind the same appearance portrait,
scene description and seed: one uses an actual video reference; the other uses
its corresponding audio with no video-frame input. Each completes 124 frames
at 24 fps, 768x1344, with full native audio/video decode and a downloaded hash
matching the native SaveVideo output. Submission-through-download observations
are 384.37 and 108.25 seconds, respectively; different conditioning and loading
states make these observations, not a model-speed benchmark.

Sampled video-guided frames retain more clothing/scene cues, but redraw the
environment and do not follow the source frame-for-frame. Audio-guided frames
invent a new performance and court layout. Neither establishes exact identity,
gesture timing, lip sync or general replacement quality. Both separate review
copies are labeled as AI-edited parody and mux the original uploaded voice,
not a clone of the depicted person's voice. The 720x1280 exports fully decode,
retain 124 frames and exact 124/24-second picture/audio presentation; unaligned
audio cosine against the 248000-sample/channel source is 0.997047 after AAC.
That waveform check is exporter evidence, not synchronization of mouth motion.
No source media, portrait, prompts or native receipts are bundled or cleared for
the public entry. All files remain in ignored private evidence. Both normal LTX
workers are restored, protected process identities retained, and temporary H3
services, tunnel and both safety timers are closed. No Cloud/Grid credit is used.

The owner subsequently rejected both FastH3 review clips for poor lip alignment.
Retain that as a failed human quality review, not merely an unmeasured success.
In particular, the video/image job had no audio input to its sampler; placing
the original sound over its generated picture could not enforce speech timing.
The audio/image job did receive native H3 reference-audio conditioning, but that
different mechanism also failed this owner's review. This does not establish
that all H3 audio workflows fail; it disqualifies these two clips as lip-sync
examples.

### Original LTX fixed-audio control

The saved earlier car-scene receipts identify LTX-2.5 Distilled BF16, not H3.
They encode the exact source WAV through the LTX audio VAE, apply a zero audio
noise mask and concatenate that fixed latent with the video latent before
sampling. A composition-matched opening image supplies appearance and framing.
The sampler uses eight manual-sigma Euler ancestral CFG++ steps at CFG 1.
This is one pass, not the studio's newer two-pass spatial-upscale workflow.

Two new owner-requested official-SDK controls reuse those actual saved graphs
with the new private performance scene: one audio/image, one video/image/audio.
Both use seed 2026, a common scene opening, exact first-section source audio,
576x1024 and 121 frames at 24 fps. The opening is the first frame of the already
saved H3 video/image result, proportionally padded rather than stretched; no
new image model was run and no raw portrait is flashed at frame zero. The
video-guided control retains the earlier 0.85 Canny-guide and 0.75 opening
strengths, but removes the old top-strip exclusion, which would erase the new
subject's head. This leaves source caption edges in the guide.

Both completed with exactly one native dispatch each. Downloaded output and
uploaded image/audio/video hashes match the separate native receipts; executed
graphs match the frozen graphs except for materialized asset filenames. Both
native clips completely decode to the expected dimensions, 121 frames and
24 fps. Disclosed five-second review copies retain the first 120 picture
frames and 240000 source samples/channel; source-audio cosine after AAC is
0.997041. That is soundtrack/export evidence, not a phoneme alignment score.
Observed submit-through-download times are 113.88 and 126.07 seconds, not a
matched speed benchmark. No Cloud/Grid credits, production dependency changes
or service restarts were involved.

Sampled audio/image frames retain the intended opening appearance more closely
and show active articulation, but unwanted lettering appears near the end.
Video-guided frames follow more original poses/gestures, drift toward the
original hairstyle and regenerate garbled source captions. Keep those flaws;
neither is a qualified general identity-replacement showcase. Word-level lip
alignment still needs direct audiovisual review of the new clips. The owner's
earlier favorable car-scene review is not proof that this different scene passes.
Private media, portraits, source receipts and operational details remain ignored
and are not cleared for the public competition entry.

### FastH3 Omni speech-anchor follow-up

Naming clarification: the preceding fast native clips already use FastH3 Omni
NVFP4 QAD. "Omni" is not another checkpoint selected by removing "Fast" from
its name. Standard MiniMax H3 is a separate base-model comparison and was not
executed in this follow-up.

One additional owned-runtime SDK job keeps the existing eight-step FastH3 Omni
checkpoint and uses `MiniMaxH3AddGuide` to anchor the actual speech and scene
opening at target frame zero. This is native timestamped conditioning, not the
previous standalone reference-audio slot or a soundtrack-only mux. It is still
not LTX's zero-noise fixed audio latent, and it cannot be labeled a lip-sync
guarantee. The opening is the exact same image used by the preceding LTX pair.
Compared with the earlier FastH3 audio case, both the opening/reference image
and audio conditioning change; this is not a one-variable experiment.

The single native job completes at 768x1344, 124 frames and 24 fps. Uploaded image
and speech hashes, the executed graph and the downloaded output match the
independent native receipt. Complete native/review decode passes. A disclosed
five-second review copy preserves the first 120 frames and original uploaded
voice, not a clone; source waveform cosine is 0.997041 after AAC. The LTX/FastH3
side-by-side plays that same original voice once, with both panels starting at
zero and exact five-second audio/video track clocks. It does not compare model
voice reconstruction. The observed 202.41-second submit-through-download time
is not a speed benchmark.

Sampled frames retain the scene and appearance with comparatively stationary
framing; clothing lettering remains distorted. These are image observations,
not a phoneme or all-frame artifact score. Direct audiovisual review remains
necessary. Exactly one new generation ran, without Cloud/Grid credits, a new
download or a public/default model change. Both normal LTX workers are restored,
protected process identities retained, and temporary H3 services, tunnel and
restoration timer are closed. Private inputs/results are not submission assets.

## Composition-matched opening-look test

A second three-way pendulum test uses the same neutral content prompt, seed 42,
guide strength 1.0 and byte-identical normalized source video. It compares no
opening image, the original first frame, and a deliberately amber/copper edit of
that first frame. The video prompt does not request amber colors. The edit was
made with native FLUX.2 Klein 4B FP8 through the official Cloud SDK as a control
experiment, not a selection of the app's image model. Its single four-step edit
took 16.68 seconds from submission through image download.

| LTX opening condition | Comfy execution | Submission through download |
| --- | --- | --- |
| No image | 40.01 s | 182.84 s |
| Original first frame | 38.53 s | 98.85 s |
| Amber/copper edited frame | 85.48 s | 88.02 s |

The original-frame and no-image controls queued behind the amber render; cache
state also differs. These timings are not an optimization benchmark. No Cloud
credits were used for the three video renders; the earlier still-image edit
consumed Cloud allowance, with exact billing to be reconciled in the usage page.

Sampled frames 0, 24, 48, 72 and 96 show that the original anchor retains the
dark dial, white marks and guard-rail appearance much more closely than the
unanchored result, which invents a pale dial and changes the tick marks. The
amber edit's warm lighting and materials persist beyond the first frame while
the bob follows the gross source swing. The edit itself changes some framing
and geometry; no anchor can guarantee undoing those changes. This is useful
evidence for a composition-matched opening-image input, not identity editing,
frame-perfect timing, arbitrary style transfer or a general quality guarantee.

The app now accepts that optional image and exports it with the take. Motion
strength remains CLI-only. The owner requested MOSS Image as the next editor to
evaluate; the live Gallery catalog advertises `MOSS Image SFT BF16` with one
online worker and source-guided img2img. Advertisement is not proof that its
edits pass this creative-quality test. Native worker tests are recorded below;
the billed Grid API route has not been tested in this entry.

The new opening-image input also completed a real browser-created LTX take in
41.39 seconds from submission through download. Its exported video is five
seconds, 1536x896, 24 fps and 120 frames. The same completed take, prompt, seed
and opening-image preview recovered after a reload. Creating a revision retained
the image and incremented the seed without submitting another job. The actual
browser-downloaded `look.png` hashes identically to the normalized render input.
At 1280-pixel desktop and 390-pixel mobile widths, the controls fit without
horizontal overflow, and both comparison videos reached playback position 2.0
seconds. These UI checks do not establish quality on untested subjects.

## Real WebM and recorded-audio check

The CC0 turbine source was cropped to the same people/brand-free upper region,
encoded as VP8 WebM, and kept its original 44.1 kHz stereo Vorbis audio. A real
browser upload now creates a separate H.264/AAC preview rather than serving WebM
bytes with an MP4 media type. The original upload is retained unchanged for
render preparation; it is not re-encoded from the preview.

The browser loaded the 768x448, 24 fps preview and cleared the previous clip's
opening-look selection. One LTX-2.5 take completed through the official SDK on
owned hardware in 47.39 seconds from submission through download. No Cloud
credits were used. Its video contains 120 frames at 24 fps. AAC packet padding
makes the MP4 container 5.018 seconds, while the video stream is five seconds.

The decoded PCM SHA-256 for the first five seconds is identical in the browser
preview, normalized render source and final export:

```text
4c9b5b8138e38d90eabfb5e3b625a15538c31f717744ae883a080afd458b0d7a
```

This proves preservation of the normalized recorded soundtrack for that window,
not lossless preservation of the original Vorbis encoding or a listening review.
The night treatment changes thin turbine structures and blade shapes, including
invented tower-like details. It is a technical QA result, not an accepted
showcase or evidence of faithful turbine geometry.

## Native MOSS opening-look tests

The existing owned RTX 5090 worker completed four native image edits through the
official Comfy SDK and a loopback-only official proxy. Its original ComfyUI and
Grid bridge services stayed running; no models or production settings changed.
These tests bypassed Grid billing and reward accounting and used no Cloud
credits. They do not qualify the authenticated or billed Grid API path.

The graph matches the deployed worker's source-guided img2img mechanism:
`moss_image_sft_bf16.safetensors`, `qwen3.5_9b_int8_convrot.safetensors`,
`flux2-vae.safetensors`, image scaling to 1344x768 with Lanczos/center crop,
VAE encoding and 50 Euler/simple steps at CFG 3. The installed ComfyUI 0.41.0
MOSS model class supplies flow shift 5. There is no optional LoRA or multimodal
image-instruction encoder in this tested graph. All four use the same source
first frame, target-scene caption, negative prompt and seed 42.

| Denoise | Comfy execution | Submission through download | Still-image assessment |
| --- | --- | --- | --- |
| 0.40 | 26.34 s | 55.80 s | Very close to the original, little requested relighting |
| 0.65 | 27.40 s | 30.76 s | Subtle warm treatment, recognizable source composition |
| 0.75 | 26.22 s | 30.68 s | Stronger warm/copper look with broadly similar composition; some detail changes |
| 0.85 | 26.31 s | 30.68 s | Strong amber look, but unacceptable bob/stem and guard-rail changes |

The 0.40 test queued behind 0.65, so its 55.80 seconds is not compute time.
These are one-case measurements, not a hardware benchmark or universal quality
ranking. Lower denoise is conservative; higher denoise is not automatically
better. The 0.75 image is a candidate for this clip, not a new Grid-wide default.

That actual MOSS image was uploaded into the browser app as the opening look.
One LTX-2.5 BF16 take then completed in 47.36 seconds from submission through
download: five video seconds, 1536x896, 24 fps and 120 frames. The neutral video
prompt does not request amber colors. Frames 0, 24, 48, 72 and 96 retain the
warmer look while following the gross bob swing. Fine dial details and rails
change, and MOSS's source crop differs slightly from LTX's letterboxing.
This proves a native MOSS-image-to-LTX-browser path, not exact identity, timing,
arbitrary instruction editing, general style transfer or a finished showcase.
That first test loaded the separately generated image through the existing
opening-image input. A subsequent integrated test is recorded below.

## In-app MOSS-to-LTX check

The app generated a warm/copper opening image from the pendulum upload through
the official SDK on the owned RTX 5090. It used the same model/encoder/VAE and
50-step preset above, seed 42 and denoise 0.75. The generic negative prompt no
longer includes the pendulum-specific phrase "extra spheres". The look completed
in 30.71 seconds from submission through image download and survived a browser
reload with its saved job, prompt and source intact.

An explicit separate click then submitted one LTX-2.5 BF16 take with that image
and the neutral motion prompt, completing in 49.55 seconds through download.
The exported video is five seconds, 1536x896, 24 fps and 120 frames. Both browser
videos reached position 2.0 seconds with the warmer treatment visible on the
result. Gross swing and framing remain recognizable; fine geometry still
changes. These timings exclude source preparation and local final export and
are not a performance benchmark. No Cloud or Grid credits were consumed.

A second MOSS look used a cool-light caption at denoise 0.65. While it was
rendering, the browser uploaded the separate turbine clip. After completion,
that new clip still had no opening image or unrelated look history. Reloading
retained the new source and draft rather than reverting to the last video take.
Selecting the earlier pendulum take exposed both of its generated look choices;
neither look generation automatically created a video take.

Actual browser downloads of the MOSS workflow and source PNG hash identically
to the saved render inputs. Exported take settings include both prompts, seeds,
MOSS denoise and relative asset names, without credentials or runtime endpoints.
The full-size Look view and comparison controls fit 1280-pixel desktop and
390-pixel mobile widths without horizontal overflow. Thumbnail captions remain
visible and unchanged polling does not recreate every video thumbnail.

Unit coverage additionally exercises duplicate request IDs, no-ID ambiguity,
same-job restart recovery, separate image/video limits, unavailable models and
look/video/Cloud credential separation. These are reliability checks, not
evidence of general image-editing quality or the billed Grid routing path.

## Native guidance and additional footage

The publisher's [MOSS ComfyUI guide](https://github.com/OpenMOSS/MOSS-Image/blob/main/comfyui/README.md)
recommends negative-branch skipping at single layer 22. The initial tests above
did not include that node. A matched native A/B on candle, bubble-wand and
pendulum images changed only that guidance, keeping input PNG bytes, seed 42,
prompts, model files, 50 steps, CFG 3 and denoise 0.75 fixed.

| Opening-look case | Without layer skipping | With layer 22 |
| --- | --- | --- |
| Candle | 30.67 s | 30.71 s |
| Bubble wand | 30.74 s | 30.72 s |
| Pendulum | 30.71 s | 30.74 s |

All times are submission through download on the owned RTX 5090, excluding
preparation/normalization. Visual differences are modest, not a demonstrated
general quality improvement. The preset now follows the publisher's guidance,
and new jobs/settings record it. Previous exports retain their actual older
preset; recovery does not regenerate an image with new settings.

Two additional LTX-2.5 camera-footage tests completed on owned hardware:

| Case | Opening image | Video submission through download | Assessment |
| --- | --- | --- | --- |
| Candle | MOSS 0.75, before the guidance change | 67.63 s | Flame motion and the general candle composition remain; warmer lighting and a greener wax pool appear, but the requested emerald candle body is not convincingly achieved |
| Bubble wand | MOSS 0.75, with layer 22 | 63.08 s | Broad wand movement follows the source; thin rims and individual bubbles differ, while the requested midnight-teal tabletop is not achieved |

Both videos are silent, five seconds, 1536x896, 24 fps and 120 frames. They
contain the new AI-generation metadata. No Cloud or Grid credits were spent.
Matched frame indices 0, 24, 48, 72 and 96 were inspected; this is not a claim
of exact bubble physics or flicker-free video. Neither is an approved showcase.

A separate candle still at denoise 0.90 produced a stronger emerald material
change but enlarged the candle and altered framing. That setting remains
experimental and is not added to the app's three strength choices. A subsequent
layout-prompt test is evaluation evidence, not a new public control or a passed
video-quality gate.

That layout-prompt experiment subsequently produced a more composition-matched
emerald candle, and one LTX take completed in 61.29 seconds through download.
Sampled frames retain the emerald treatment across the full five-second window;
the rim, wax geometry and flame shape differ from the source. It is a promising
candidate requiring full-motion review, not an approved showcase or evidence
that app-default look strength can reproduce it. The matched layout at denoise
0.75 retains more source appearance and does not make the same emerald change.

The alternative flameless-candle source was rejected because its active picture
is a narrow portrait within large black bars; the previously inspected spinning
top has hands throughout. Do not count rejected inputs as showcase examples.

The known completed pendulum job was also retrieved after restarting only the
isolated SDK proxy, using its existing state and job ID. Its local export was
refreshed with AI-generation metadata without a new GPU render. This tests
same-job recovery across proxy restart, not arbitrary network-failure recovery.

One new look also completed through the actual app with the layer-22 preset in
30.67 seconds. Its saved job records `[22]`. A browser download of that look,
before any new video submission, hashes identically to the normalized image.
The app still had five video takes after this look-only generation and export.

## Further camera footage and prompt separation

All three new originals above matched their file-specific Commons SHA-1 records.
The selected five-second windows were inspected for people and branding. New
MOSS edits used the existing 0.75 preset, seed 42 and layer-22 guidance on the
owned RTX 5090. No new weights, adapters or production configuration were needed.

| Opening look | Submission through download | Assessment |
| --- | --- | --- |
| Forest waterfall | 55.85 s | Recognizable cascade arrangement with cooler, luminous forest lighting; ledges and foliage change |
| Lava lamp | 30.64 s | Requested sapphire liquid is not achieved and the wax blobs disappear; rejected, no video submitted |
| Mountain cloud | 30.70 s | Coral/amber light appears, but the cloud enlarges and some foreground/mountain geometry changes |

The waterfall look queued behind the lava-lamp job, so these are not comparable
compute durations. Both candidate videos used the same owned LTX-2.5 BF16
runtime and official SDK route as earlier tests, with no Cloud or Grid credits.

The waterfall was uploaded into the actual app with its reviewed MOSS opening
image. One explicit take completed in 52.80 seconds through download. Its prompt
repeated the desired blue-hour/cyan lighting, and sampled frames become
progressively bluer. A deliberate matched revision kept the normalized source,
opening image, seed and graph unchanged, but used a motion-focused prompt that
asked to retain the opening appearance without repeating the blue lighting.
That take completed in 112.96 seconds through download and showed much less
color drift at frame indices 0, 24, 48, 72 and 96. Transfer/cache conditions differ;
this is prompt evidence on one case, not a speed benchmark or universal fix.

The actual app take contains 120 video frames at 24 fps and 1536x896. AAC padding
makes the container 5.012 seconds. The first five seconds of decoded PCM match
in the app's browser preview, normalized render input and export:

```text
73e993905c833e7ddb123f4ad010afb29eb3dd51ef4a757d94a9cf4119f3ab13
```

This is normalized-audio preservation, not a listening review or lossless
preservation of the original Opus encoding. The real browser comparison also
revealed that source-preview padding could outlast the result. Either video's
end now stops the pair; a completion latch prevents a subsequent near-five-second
timestamp from resetting the displayed clock to 0:04. Replay and scrubbing clear
that latch. A Node event-handler test uses the actual inline app script; real
browser/media checks remain necessary.

The mountain's single-opening-frame LTX take completed in 130.91 seconds through
download, but its amber cloud fades over the shot even with a motion-focused
prompt. It is not a passed showcase. A closing-look test evaluated native
`LTXVAddGuide` at frame 120, strength 0.7 in both passes, with guide cropping
before decoding. Comfy's [official first/last-frame blueprint](https://github.com/Comfy-Org/ComfyUI/blob/master/blueprints/First%20%26%20Last%20Frame%20to%20Video%20%28LTX-2.5%29.json)
uses that native node; the blueprint alone does not establish quality of our
combined Canny/keyframe experiment. The initial probe was CLI-only.

The three matched closing-look experiments subsequently completed. Each keeps
its baseline source bytes, opening-image bytes, video prompt and seed. A MOSS
edit of normalized source frame 120 uses the same look prompt, denoise and seed
as its opening edit; native LTX guide/crop nodes add that image to both passes.

| Closing-look video | Submission through download | Matched-frame assessment |
| --- | --- | --- |
| Mountain cloud | 46.78 s | The amber treatment remains across the sampled sequence instead of visibly fading as in the single-anchor baseline; cloud scale and terrain still differ from the original |
| Forest waterfall | 50.63 s | The target treatment remains; the neutral-prompt single-anchor baseline was already fairly consistent, so the incremental gain is smaller |
| Candle | 53.66 s | The emerald treatment remains; the rim/body still differ from the original, and its images use the private 0.90/layout experiment rather than an app default |

All three exports have 120 video frames at 24 fps and 1536x896. The waterfall's
normalized-audio hash above is unchanged; the other sources remain silent.
These are matched-frame observations, not proof of frame-perfect motion,
absence of flicker, or three approved submission examples. The generated
closing images can themselves drift in composition. No Cloud or Grid credits
were consumed.

The reproducible CLI now supports `look --frame-index 120` and
`reshoot --closing-frame`, with distinct asset binding and persisted closing
settings. Its generated graph matches all three actually executed experiment
graphs. No private helper is required to construct it. The subsequent browser
and Cloud checks below qualify the same execution graph, not general fidelity.

An earlier mountain attempt timed out without a job ID. A read-only check found
neither its idempotency key nor any new recorded job in the isolated proxy. The
failed attempt was preserved, and one explicit new attempt completed after the
SDK request timeout was increased from 30 to 120 seconds. There was no automatic
resubmission. This observation does not authorize retrying other ambiguous jobs:
their actual backend state must be reconciled independently.

## Two-look browser and Cloud qualification

The actual browser app uploaded the CC0 mountain Ogg source, generated one MOSS
image from normalized frame 0 and another from frame 120, and then submitted one
explicit two-look LTX take. Both image jobs used the same target-scene caption,
seed 42, denoise 0.75 and layer-22 preset, completing in 30.7 seconds each through
download. The video used a separately edited motion-focused prompt and completed
in 46.44 seconds through download on the owned RTX PRO 6000. Neither image job
automatically submitted a video. The two images and selected frame survived reload.

An official Cloud SDK run of the same graph, prompt, seed and byte-identical
normalized source/opening/closing inputs completed in 167.59 seconds through
download, including queuing. Cloud billing reports 55.812 GPU seconds on
`rtx_pro_6000`; the rounded credit display increased by approximately 15 credits.
No top-up or replacement job was submitted. The Cloud and browser exports each
contain 120 frames at 24 fps, 1536x896 and five seconds, with no audio for this
silent source. Matched frames 0, 24, 48, 72 and 96 retain the target treatment on
both backends; the generated cloud and terrain still differ from the original.
This is not a cross-hardware determinism or minimum-VRAM claim.

The actual browser Export menu downloaded distinct opening/closing images, both
MOSS workflows, the closing source PNG, take settings and video. Downloaded bytes
matched their saved inputs/results. The closing source PNG hashes identically
to frame 120 extracted independently from that take's normalized source video.
The two MOSS workflow graphs are intentionally alike; their different source
PNGs and frame indices are identified separately in the take settings. Provider
asset names still need SDK rebinding when reproducing an exported graph.

Replaying the same closing-image and video request IDs returned their existing
jobs without incrementing the counters. A controlled recovery test preserved
the local video under a backup name, restarted only the local app, and used the
browser's Recover result action. It retrieved the same saved provider job,
preserved the idempotency key and original timing, and recreated a byte-identical
video. The counters stayed at seven takes and five generated looks. This is
same-job/local-export recovery, not a claim that every network-failure mode passed.

New take retained both reference IDs and incremented the visible seed from 42 to
43 without submitting. Opening/closing histories are filtered by source and frame;
choosing another opening clears the selected closing reference but retains its
history. API tests reject generated references belonging to another source or
frame and reject a closing-only take before spawning a process. Legacy opening
requests without a frame field remain idempotent and are treated as frame 0.

At 1024-pixel tablet and 390-pixel mobile widths the filled role controls fit
inside their parent with no horizontal overflow. Both comparison videos loaded
without media errors. Node event-handler tests exercise late-result role/source
isolation in the actual inline script; real browser checks complement those
tests. Status polling now uses a five-second SDK timeout independently of the
120-second media-transfer timeout. The original soundtrack-preservation evidence
remains the recorded-audio waterfall and turbine cases, not this silent mountain.

## Prompt usability and denser temporal inspection

The three closing-look candidates were decoded through all 120 exported frames.
Each source and output has 120 distinct decoded low-resolution RGB frames.
Quarter-second contact sheets, including frame 119, retain the edited treatments,
but the waterfall's generated flow looks smoother and less turbulent, and the
candle's shape and framing remain different from its source. The candle still
depends on the private 0.90/layout experiment, not an app-default look. These
are not three approved showcases or a passed full-motion human review.

At 192x112, maximum consecutive-frame mean absolute RGB differences are:

| Candidate | Source | Generated |
| --- | --- | --- |
| Mountain | 1.121 | 0.658 |
| Waterfall | 8.182 | 1.683 |
| Candle | 1.242 | 0.492 |

These global values detect neither local geometry errors nor accurate motion.
Lower differences are not a quality score: an overly static result can also
score low. The waterfall's first-five-second normalized PCM hash remains the
same in source and export. Silent inputs remain silent. Listening review and
unfamiliar-viewer acceptance are still outstanding.

Two matched owned-worker LTX tests changed only the video prompt to the same
general motion-focused wording, keeping source, opening, closing and seed bytes
fixed. Mountain completed in 51.36 seconds and waterfall in 113.39 seconds through
download, including different queue/cache conditions. Both export 120 frames at
24 fps and 1536x896; sampled sequences retain their looks and the waterfall's
normalized soundtrack hash is unchanged. These tests support an editable shared
motion starting point, not exact timing, fixed geometry or a universal default.
No Cloud or Grid credits were used.

The app now keeps the image art direction separate from Motion & camera video
instructions. One actual browser take with the existing mountain look images
completed in 46.81 seconds through download. The browser-downloaded settings
contain both directions independently; the executed prompt in the saved provider
record matches the exported motion prompt rather than the image caption. The
same take and both directions survive reload, with no additional submission.
Legacy takes without the new fields retain their original executed prompt.
The expanded motion controls and loaded comparison were also checked at 1024-
and 390-pixel widths without horizontal overflow; both textareas fit their
parents and both videos loaded without media errors.

During clean-install review, Cloud's old unconditional connected flag was found
and removed. A read-only request to the documented Cloud user-status endpoint
succeeded with the existing credential, without a render. Tests reject missing
keys, wrong target hosts, rejected/waitlisted access, malformed status responses
and timeouts before a job directory is created. Display polling caches readiness
for 15 seconds; submission rechecks even if that cached display was healthy.
Cloud job execution still uses the official SDK. This preflight does not prove
available credits, queue capacity or model files.

## Actual preset qualification and image-editor comparison

Six native MOSS stills tested the actual Warm Film and Blue Hour browser text
at the default denoise 0.65, seed 42, layer 22 and unchanged sampling on mountain,
waterfall and pendulum inputs. Each completed in 30.69-30.76 seconds through
download. The generic captions make only subtle changes on the mountain and
pendulum; the waterfall Blue Hour result adds a yellow lamp. These do not pass
the intended default-look quality gate. Do not present them as curated successes.

A second six-image, prompt-only comparison kept those same inputs and settings.
More explicit amber/copper and cyan/teal palette captions, with no added lamps
or fixtures, completed in 30.67-30.72 seconds each. They reduce that added-fixture
problem but still do not reliably achieve the requested strong looks. The
proposed text has not replaced the app presets on the strength of these results.
No Cloud or Grid credits were used for the twelve native images.

Four native Cloud Klein 4B FP8 edits used the same palette captions and
byte-identical source PNGs on mountain and waterfall. This reuses the earlier
qualified four-step reference-latent graph, not a closed partner node or a new
video model. They completed in 7.17-8.99 seconds through download. The requested
palettes are much stronger in these examples, sometimes too dark or saturated.
This compares two practical workflows, not an isolated model benchmark: pixel
sizes, conditioning mechanisms, step counts and hardware differ. It does not
establish universal superiority or minimum VRAM. The official
[Klein 4B model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
identifies image editing and Apache-2.0; do not substitute the differently
licensed 9B model. LTX 2.5 remains the app's video model. Any default image-editor
change remains subject to the owner's requested MOSS preference and review.

Four further Cloud Klein edits prepared opening and closing material-change
references for a paper-diorama waterfall and porcelain/chrome pendulum. The
waterfall pair is a candidate. The pendulum closing edit duplicates the bob and
was rejected before video submission; its candidate video uses only the opening
image. The rejected image is preserved, not automatically replaced or reported
as a successful reference.

A separate three-slot browser session retains the original QA history. Its
paper-waterfall take completed through the official SDK on owned LTX hardware
in 118.86 seconds through download. Sampled frames retain the paper appearance,
but the paper ribbons have much less evident flow than the real water. It is
not a passed source-motion showcase. The selected look images were uploaded
through the existing image-input feature; this does not claim an integrated
Klein generation button. No replacement video was submitted.

The porcelain/chrome pendulum browser take completed in 51.11 seconds through
download, using its accepted opening image only. Its 120 exported frames at
24 fps retain the ivory/cobalt/red treatment. Matched source/result frame pairs
at half-second intervals show the bob following the gross swing arc and timing;
the rails and dial geometry still differ. This is a stronger material-change
candidate, not exact geometry or motion reconstruction. The pendulum source is
silent. The paper-waterfall export retains the source soundtrack: the first
five seconds have identical decoded PCM hashes after the same normalization.

The same browser then used New take to revise that pendulum from porcelain to
the earlier reviewed MOSS copper/amber opening image. The source stayed the
same, the seed advanced to 43, and both art and video direction were explicitly
changed before one new submission. It completed in 42.01 seconds through
download, with 120 frames at 24 fps and no audio track, matching the silent
source. Half-second source/result pairs show the broad swing continuing while
the warm copper appearance persists; fine geometry and bob position differ.
The earlier MOSS image predates layer-22 guidance and is not relabelled as using
it. This is an uploaded-image revision, not another in-app MOSS generation.
Reload restored Take 03 with the same result and all three takes; playback
reached the end on both comparison videos without media errors. The actual
downloaded take settings retain seed 43, the changed art direction, the exact
executed motion prompt and the opening-image filename. Uploaded images do not
claim generated-look provenance in that export. No replacement job or expanded
session limit was used; the separate session ends at its original three slots.

### Existing Grid MOSS route

A read-only check of the public [media catalog](https://api.aipowergrid.io/v1/status/models)
on October 21 found `MOSS Image SFT BF16` advertised with `txt2img` and `img2img`.
The [price book](https://api.aipowergrid.io/v1/pricing) configured USD 0.01 per
image. Neither signal is a guarantee of capacity or successful rendering. The
existing Grid image endpoint accepts an inline source image with the prompt,
model and seed; its capability-aware recipe selects image-to-image execution.
No billed Grid job was submitted for this check. The app's MOSS look button
still uses the owned runtime via the official Comfy proxy, not that endpoint;
these native tests do not qualify Grid billing, recovery or an API integration.
No additional MOSS installation is needed merely to use the existing worker.

A private, attributed 15-second candidate reel combines the earlier coral cloud,
cool forest and copper pendulum source/render pairs, with visible AI labels and
geometry limitations. It is review material, not the required 60-90 second app
demo, not three approved showcases and not a published submission.

## Explicit Cloud image-to-video browser path

The explicit `--look-engine klein-cloud` configuration now exposes the previously
tested native four-step Klein 4B reference editor in the browser. MOSS remains
the default; this is not an automatic fallback or a public Grid integration.
The test used a separate directory capped at two look images and one video,
with the same licensed real-camera mountain Ogg input. Warm Film was explicitly
selected and both references were reviewed before the video action.

| Explicit browser action | Elapsed through download |
| --- | --- |
| Generate opening image, normalized source frame 0 | 9.11 s |
| Generate closing image, normalized source frame 120 | 12.49 s |
| Generate LTX 2.5 video with those two references | 79.47 s |

All three jobs executed through the official Comfy SDK on Cloud. No local GPU,
second local proxy, closed partner-model node or alternative video model was
used. The provider's GPU model was not established for this particular run.
The completed video has 120 frames at 24 fps, 1536x896 and no audio track,
matching this silent input. Half-second frame pairs show the warm treatment
persisting while the broad cloud movement and fixed mountain framing continue.
Individual cloud contours differ and the preset makes the foreground and sky
very dark. This is portability and bounded-workflow evidence, not exact motion,
general best-default quality or a third approved showcase. The usage display
increased by roughly 18 rounded Cloud credits across the three jobs; this is an
observed aggregate estimate, not an exact per-job invoice or future price quote.

Reload restored the same completed take, both generated references and the
original two-look/one-video counts. Both comparison videos reached five seconds
with ready media and no playback errors. Desktop/tablet and 390-pixel mobile
screenshots show no horizontal overflow; the MOSS-only strength control is
absent. The take-settings endpoint identifies Klein for both generated images,
separate art and executed video directions, seed 42, and opening/closing source
frame roles 0/120. Denoise is null, not silently applied or claimed as MOSS
guidance. The existing export controls expose both image workflows and source
PNGs. No replacement image/video or expanded session limit was used.

Regression tests also cover a saved Cloud look recovered after changing the
next-look engine to MOSS: they assert retrieval of the original Cloud job, not
another image submission. That cross-configuration check is a test, not a claim
that the real browser session switched engines. The 135-test suite passes on
Python 3.12 and on Python 3.11 using the built wheel outside the checkout.
Wheel and source-distribution listings exclude run state, generated media and
credentials and retain required license notices. These developer checks do not
replace the still-required unfamiliar-person install/usability test.

## Recorded revision and private demonstration draft

One bounded follow-up produced four Cloud look images and three LTX 2.5 videos,
without replacement jobs. The real browser session uploaded the same licensed
pendulum source, generated its porcelain reference, rendered a take, used New
take to change art direction to copper and seed to 43, explicitly generated the
new reference and take, returned to the earlier version, and exported settings.
Its two normalized video source files are byte-identical. The actual browser
download identifies LTX 2.5, seed 42, Klein 4B image provenance and relative
source/reference filenames; it contains no backend endpoint or credential.

| Job | Elapsed through download |
| --- | --- |
| Porcelain opening reference | 14.29 s |
| First porcelain video, browser | 48.26 s |
| Copper revision reference | 21.44 s |
| Revised copper video, browser | 242.36 s |
| Jade candle opening reference | 11.88 s |
| Jade candle closing reference | 21.83 s |
| Jade candle video, explicit CLI after image review | 206.66 s |

Video times include different Cloud queue/transfer conditions and are not GPU
benchmarks or latency promises. The provider GPU type was not established for
these jobs. The usage display increased by roughly 45 rounded Cloud credits
across the four-image/three-video run; this is an aggregate observation, not
an exact per-job invoice or future price quote. Each video has 120 frames at
24 fps, 1536x896 and no soundtrack,
matching the silent inputs. The jade case uses the table's hash-verified Blue
candle burning source by Jahobr, not the separate flameless-candle asset.

Half-second source/result pairs show both pendulum treatments following the
broad swing while maintaining their distinct materials. The reference edits
change the bob's mount details, dial and rails; those differences remain visible.
The candle's jade material persists while its flame leans and flickers, but vein
patterns and rim details vary. Do not call these exact geometric reconstructions.
Whole-frame luma means were measured on all 120 frames at 192x112 using FFmpeg
signalstats. Maximum consecutive mean changes were 0.2650 for porcelain, 0.1538
for copper and 0.4874 for jade, on the 8-bit scale. These are limited checks for
large brightness jumps, not proof that local detail is flicker-free.

The real browser also verifies the new revision state: changing art direction
marks a selected generated reference as using an earlier direction, with no
dispatch or reference deletion. Choosing the new matching image clears it.
Motion-only edits do not produce that state. A fresh local origin now receives
the configured Cloud palette after startup instead of retaining a prematurely
autosaved temporary default. Regression tests additionally preserve user text
typed before configuration arrives; that early-input race is a test, not a
claim that the real session deliberately induced network delay.

The private draft demonstration is 79.08 seconds, 1920x1080, 24 fps and 1,898
frames. It includes fourteen real-app capture chapters, the actual material
revision, retained takes, export controls and three camera-source comparisons:
pendulum, mountain and candle. The source captures contain 657 browser screenshot
samples with wall-clock timestamps, resampled during editing; they are not
synthetic UI states or a claim of native 24 fps screen capture. Generation waits
are explicitly shortened, and captions retain actual completed job times.
The full video decodes without errors. Credits, modification notices and the
proposed ShareAlike media terms accompany the ignored draft. No music, voice,
private account data or infrastructure addresses are included in the video.
It is an owner-review draft, not a published or submitted entry, and its three
examples are not a claim that every quality or release gate has passed.

## Stronger MOSS material-caption follow-up

A fixed six-image follow-up tested the same generic copper and porcelain
captions on the pendulum, Blue candle burning and bubble-wand sources. It kept
seed 42, 50 Euler/simple steps, CFG 3 and negative-branch layer 22, while using
the existing Strong denoise value of 0.75. Each image completed through download
in 30.60-30.99 seconds on the owned MOSS runtime. This is a proposed material
caption test, not qualification of the current default denoise 0.65 or a new UI
preset. No image editor, sampler or default was silently changed.

The acceptance criteria were a clear material change, recognizable source
subject/framing, and no additional subject or fixtures. All six outputs were
retained and inspected, not only the favorable candle pair.

| Source | Copper / porcelain observations | Disposition |
| --- | --- | --- |
| Pendulum | Distinct materials and broad dial composition, but cups/vase-like decorative forms appear around the rails and fine geometry changes | Fails the no-added-objects preset criterion |
| Candle | Copper/amber and ivory/cobalt ceramic appearances are obvious; the single flame and general composition remain. The wax body becomes a more bowl-like vessel | Accepted for a limited video test, with that shape change disclosed |
| Bubble wand | The thin loop is lost, replaced by molding/shelf-like geometry and invented vessels | Reject both; do not send them to video |

The two reviewed candle references then completed separate owned LTX-2.5 BF16
SDK renders with the same source bytes, seed 42 and the app's default motion
direction. Each used one opening image, no closing guide and no automatic retry.
Copper took 52.38 seconds and porcelain 59.33 seconds through download, excluding
local preparation/export. These timings are not a hardware benchmark or a price.

Both exports fully decode to 120 frames, 1536x896, 24 fps and five seconds. Their
normalized workflow source is 768x448 with 124 frames, including the existing
tail padding; the review compares its first 120 frames. The original input is
silent, and both exports are silent. A private five-second source/copper/porcelain
comparison retains attribution and an AI-generation notice.

Sampled frames show the two material treatments persisting, the flame leaning
and changing height, and the broad stationary framing holding. Flame shape and
fine ornament details differ from the source and between takes. This does not
establish frame-accurate flame motion, absence of local flicker, arbitrary edit
fidelity or general-purpose MOSS preset quality. These native tests used no
Cloud or Grid credits and changed no production services. MOSS remains the
selected default; its original failed Warm Film/Blue Hour tests remain failures.

## Vertical And Square Source Windows

Two new owned-worker controls use the existing permissioned, silent Blue candle
burning source with source start 1.0 second, seed 42 and the same single-candle
caption. No look image, source-audio conditioning or character reference is
supplied. Both execute through the official SDK and existing Union-Control
two-pass BF16 workflow, without Cloud/Grid credits or service changes.

| Format | Input canvas | Export | Observed render/download time |
| --- | --- | --- | --- |
| Vertical 9:16 | 576x1024 | 1152x2048 | 83.21 seconds |
| Square 1:1 | 640x640 | 1280x1280 | 51.83 seconds |

Both exports independently count and decode all 120 frames, at 24 fps and
exactly five seconds, with no audio as expected for this source. First, middle
and last frame samples show a single blue candle and changing flame shape.
This is not an all-frame flicker score, benchmark, exact-motion claim or
qualification of Cloud, opening/closing looks, audio or arbitrary subjects at
these new dimensions. Preserve the separate rejected material-edit results.

The real local browser selects square at source start 3.25 seconds and loads a
640x640 preview; vertical loads 576x1024 for the same range. Desktop 1440x1000
and mobile 390x844 checks show no horizontal overflow. Changing framing never
submits inference. A displayed start-time change disables generation until
Apply commits the range, preventing a stale preview/render discrepancy found
during the test. After browser reload and a real local app restart, framing,
numeric start, slider position and source URL all restore consistently.
These browser checks submit no new image/video job. The native controls above
are separate CLI executions, not an end-to-end browser-render qualification.

Hermetic tests additionally verify later source-video content, selected audio
frequency, finite/valid offsets, portrait/square reference normalization,
idempotent API dispatch, saved export dimensions, same-job look recovery in all
three formats, and rejection of references for a different source range or
framing. They do not replace real model or unfamiliar-human quality tests.

## In-App Speech Workflow Comparison

Three new jobs were explicitly submitted from the actual local studio through
the official SDK to the owned BF16 runtime. They reuse the owner's private
performance test and composition-matched opening. Neither the uploaded source,
celebrity-like generated reference nor the resulting clips is cleared submission
media. Keep those files outside the public repository and competition demo.

| Actual studio input/profile | Observed render/download time | Export |
| --- | --- | --- |
| Audio + opening / single-pass speech | 101.15 seconds | 1152x2048, 120 frames |
| Same audio, opening, prompt and seed / two-pass | 72.84 seconds | 1152x2048, 120 frames |
| Video + its fixed audio + same opening / single-pass speech | 66.96 seconds | 1152x2048, 120 frames |

These are sequential observations with different warm-cache conditions, not a
speed comparison or a reason to claim single-pass is faster. Exactly one new
provider job was submitted for each case, with no automatic replacement or paid
Cloud/Grid call. Both normal LTX workers and protected process identities remain
active; the native queue is empty after completion.

Read-only native receipts bind each downloaded output and uploaded asset by
SHA-256 and compare the executed nodes/parameters against the frozen workflow.
The matched audio pair uses identical normalized WAV and opening-image bytes.
The video case additionally binds the normalized source MP4; its audio is
extracted from that selected normalized window, so it is not bit-identical to
the original upload's codec. Independent full decoding/counting confirms all
three exports have 120 frames at 24 fps, exactly five-second video and audio
track clocks, and stereo 48-kHz audio. The matched pair's decoded exported audio
also has identical hashes; that does not prove synchronized lips.

Sampled audio/opening frames retain the broad scene and clothing but differ in
framing and expression. The video-guided take follows broad body/phone placement,
with hair/appearance drift and garbled source captions despite a no-text prompt.
Do not call it a qualified arbitrary identity replacement, caption-preservation
or word-level synchronization feature. Direct complete-performance review is
still required, and the two-pass default is unchanged.

Browser playback loads the actual result; seeking sets the video-source and
output clocks to the same 2.5-second position. The new profile is retained in
saved shot drafts and individual take settings, and both takes remain separate
after reload without another render. A transient connection warning observed
during native rendering used to remain after success; the UI now clears the
take's recovered warning without erasing unrelated form/save errors. Single-pass
metadata explicitly identifies the CPU 2x export resize, not latent refinement.
These tests do not complete look auditions, portable bundles, the unfamiliar-user
trial or the three permissioned showcases.

## Owned Production Matrix

Fifteen explicit real-browser submissions use an existing generated paper-boat
image/video and original procedural audio. They execute through the official SDK
on the owned BF16 runtime, not Cloud or billed Grid. No private human-performance
assets, model downloads or public-service changes are involved.

| Input / profile | Formats | Ending reuse |
| --- | --- | --- |
| Idea / two-pass | Landscape, portrait, square | No reference; off |
| Image / two-pass | Landscape, portrait, square | On |
| Audio + opening / two-pass | Landscape, portrait, square | On |
| Video + opening / two-pass | Landscape, portrait, square | On |
| Audio + opening / single-pass | Square | On |
| Video + opening / single-pass | Square | On |
| Image / two-pass control | Square | Off |

Every submitted job completes. The saved workflow and actual native receipt
match node classes and parameters, allowing only provider upload filenames to
differ. Uploaded asset and downloaded native output bytes match by SHA-256.
Two-pass cases have two samplers and ending guides in both passes when enabled;
single-pass cases have one sampler and one ending guide. Reuse binds identical
opening/closing bytes at model frame 120, strength 0.7. The off control has no
ending guide. Exports fully decode with 120 frames at 24 fps at the intended
1536x896, 1152x2048 or 1280x1280 dimensions.

The first square video export failed strict audio timing: its source AAC packet
extended to 5.013 seconds despite five seconds of picture. Its original bytes
remain intact. The revised finisher re-encodes/trims source samples and sets
exact MP4 clocks. Re-finishing the same saved native output into a separate
directory passes exact five-second video/audio clocks; later native portrait
and landscape video exports also pass without repair. This is one discovered
failure and an offline export fix, not fifteen clean first-pass exports or a
replacement render. Silent source regression coverage adds no audio.

Eight supplied-audio results have zero-lag decoded PCM correlation from 0.99807
to 0.99968 against the selected normalized source. This establishes retained
sound/timing, not mouth synchronization. Two-pass video uses source sound in
finishing; it does not bind it as a fixed audio latent. Audio starts and the
explicit single-pass video profile have their separate fixed-audio graph paths.
Sampled boat frames retain the broad subject/scene with both toggle choices;
this is not a face identity, all-frame quality or motion-performance benchmark.

Immediate reload also exposed a preview handoff bug after acceptance. The fix
remembers the take before clearing pending state and awaiting refresh. Project
reload can retain a matching shot preview without choosing it as the winner.
Both paths have delayed-refresh regressions; another shot cannot inherit that
preview. The initial blank-result screenshot is retained as failed QA evidence.
Completed native portrait playback, seeking, nonblank pixel checks and reload
now pass at 1440, 768, 390 and 320px with inference blocked and no page errors
or horizontal overflow. This is developer browser QA, not an independent trial.

One portrait-audio observer lost its SDK connection after native success. The
actual UI Recover action retrieved the same provider ID and idempotency key;
no replacement generation was submitted. Additional polling warnings cleared
without intervention. The isolated proxy reported zero restarts; do not claim
the underlying connection issue was diagnosed or fixed.

An actual QA app stop/restart retains all fifteen native job IDs and MP4 hashes,
and the API reopens the same fifteen results. The native queue is empty. Private
proofs, native receipts, contact sheets, restart snapshot and four-size screenshots
are under ignored `runs/production-native-qa/`. Cloud/credit execution, arbitrary
references, public accounts, sustained outage testing, direct human speech review
and the unfamiliar-user trial remain separate open release gates.

## Portable Native-Media Browser Check

A separate rendering-disabled local app packages three already-completed native
portrait takes. The actual browser deliberately loses both completed package and
import replies, reloads and retrieves the same transfer receipts. Selected media
hashes, opening/end reuse, settings, soundtrack and caption survive import with
new project/asset IDs. The imported board is revised, reloaded and assembled into
a fully decoded fifteen-second 1152x2048 export. Four-size checks cover playback,
seeking, import/reload and horizontal bounds without page errors or inference.

The first new-validator run confused reference latent and output dimensions;
the validator and synthetic fixture were corrected. The next harness tried
editing hidden Shot controls while in Finish; it was corrected to use the tab.
These failed attempts are retained, not described as clean first-pass success.

Eight existing QA project files remain byte-identical across an actual app
restart. A synthetic package separately exercises image/video/audio audition
state and safe MOSS layer-22 provenance. Desktop and 320px browser checks retain
seeds above 2^53 and through 2^63-1 across save, reload, package/import and exact
new-take increment. Already-rounded legacy drafts require explicit correction.
Private scripts, screenshots and receipts remain in ignored
`runs/portable-browser-qa/`; no new model, Cloud or billed Grid job ran here.

These are developer persistence/portability checks. They do not complete public
billing, upload lifecycle/quotas, OS decoder isolation, spoken synchronization,
permissioned showcases or the unfamiliar-user trial.

## Resource-Admitted Offline Export

A separate rendering-disabled app copies three already-completed native portrait
takes into a private QA workspace. The actual browser exports their selected
sequence under shared work admission. A separate process confirms that the
live assembly child holds capacity and releases it after completion. Independent
full decode verifies 360 frames at 24 fps, 1152x2048 and exactly fifteen seconds
with audio. Four viewport sizes reload and play the same completed export without
page errors, horizontal overflow or inference requests.

The first capacity probe ran during child startup, before admission, and failed
its expectation. That export subsequently completed successfully and was not
restarted. A subsequent explicit CPU-only check waits for admitted/running state;
the UI now distinguishes preparing from running. Separate regressions cover
one export per workspace and lock retention/release across independent processes.
These controls do not imply native model execution was newly qualified.

Synthetic Google/wallet browser checks also retain sign-in, account isolation,
reload and no automatic wallet RPC at desktop/tablet/phone sizes. Actual request
byte limits, one-file multipart admission, spooled-file cleanup and storage/work
backpressure have separate regression evidence. No paid API, new model job,
GPU restart or public deployment occurred. Hard filesystem quotas, decoder
isolation, storage lifecycle and the independent human trial remain open.

## Read-Only Video Take Comparison

The A/B browser check uses nine already-completed native videos in portrait,
square and landscape. Private fixture copies remap only their shot/project
association metadata so two candidates belong to one test shot and a third to
another; this is not new alternate-take generation or a worker attestation.
All nine video SHA-256 values remain identical to the source outputs.

Twelve format/viewport cases verify both decoded pictures have nonblank pixels,
shared playback/seek and only one audible soundtrack. Sampled player-clock drift
is below 50 ms, not a worst-case synchronization guarantee. Comparison leaves
project JSON unchanged; explicit seed reuse changes only the seed, and choosing
a winner preserves the draft and survives reload. Another shot's take is excluded.
Single-shot View separately retains its draft and full-width seed. Navigation
stops hidden comparison audio. No inference request is attempted.

Initial harness checks read pixels before a ready video had actually painted,
then encountered incomplete synthetic saved-shot context. Both fixture issues
are retained and corrected, not treated as failed native video outputs. A real
post-swap winner-button state lag was also found and fixed, with handler and
browser checks requiring the label/button state to agree immediately. Selection
now safely rejects corrupt metadata instead of replacing a project or exposing
validation details. These tests do not qualify public billing, live identity,
new model quality or the unfamiliar-user trial.

## MiniMax H3 Swap, Camera Flight And Backend Prompt Helper

Three features landed on 2026-10-28 from the private H3 work of 2026-10-26/27,
all rendered on the owned 96 GB GPU through the studio's own API and CLI
(ComfyUI 0.38, self-hosted backend through the official SDK proxy):

- Replace the person, swap engine: the five-second car clip with the legionary
  photo, portrait 768x1344, 124 frames, swap LoRA plus Comfy's Ref2V turbo at
  four steps. One job, 176 s observed; picture and voice muxed locally; the
  helmet, gestures, mouth timing and original voice held. The earlier private
  side-by-side (20 steps, DMAD six steps, turbo four steps) on two clips is
  the basis for choosing the turbo; DMAD dropped the helmet once and is unused.
- Camera flight, orbit: the showroom-car look, orbit LoRA plus Comfy's FL2V
  turbo at eight steps, 185 s; frame-by-frame it matches the 20-step orbit the
  owner kept on 2026-10-26. The FPV move was then run through `/api/flights`
  on the skyline look; see the entry's render folder for its receipt.
- Prompt helper: with no Ollama reachable, Qwen3-VL 8B through `TextGenerate`
  wrote a style sentence from the car clip's first frame and a scene from the
  legionary photo in two to three seconds each with the model already loaded;
  `PreviewAny` returned no SDK output, `SaveText` did.

Limits: portrait only, one seed each, Cloud not run (its swap, orbit and
camera LoRAs must be imported by the account), no landscape/square render,
no identity or lip-sync qualification. The inputs are our own generated looks
and the owner's test clip; nothing here is competition media by itself.

## Remove Something From The Clip And Four Versions

Remove something (`remove.py`, 2026-10-28, owned GPU, pasta clip at 480x848,
121 frames, SAM 3.1 plus Wan 2.1 VACE 1.3B, 20 steps, seed 42):

- Find stage: "the wooden spoon" tracked cleanly through the clip in 32 s;
  the preview lights the spoon and its grown edge over the picture.
- Remove, attempt 1: black fill, mask grown 20 px, prompt "the same shot with
  the wooden spoon gone", 164 s. The spoon was painted back.
- Attempt 2: grey fill, grown 50 px, same prompt, 174 s. Spoon back again.
  "the pot on the stove" with the same wording, grown 30 px, 180 s: a
  different pot appeared in its place.
- Attempt 3: the positive prompt names only what is there instead ("the bare
  stove top with its black burners and clean steel surface"; "her empty hand
  with the fingers relaxed and open") and the object goes to the negative
  prompt. Pot gone in 154 s, spoon gone in 190 s, the hand gestures empty.
  The steam and everything outside the mask are the original pixels.

Attempts 1 and 2 are kept as failures; the app requires nothing but offers
the "instead" field and says why. One seed each, portrait only, not Cloud.

Four versions (`product.js`): a code change only. The plain editor's button
sends the current request at four consecutive unused seeds one at a time and
shows the takes in a grid; no new native render was made for it today, and
the Chrome check only confirmed the controls load without script errors.

## Idea-To-Video Styles, Background Change And Say This Line

All on the owned GPU on 2026-10-28 through the studio's own API.

- Idea to video styles: four text-mode takes (landscape, seed 42, two-pass
  LTX-2.5 with the style LoRA after the backbone), one per tile. Claymation
  (a fox in a snowy forest) came out as sculpted stop-motion clay; Paper
  cut-out (a lighthouse) as layered cut paper; Cozy felt (a hedgehog's
  kitchen) as plush felt; Pixar-style toon (a robot gardener) as a stylized
  CGI film frame. 76 to 94 s each. One prompt and one seed per style; no
  portrait or Cloud run.
- Change the background: the kitchen clip with the skyline look as the new
  place, H3 Ref2VA with no LoRA, 243 s in the private probe. The person,
  her spoon, mouth timing and voice are kept and the light on her matches
  the dusk skyline. The studio-driven run is recorded below with its time.
- Say this line: the legionary look speaking a typed line, H3 FL2VA with the
  turbo LoRA; recorded below. Mouth timing remains the owner's call, as with
  the 2026-10-26 stills that were dropped from the reel.

Studio-driven runs, same day: Change the background on the kitchen clip with
the skyline look, 186 s; Say this line with the legionary look and the line
"Day four hundred of the campaign. Still no coffee.", 180 s, and the local
Whisper transcript of the output reads "Day 400 of the campaign still no
coffee" at a mean level of -19 dB. Lip timing was not reviewed by the owner.

## Twelve Style Tiles And The Two UI Walk-Throughs

Later on 2026-10-28, owned GPU, through the studio:

- Eight more Idea to video styles rendered as single text-mode takes
  (landscape, seed 42, 60 to 140 s each): 90s cartoon (a cat chef), Wild West
  (a rider at high noon), Post-apocalyptic (an overgrown highway), Fantasy
  anime (a lantern in a mushroom forest), Fantasy painting (a knight by a
  river), Fantasy puppet (a goblin shopkeeper), Cyberpunk (a courier in neon
  rain) and Fantasy realism (an elf archer at sunrise). Two first submissions
  were refused by the worker-health probe during a model swap ("Worker
  connection unavailable", nothing submitted) and were sent again. Each tile
  was looked at before being kept; none has a portrait or Cloud run.
- Remove something, in Chrome against the local studio: the kitchen clip
  (landscape framing this time), target "the pot on the stove", instead "the
  bare stove top with its black burners and clean steel surface". Find it
  showed "SAM 3.1 is tracking it", then the mask link; Remove it ran Wan VACE.
  The studio process was killed mid-render by a stopped shell task; after a
  restart, POST /api/removals/{id}/resume picked the saved job id up and the
  page, reloaded, showed "the pot on the stove" removed with the mask,
  download and before/after links. The page now re-checks a given-up run
  once on load.
- 4 versions of this take, in Chrome: Idea to video with the 90s cartoon
  style, seeds 43 to 46 (42 was already used), rendered one after another
  (about 100 s each) into the grid; View switches the shown take and the
  seed field. Rows for the video-mode features now hide in other modes.

Three more tiles the same afternoon, from other public Apache-2.0 LTX-2.3
LoRAs Comfy Cloud hosts: 90s TV sci-fi (bionicman69's TNG style; a corridor
scene), CRT terminal (lovis93's crtanim at 10,000 steps; a pixel pilot over a
neon grid) and FPV drone (chsengni's FPV motion; a lake at sunrise). Single
landscape text-mode takes at seed 42, 60 to 140 s each, through the studio.
Fifteen Idea to video tiles in all; the LTX-2 photo effects and the gated
Lightricks IC-LoRAs remain the unrendered part of Cloud's catalogue.

## Node Check: Wan MiniMax Remover, And Two Deliberate Deviations

Checked 2026-10-28 against Comfy Cloud's `/api/object_info` and the owned
worker's `/object_info`:

- `Wan2_1-MiniMaxRemover_1_3B_fp16.safetensors` is hosted by Comfy Cloud, but
  the only node that drives it, `WanVideoMiniMaxRemoverEmbeds` (inputs width,
  height, num_frames, latents, mask_latents), belongs to the WanVideoWrapper
  custom pack: 140 of its nodes are on Cloud, none on the owned worker, whose
  runtime is pinned and takes no custom packs without the owner's approval.
  Core ComfyUI has no node for the remover's extra latent channels. Remove
  something therefore uses the core `WanVaceToVideo` inpaint (Wan 2.1 VACE
  1.3B, hosted by both) with the fill-description prompt recorded above; the
  remover remains the roadmap item for held objects without a fill line.
- Change the background was built on MiniMax H3 (clip as motion and audio
  reference, photo as the place) instead of the remove-background matte plus a
  Klein first frame plus Transform, because Klein runs only on the 5090
  (reachable on the LAN, not from this session) or on Comfy Cloud (no
  credits). The H3 route needs no LoRA and ran through the app in 186 s.
- The remaining Cloud-hosted LTX LoRAs are not tiles for one of three
  reasons: LTX-2 19B photo effects run only on the 5090 or on Cloud; the
  Lightricks IC-LoRAs (clean plate, cross-eyed, outpaint and the rest) are
  gated on Hugging Face and the worker's account gets 403 until the gate is
  accepted; the others are utility adapters (lip-dub, upscale, controls,
  identity) that already back their own features or are not one-click tiles.

## The Named Remover, On An Isolated Runtime

Later on 2026-10-28 the Wan MiniMax Remover was run as named, without touching
the pinned worker: the WanVideoWrapper pack was installed into the isolated
ComfyUI 0.42 left from the FastH3 test (its own venv), started on GPU1 port
8190 with the shared model folders and a second official proxy in front of it.
Kijai's repack of the remover weights (2.25 GB) was added to the shared
diffusion models. Findings:

- First run, masked region filled black, 12 UniPC steps, 81 s: the region
  came back as dark smears. The model's own pipeline zeroes the region in
  [-1, 1], which is mid-grey in pixel space, and VAE-encodes the mask as a
  second latent.
- Second run, grey fill, mask grown 40 px, otherwise the same: the spoon is
  gone and the hand reads as empty, no prompt and no fill line, 81 s.
- Through the studio pointed at the isolated instance: readiness reported
  engine "remover"; find then remove on the same clip finished in 47 s, with
  the mask preview, download and before/after links.

The app picks the remover whenever the backend lists its node and weights
(Comfy Cloud does) and falls back to VACE otherwise. The isolated instance and
its proxy are stopped after the test; the pinned runtime is unchanged.

## Lightricks Gates Accepted, Two More Clip Tiles

On 2026-10-28 the owner asked for the Lightricks LTX-2.3 LoRA gates to be
accepted and I clicked "Agree and Access" on all sixteen repos in the owner's
Chrome, signed in as the rig's Hugging Face account; the rig's token then
returned 200 where it had returned 403. Five LoRAs were downloaded (the rig
had 5 GB free; 2.7 GB after) and each was run as a clip effect on the kitchen
clip through the studio, portrait, seed 42, two-pass distilled Transform:

- Cross-eyed: eyes crossed, everything else kept. Now renders locally, not
  only on Cloud.
- Colorize, on a grayscale copy of the clip: skin, hair, the wooden spoon, the
  copper pot and the blue flame came back in natural colors.
- Clean plate ("Everyone gone"), Day to night and Add water: the output was
  the source clip with at most a faint change. Their cards call for the
  single-stage V2V IC-LoRA workflow on the dev model at 30 steps with a
  guidance scale of 3 to 4; our Transform path is the distilled model without
  guidance, which is enough for a local edit like crossed eyes but not for
  removing people, relighting a room or flooding it. Not listed; their files
  were removed from the rig for space and can be fetched again.


## The Klein Route For A New Background: Built, Then Rendered

The owner's "do whatever" allowed the duplicate Wan download to go. It turned
out to be hard links to the primary files (link count 2, `du` charging all 46
GB to the first path), so removing it freed nothing, and the FLUX.2 Klein
downloads that followed filled the rig to zero; they were stopped and their
partial files deleted (3.8 GB free afterwards, all four services active).
BiRefNet (444 MB) did land. The scene engine (matte, Klein place on the first
frame, matte composite, Transform) is implemented with route and contract
tests, and waits for a Klein engine for its first native run.

The owner then approved deleting the 34.5 GB `wan2.2_animate_14B_bf16`
file (36 GB free afterwards). Klein 4B (bf16, 7.75 GB), the Qwen3 4B encoder
(8.04 GB, one stalled transfer resumed) and the FLUX.2 VAE went into the
shared model folders; the isolated ComfyUI 0.42 instance on GPU1 (port 8190,
proxy 18295, its own model-paths file gaining `background_removal`) lists all
four files, so Klein looks and the BiRefNet matte run there while the pinned
0.38 worker (which cannot see `background_removal`) keeps the Transform take.
A small change lets self-hosted tools name that second worker
(`COMFY_TOOL_BASE_URL`/`COMFY_TOOL_UPSTREAM_URL`; default unchanged).

One app run (`POST /api/replacements`, engine `scene`, the kitchen talking
clip, portrait, seed 42, "a sunlit Tuscan terrace with olive trees, a low
stone wall and rolling hills behind"):

| Step | Wall time |
| --- | --- |
| BiRefNet matte (121 frames) | 35 s |
| Klein paints the place on frame 0 | 91 s (first load) |
| Transform two-pass take | 101 s |
| Total to compare wipe | 232 s |

Output 1152x2048, 120 frames, 24 fps, source audio kept. Sampled frames keep
the person, her lip motion and the wooden spoon she raises from the source;
the terrace, olive trees, pots and wall stay put behind her. The matte edge
is clean on this clip. One portrait clip is not a qualification across
subjects, hair or busy backgrounds; the LTX-2 photo tiles still need the
5090 or Cloud credits.


## LTX-2 19B Photo Tiles On The Owned Rig

The owner's second approval of the day removed the unused full
`minimax_h3_fl2va_bf16` (66 GB; the app's recipes pick the pruned 40 GB copy
first, and the symlinked int8 name points at it). That made room for the
Lightricks `ltx-2-19b-distilled-fp8` checkpoint (27.1 GB), Comfy-Org's
`gemma_3_12B_it_fp4_mixed` encoder (9.4 GB), the LTX-2 spatial upscaler and
seven `ltx2-*` effect LoRAs Comfy Cloud hosts but we had never run, fetched
from their authors' public repos under Cloud's filenames. Rendered on the
isolated ComfyUI 0.42 instance on GPU1 with the 5090 recipe (Comfy Org's
LTX-2 LoRA template, distilled checkpoint so the distilled-LoRA nodes are
dropped, 704x1280, 121 frames, seed 42), after `POST /free` emptied the
pinned worker's idle 68 GB from the GPU. Photos are the Klein looks from the
earlier effect batch.

| Tile | Photo | Time | Sampled result |
| --- | --- | --- | --- |
| Cakeify | laptop under a press | 144 s | a gloved knife cuts the laptop; layered sponge and jam inside |
| Eat it | pancake stack | 44 s | a man leans in, lifts the stack and bites it |
| Timelapse (first prompt) | realtor by a SOLD sign | 34 s | she only turned around: no time passing |
| Timelapse (day-passing prompt) | rooftop selfie | 146 s | sunset to dusk, lights come on, birds streak past; she holds still |
| Outfit check | rooftop selfie | 34 s | a pose, then shorts replace the tee; same face and bar |
| Outfit switch | beach jogger | 70 s | the outfits change colour three times but the man becomes a woman |
| Outfit switch (retry) | two kids at a lemonade stand | 148 s | the boy vanishes while the girl's outfit changes |
| Costume sweep (`ltx2-smooth`) | backyard barbecue | 46 s | a different person smears in over him |
| Costume sweep (retry) | rooftop selfie | 74 s | arms up and crossed as trained, then a blur, no new outfit |
| AnimateDiff look | night skyline | 124 s | dusk slides into night, boats cross, a soft painterly drift |

Cakeify, Eat it, Timelapse, Outfit check and AnimateDiff look are tiles
(28 in all). Outfit switch and the `ltx2-smooth` costume sweep changed who was
in the frame on both tries and are not listed; their files stay on the rig.
These are single seed-42 renders on one photo each, not a quality
qualification across subjects. The first and second timing in each pair
differ because the 19B model stayed resident between consecutive jobs.
