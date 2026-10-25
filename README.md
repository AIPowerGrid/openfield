# Openfield

Openfield is AI Power Grid's open-source short-video studio. Drop a product
photo, pick a style, and press **Make the whole short**: it places your real
product into each shot with FLUX.2 Klein, animates the shots with LTX-2.5
through the official Comfy SDK, builds a packshot and scores the cut with
ACE-Step, showing the price before every step. Everything runs on open models,
on your own GPU or on Comfy Cloud.

## Quickstart: 5 minutes, no GPU

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), FFmpeg
and a [Comfy Cloud](https://comfy.org/cloud) API key (create one at
[platform.comfy.org](https://platform.comfy.org), Profile → API Keys; Cloud API
runs need an active subscription).

```sh
git clone https://github.com/AIPowerGrid/openfield && cd openfield
COMFY_API_KEY=your-key uv run openfield --cloud
```

The first run installs dependencies (about a minute), checks FFmpeg and your
key, then opens the studio at http://127.0.0.1:8793. Everything (video, looks
and tools) runs on Comfy Cloud; each button shows its estimated cost first.
Try **Transform a video → Recreate this** on any style for a ready-made first
take, or open the [MCP server](#agents-mcp) from Claude.

**If it doesn't start**

| Message | Fix |
| --- | --- |
| `ffmpeg is not installed` | macOS `brew install ffmpeg`, Ubuntu `sudo apt install ffmpeg`, Windows `winget install ffmpeg`, then open a new terminal. |
| `COMFY_API_KEY is not set` | Put the key on the same line as shown, or in a `.env` file and run `uv run --env-file .env openfield --cloud`. |
| `Comfy Cloud rejected COMFY_API_KEY` | Copy the whole key again; keys are shown once, so make a new one if needed. |
| `no active subscription` | Cloud API runs need a paid Cloud plan. |
| `uv: command not found` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (macOS/Linux) or `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` (Windows). |
| Port 8793 is busy | Add `--port 8800`. |
| A take shows "came back blank" | A GPU numeric error on the provider; press Generate again (a new seed can help). Nothing is retried for you. |

The home screen offers every capability as a starting point:

- **Create a product ad**: one photo becomes a calm, finished ad (see [Product Shorts](#product-shorts)).
- **Transform a video** (OpenReshoot): restyle your own footage while keeping its motion, timing and sound. Takes run 5, 10 or 15 seconds.
- **Add to video (beta)**: put a product or object from up to three photos into a clip, like a bottle in someone's hand. Klein edits the first and last frame with the photos, then the take follows the clip's motion more loosely (guide 0.6) so the object moves with the hand. Best on steady shots; busy scenes where people cross can lose the object.
- **Restyle a whole video**: up to two minutes as back-to-back 10 s takes in one style, each seam pinned to a shared look, joined with the original sound. Fast push-ins into a close-up can briefly lose the style.
- **Replace the person (beta)**: pick a photo and someone new takes over a talking clip. Klein empties the scene and places the person from the photo into it, then LTX animates them from the clip's own voice so the lips follow the words. Body motion is new, not copied; a before/after wipe is made too.
- **Prompt helper**: type a vibe ("make it spooky") and get full directions. It uses a local Ollama model when one runs on a loopback address (`OPENFIELD_LLM_URL`, default `http://127.0.0.1:11434`, model `OPENFIELD_LLM_MODEL`, default `phi4-mini`); otherwise a plain template.
- **Auto captions**: Whisper (faster-whisper "small", on this computer) turns speech into big three-word social captions burned into the clip, plus an `.srt`.
- **Save your own style**: keep any look as a named tile in your style library.
- **Camera moves (best effort)**: dolly in, orbit, crash zoom, drone pull-back or handheld for Idea to video and Animate a photo.
- **Style compare**: tick up to four styles and see your clip in each as stills before rendering one.
- **Your own style image**: upload any picture (a painting, a still, a palette) and Transform restyles the clip in its look, using it as a second Klein reference image.
- **Transform styles**: nine named restyles (neon future, full colour, anime, 3D animated film, golden hour, bioluminescent night, ink wash, watercolor, Van Gogh oil), each with a split before/after example rendered by Openfield. One click fills the direction and makes the opening look; "Recreate this" loads an example's own clip and style.
- **Tools**: FPS boost (RIFE v4.26, 24 to 48 fps), remove background (BiRefNet: green, black or white plate, or a matte), upscale 2x (RealESRGAN), extend a take by 5 s (LTX image-to-video from its last frame), depth map (Depth Anything V2 Small, Apache-2.0, via comfyui_controlnet_aux) and reframe (local ffmpeg: vertical, landscape or square with a blurred fill or centre crop), on an upload or any finished take. Relight opens Transform with the golden-hour style.
- **MCP server**: `openfield-mcp` lets Claude or any MCP agent list styles, transform a clip, make a shot from words and run tools on your own studio (see [Agents (MCP)](#agents-mcp)).
- **Before / after export**: one click turns a finished Transform take into a shareable split-screen or wipe video with the take's sound and a small Openfield mark (local ffmpeg).
- **Open in ComfyUI**: every finished take downloads as a ComfyUI bundle: the exact API-format graph (numeric node IDs), its input files and the model list.
- **Animate a photo**, **Idea to video** and **Shot from audio** (single-pass speech; not lip sync).
- **Multi-shot story**: plan, select takes, add captions and music, export one short.
- **Look lab**: compare opening looks side by side before rendering.

Saved shot boards, four starting modes and
offline short assembly, captions, extra sound layers and portable project
packages now work locally. Public release and user acceptance remain goal work.

Openfield is also a local creative-video app for turning an idea, image, audio or
original footage into LTX 2.5 takes and short sequences. Plan shots, review and
select takes, trim and export. MOSS can create optional opening and closing looks;
an explicit Klein 4B Cloud option is also available.

**No GPU?** Start with the [Cloud quickstart](#cloud-quickstart-no-gpu):
`--backend cloud --look-engine klein-cloud` runs both image editing and LTX 2.5
video on Comfy Cloud. MOSS remains the default image engine for the
[first-class owned-hardware path](#owned-video-backend); Cloud is optional.

Motion and appearance fidelity are still under evaluation; they are not
guaranteed. Video mode reuses normalized source sound, text/image generate sound,
and audio mode uses the supplied sound as fixed conditioning and the soundtrack.
That does not promise lip sync. Our application code is [MIT licensed](LICENSE).
Source: [github.com/AIPowerGrid/openfield](https://github.com/AIPowerGrid/openfield).
The Python package is currently named `aipg-cinema`.
The release scope and production plan are maintained with the project's private
notes; the [unfamiliar-user trial](tests/INSTALL_TRIAL.md) remains a separate
release gate.
The separate account-isolated staging shell now has Core-backed sign-in, scoped
projects/assets and account-scoped browser drafts. It is not deployed, and the
local app below remains single-user. Staging rendering stays blocked until
Grid-backed billing and approved-workflow execution are integrated and verified.
The new Core video client and journal are development components, not a change to
the local SDK backend or permission to submit unqualified studio profiles.

Staging now limits expensive transfers/preview builds and offline exports with
shared cross-process slots (four overall, two per workspace, one export per
workspace). Status, recovery receipts and cached media remain readable while
capacity is busy. Request bytes are bounded before multipart parsing, including
chunked uploads; stalled uploads time out and close temporary files. Storage
admission checks existing workspace/total usage and free-space headroom. Before
reading media uploads, it reserves the route's maximum body size across
processes, including temporary-spool headroom. Portable imports instead reserve
1548 MiB for the archive, extraction, remapped copies and bounded metadata;
package creation reserves 1028 MiB for frozen media and the growing archive.
Missing or smaller length headers never reduce these server-owned reservations.
Archives are capped while writing, and rebuilt metadata has an aggregate cap.
A disconnected or dead process releases its OS-held claim. These are conservative
data-byte admission bounds, not filesystem quotas or bounds on every decoded or
generated output. OS limits, decoder isolation and retention/deletion remain
public-release gates. Staging persists the transfer limits with its work policy;
an old or mismatched policy fails closed. Review all writers while stopped before
an explicit policy upgrade; never delete a live lock root or user data to bypass it.

The staging app cache reuses idle workspace slots instead of permanently filling
after its first 128 accounts. Request pins cover the full response; live export
children and held work slots prevent eviction. On a cache miss, it lazily removes
idle entries older than fifteen minutes or the least-recently-used idle entry
needed for capacity. This only discards an in-memory app: sessions, projects and
media stay on disk. If all slots are active, new workspaces receive retryable 503
backpressure. This is not a hard memory quota or a production load qualification.

## Setup

### Managed Account Staging

The installed wheel includes `aipg-studio-staging`, a separate loopback-only
launcher for the account-isolated shell. It does not enable inference or deploy
the public product. Do not reverse-proxy the single-user `openfield` command (alias `openreshoot`).
Before choosing a public hostname, complete the production-home, billed-workflow,
live-login, upload/decoder isolation and operating gates in the production plan.

Use a dedicated POSIX service user and private absolute state/key-file paths. The
key file must be a regular owner-only file (0600 or 0400), not a symlink, hard
link or pipe. It is read in-process, never passed as a CLI value or loaded into
the environment. Keep the state volume and backups private: the session database
contains credentials. Never commit them or put them in project packages.

```sh
aipg-studio-staging \
  --state-dir /absolute/private/studio-state \
  --service-key-file /absolute/private/grid-service-key \
  --origin https://studio.example \
  --google-client-id PUBLIC_GOOGLE_CLIENT_ID \
  --release-sha256 SHA256_OF_REVIEWED_INSTALLED_WHEEL \
  --port 8800 --check
```

`--check` validates configuration and initializes private session/workspace policy
storage; it does not listen, call Core, verify the credential's permissions, test
Google proofs or generate media. Use the verified wheel hash for the release
label; the launcher validates its format but does not attest installed code.
Remove `--check` to serve only on `127.0.0.1`. There is no remote-bind, reload,
multi-worker or inference-enable switch. A host-bound HTTPS proxy, certificates
and origin registration still require a reviewed deployment. Proxy-forwarded
headers are not trusted, and access logging is off by default.

One managed server holds the private state lease for its full lifetime. A second
server or `--check` against that store fails before session initialization. A
separate shared activity lease covers the server and resource-managed export
children, including after the server exits. Exclusive maintenance rejects active
writers; a late export leaves its saved request untouched and exits 75. The locks
release on normal exit or process death and are never deleted to bypass activity.
Direct factories and arbitrary external writers must still be stopped explicitly.
Existing state is not silently repaired, deleted or migrated on failure.

Send probe GETs with the configured origin's `Host` header. `/health/live` reports
that staging is alive; it does not check Core or create a login session.
`/health/ready` deliberately returns 503 `billed_execution_not_enabled` while
rendering is gated. Do not restart a healthy staging server because of that
expected readiness response, or treat liveness as production launch approval.

Pending sign-in state survives anonymous reloads without resetting its ten-minute
expiry. A reused HttpOnly capability does not authenticate anyone: Google or a
wallet proof and a matching CSRF header are still required. Used, expired or
abandoned wallet challenges get a fresh flow; no proof/signature is replayed.
The shared database admits at most 4096 pending logins. At capacity, new flows
receive a private retryable 429; existing fresh flows, signed-in sessions and
logout remain usable. The page exposes an explicit retry and keeps unavailable
provider controls disabled. This is bounded backpressure, not bot protection or
per-client rate limiting; trusted-edge abuse controls still need deployment review.

### Offline Backups And Restore

Use a reviewed [Restic binary](https://restic.readthedocs.io/en/stable/020_installation.html)
for encrypted snapshots. Keep its password, service credential and repository
outside the state/backup source paths, with owner-only permissions and a separate
recoverable password copy. Backups contain private media and account credentials;
they are not portable project packages and must never be exposed as web downloads.
The commands below configure neither an offsite destination nor a schedule.

Stop the managed web service and let exports finish. Stop direct-factory servers,
older incompatible runtimes and any other writers too. Set the non-secret canonical absolute
path variables `STATE`, `BACKUP_REPO` and `BACKUP_PASSWORD_FILE`, then initialize
the repository once and run a foreground backup:

```sh
restic --repo "$BACKUP_REPO" --password-file "$BACKUP_PASSWORD_FILE" init
aipg-studio-maintenance hold --state-dir "$STATE" -- \
  restic --repo "$BACKUP_REPO" --password-file "$BACKUP_PASSWORD_FILE" \
  backup auth workspaces .workspaces-resources/policy.json \
  --exclude '*.lock' --exclude render.log --tag aipg-studio-state-v1
restic --repo "$BACKUP_REPO" --password-file "$BACKUP_PASSWORD_FILE" check --read-data
```

Maintenance checks the private layout, policy, bounded file tree, account schema
and ownership records. It takes exclusive writer/observer fences and changes the
command's working directory to `STATE`. The foreground executable inherits the
leases directly; do not wrap it in a shell that launches background work. Busy
stores exit 75 without running the command. Never delete a lock file to retry.
Record the full snapshot ID and require a zero backup/check exit; partial backups
are failures. See [Restic's backup semantics](https://restic.readthedocs.io/en/stable/040_backup.html).

Restore the chosen full snapshot ID (`SNAPSHOT`) only into a brand-new, empty,
owner-only canonical directory (`RESTORED_STATE`) outside the original state tree.
Run as the service user and verify repository health first. Never restore in place:

```sh
mkdir -m 700 "$RESTORED_STATE"
restic --repo "$BACKUP_REPO" --password-file "$BACKUP_PASSWORD_FILE" \
  restore "$SNAPSHOT" --target "$RESTORED_STATE" --verify --overwrite never
aipg-studio-maintenance prepare-restore --state-dir "$RESTORED_STATE" \
  --previous-state-dir "$STATE"
```

[Restic verifies restored content](https://restic.readthedocs.io/en/stable/050_restore.html);
`prepare-restore` is not that cryptographic verification. It checks the relocated
trusted store, preserves account/workspace mapping and data, clears copied login
sessions/challenges, and rebinds only the resource-policy workspace path last.
Schema/policy changes need a separate migration review. Original, nested,
already-prepared or mismatched stores are rejected. No command starts a service,
submits a model job or rolls back Core credit balances.

Run the staging launcher's `--check` against the restored directory, sign in
fresh, and verify project/media access and an offline export before switching a
service to that path. Keep the original state and exact reviewed wheel. Reconcile
uncertain paid jobs by their original Core IDs, never replacement submissions.
Offsite recovery, scheduling, alerts, retention and software rollback compatibility
still need deployment-specific review and tests; no automatic pruning is enabled.

### Local Rendering Setup

Install Python 3.11+, [uv](https://docs.astral.sh/uv/), and FFmpeg (including
FFprobe), then run from the repository root. Comfy Cloud needs no local GPU;
owned hardware can instead use the official Comfy API proxy described below.

```sh
uv sync --frozen
```

The runner uses the [official Comfy SDK](https://docs.comfy.org/development/api-development/sdks)
with Comfy Cloud or a self-hosted Comfy API proxy. Cloud API access requires a paid Cloud subscription and a
workspace API key. Configure `COMFY_API_KEY` locally, not in source control.
Alternatively, put it in a local `.env` based on `.env.example` and add
`--env-file .env` immediately after `uv run` in the commands below. Never put the
key in frontend code. The `.env` file is ignored by Git.

## Run the app

### Cloud Quickstart (No GPU)

After [Setup](#setup), put your Cloud workspace key in the ignored local `.env`
file as `COMFY_API_KEY`, then run:

```sh
uv run --env-file .env openfield --backend cloud --look-engine klein-cloud --max-renders 6 --max-looks 12
```

This uses the same Cloud workspace key and needs no local GPU or second proxy.
It does not install a model, switch the video model, call a closed partner model
or fall back to another image engine. Review each generated look before the
separate Generate take action. The engine name is shown next to the look limit.
Klein uses reference conditioning, not latent-blend denoise: the MOSS strength
selector is hidden and the API rejects that unsupported control. The model can
still change geometry or overdo a palette; it is not an exact reconstruction.

### Default MOSS Image Engine

With the [owned MOSS runtime](#optional-moss-opening-looks) configured, this keeps
MOSS image generation on your hardware while sending video to Cloud:

```sh
uv run --env-file .env openfield --backend cloud --max-renders 6
```

For both image and video on your own hardware, use the owned-backend setup below.
Neither path silently falls back to the other. Both use the official Comfy SDK.

### Create And Export

Open [Openfield locally](http://127.0.0.1:8793/). Choose Idea, Image, Video or
Audio. Video needs at least five seconds and less than 100 MB. Audio needs
5 seconds to 30 minutes, less than 50 MB; choose its five-second section before
generating. Image mode requires an opening image. The
current LTX-2.5 BF16 workflow renders a selected five-second section at 24 fps.
Choose vertical 9:16 (1152x2048), square 1:1 (1280x1280), or landscape (1536x896).
Use Source start to choose the section of longer footage. New drafts start in
vertical; old saved takes retain their original landscape framing and start.
Vertical and square each have an owned native rendering control; their Cloud
execution and broader creative-quality matrix still need qualification.
Source footage is letterboxed rather than stretched. Keep the app local: it has
no multi-user authentication and is not a public hosting service.

Uploads get a browser-compatible H.264/AAC preview at the selected input canvas
(576x1024 vertical, 640x640 square, 768x448 landscape) and 24 fps, with
the same framing as the render input. The original upload remains unchanged
and is used to prepare the render independently, not re-encoded from that preview.
Video inputs are restricted to standalone MP4/MOV, WebM/MKV and Ogg containers;
playlists and network references are not accepted. MP4, VP8/Vorbis WebM and
Theora Ogg have actual local decode/preview tests. Container selection, file-only
protocols, disabled MOV data references and bounded inspection/preview time do
not replace an operating-system media sandbox or storage/concurrency limits.

The six-render limit counts submitted takes in the saved application directory;
it is not a credit or dollar cap. Cloud jobs consume the provider's credits.
There are no automatic replacement renders. Interrupted jobs with a saved ID
can be recovered; a submission with no recorded ID requires manual review.
SDK requests have a bounded 120-second timeout for media transfers, independently
of the render wait. Browser job-status calls use a separate five-second timeout.
A timeout never authorizes an automatic replacement job.
Jobs and takes survive reloads and app restarts in the ignored `runs/web/` tree.
Cloud readiness uses the documented [user-status endpoint](https://docs.comfy.org/api-reference/cloud/user/get-current-user-information)
to check credentials and active access without submitting a render. Display
checks are cached for 15 seconds; each new take or Cloud look rechecks before creating its job
directory. This is not a credit-balance, queue-capacity or model-availability quote.
New MP4 exports identify AI generation in their title/description metadata;
take settings also carry an `ai_generated` flag. These are not cryptographic
Content Credentials. Disclose AI generation when sharing results publicly.

The Export menu downloads the finished video, API workflow and portable take
settings. Video takes include normalized `source.mp4`; audio takes include
`source.wav`. Text/image takes have no source clip to download. An optional opening
look image is anchored in both LTX passes and exported as `look.png`. PNG, JPEG
and still WebP uploads are limited to 12 MB and 16 megapixels. The image is an
opening-frame anchor, not an arbitrary style-reference image. The optional
closing look is exported as `closing.png`; it uses native guidance at model
frame 120, strength 0.7 in both passes. This has real owned-worker and Cloud
tests, but does not guarantee fixed geometry, exact motion or a copied last frame.
Keep the exported files together to reproduce a take.
For video mode, the SDK uploads the source and substitutes its returned name in
the workflow's `LoadVideo` node. Upload the look images and bind their respective
`LoadImage` nodes when present; provider upload filenames alone are not portable.

Known limitations: five-second native shots; basic sequence assembly is not the
complete finishing suite, and there is no motion-strength control in the app.
In video mode without an opening image, Canny guidance
follows outlines, not identity: a test changed a blue toy car to white. Matched
pendulum tests show stronger appearance retention with an opening frame and
persistent relighting with an edited frame. Those results do not promise exact
object appearance, arbitrary reference transfer or perfect motion on other clips.
Native source-guided MOSS edits have also been tested on an owned image worker,
then loaded through the app's opening-image input for an actual LTX take.
The optional MOSS stage uses the Opening/Closing selector: generate or upload
the opening image, inspect it, optionally create a closing image, then explicitly
generate the LTX take. Each generation submits one image, never a hidden batch
or an automatic video. Histories are specific to the source clip, selected range,
framing and frame role.
Changing the opening selection clears a separately selected closing reference,
while **Use opening at end** follows the new opening selection. Previous images
remain in history. This uses
the owned worker through the official Comfy SDK, not the billed Grid API.
The Export menu can download both selected images before a video exists.
In video mode, art direction and video direction are separate. Art direction captions the MOSS
look; the editable Motion & camera section controls the LTX motion prompt. When
look images are selected, video generation uses the motion prompt rather than
repeating the image's lighting description. Without an opening image, it joins
the art direction and motion text. Both directions and the exact executed video
prompt are saved and exported. Changing text does not regenerate a look or video.
Older takes retain their original prompts when selected or copied for revision.
If an art-direction edit differs from a selected generated reference, the app
identifies that image as using an earlier direction. It does not erase the
reference or silently regenerate anything. Motion-only edits do not mark a look
as outdated. A first-load configuration response cannot overwrite user-typed text.
The [quality notes](tests/REAL_FOOTAGE.md#native-moss-opening-look-tests) record
both the useful warm edit and the geometry failures at stronger denoise.

### Single-Pass Speech

The main editor keeps source, framing, scene and reference images together.
**Advanced** contains source-range selection, motion/camera direction, the LTX
workflow and seed. Shot
bookkeeping lives under **Shot settings**, while the shot board and earlier
takes have their own expandable sections. On phones, the preview comes first;
**Edit shot** jumps to the composer and **Back to preview** returns to the result.
These navigation actions never submit a render or change saved generation settings.
An accepted submission is remembered before the next status refresh, so a fast
reload retains its preview. Reopening a project restores the last previewed take
for that shot without changing its explicitly selected winner.
Viewing an earlier project take does not restore its old settings over the
current draft. Its later completion updates the preview while retaining newer
prompts, references and seed. Choosing a take from history opens its source/result
view; a background completion does not move you out of a deliberate frame review.

Audio and video starts offer an explicit **Single-pass speech** LTX workflow.
It encodes the selected audio as a fixed latent before the single eight-step
BF16 sampling pass. For a video start, the sound comes from that selected source
window, alongside Union-Control motion guidance. An optional opening image is a
frame anchor, not a guaranteed identity replacement. Silent video is not supported
by this profile; choose Two-pass for a video without usable audio.

**Use opening at end** optionally reuses the selected opening image at the final
model frame, with strength 0.7. It is off by default and works with Single-pass
speech as well as Two-pass. It can help appearance consistency but can also
restrain movement or pull the ending pose toward the opening. A separate image
can still be chosen under Ending. Changing this toggle never generates an image
or video; the choice is saved with the draft, shot and immutable take. Export
includes `closing.png`, its frame index and strength, and whether it reused the
opening. This is frame guidance, not an identity adapter or identity guarantee.

The Frame guidance information control opens with mouse, touch or keyboard;
Escape closes it and returns focus. It distinguishes a composed opening/ending
frame from a separate character identity reference. Upload/replace actions name
their active role, and the image thumbnail opens a full-size read-only review.
On phones an empty viewer stays out of the way until there is media or a take
to review. These UI controls do not add a new conditioning input or render job.

The native portrait/square/landscape canvases are 576x1024, 640x640 and 768x448.
Export resizes them 2x with CPU Lanczos to match the studio's other takes; this
is not a model-refined upscale. The supplied sound is retained in the five-second
export. Settings preserve the profile, native dimensions and resize method.
Existing projects and new shots still default to **Two-pass**. Source-audio
conditioning is not a promise of word-perfect mouth timing. The
[evidence notes](tests/REAL_FOOTAGE.md#in-app-speech-workflow-comparison) distinguish
real studio tests from graph/CPU regression checks and unperformed quality gates.

Two-pass video exports also retain the selected source soundtrack. AAC audio is
re-encoded to a sample-aligned five-second track rather than copying a final AAC
packet beyond the picture boundary. This is not a bit-for-bit audio export;
silent sources stay silent.

### Short Projects

Create a New short, choose vertical, square or landscape framing, and start with
a hook/reveal/payoff, before/transformation/after or blank board. A project holds
up to six five-second shots. Set a shared art direction and edit each shot's
scene, motion, inputs and seed; a shot can override or omit the shared direction.
Only Generate take dispatches inference for the selected shot. There is no hidden
batch render. Use in short or the Selected take menu explicitly chooses the
favorite for that shot. Earlier takes remain available for review and revision.

If creating a short loses its reply, **Check creation** retrieves that same short
after reload. Its original details stay fixed until recovery finishes. If the
saved request is not found, **Retry creation** resends the same ID and details;
it does not create a replacement request or start a render. Existing projects
and later edits are retained.

**A/B** compares two completed takes in the current framing. In a project it
uses the active shot's history, plus any explicitly selected existing take.
Both pictures share playback and seeking; Audio selects A, B or muted, never
both soundtracks together. Swap changes the sides. Comparing does not change
the saved shot, choose a winner or submit a render.

**Use A / Use B** explicitly saves that shot's winner without replacing its
editing settings. Outside a project these are **View A / View B**, which only
preview the chosen take. **Seed** copies that take's exact seed into Advanced,
leaving prompts and references intact; generating remains a separate action.
The comparison pair is remembered in account-scoped browser storage, not as a
provider job or an inferred winning take.

Move, duplicate and remove shots without new generation. Duplicating a shot
reuses its chosen take and draft settings; removing it does not delete any take.
Trim in/out are quantized to 24-fps frames. Shot sound runs from mute at zero to
double gain. Export short assembles the chosen takes locally into an MP4 with
stereo 48-kHz AAC, up to 30 seconds long. It does not consume inference credits.
The Edit manifest records the exact saved project, selected take settings and
frozen input hashes. Review it alongside the MP4; it is not a media archive.

Projects autosave into the local app directory and reopen after a browser reload
or app restart. Concurrent stale saves are rejected rather than overwriting a
newer edit. Uncertain saves retain the browser draft and require reopening before
generation. Each take stores its saved shot/project revision; checking an old
submission retrieves that job even after later edits. Local export recovery also
uses its frozen edit, never the current board. Completed exports remain separate.

The real square browser test uses three native takes, including last-frame
chaining for successive openings, and exports 15 seconds. The reveal broadens
from a paper boat to its neon street puddle; the fish payoff remains a creative
review draft. Neither that test nor the developer's installed-package checks
replace the required unfamiliar-human trial. The portable round trip below has
additional native-media browser evidence; broader Cloud/credit qualification
and creative acceptance remain open.

### Portable Projects

Choose **Download project** in the shot's Export menu or the Finish view to
download an editable `.aipg.zip` package. The upload-icon **Import project**
button beside New short opens it as a separate project. Original projects and
their media are not overwritten. Importing, packaging, editing and offline movie
export never submit model work; Generate remains a separate explicit action.

Packages include the complete board, shared/shot direction, source windows,
seeds, workflow profiles, opening/ending references, look auditions, selected
takes, related completed alternate takes, original source media, music/voiceover
and captions. Frozen workflows and their local inputs travel with completed
takes/looks. Pending jobs, failed-job logs, provider recovery IDs, service keys,
account sessions and credit journals do not. Credits and live provider jobs are
not transferable. Imported results are user-supplied media, not Grid attestations.

Checksums, source roles, dimensions, frame/audio clocks and supported workflows
are checked before a single directory rename publishes the imported project and
its assets. IDs are remapped without changing selected media bytes. A lost reply
keeps the saved transfer ID: use **Check transfer** to retrieve the same operation.
An unconfirmed import can be retried with the same file and ID, not another copy.
Look guidance provenance is retained separately from private provider state.

Seeds from zero through 9223372036854775807 retain their exact value across the
editor, saved requests and project packages. Browser transport uses decimal
strings above JavaScript's exact-number range. New take increments exactly and
wraps the maximum seed to zero. If an older browser draft already rounded its
seed, restore the original value or explicitly choose another before generating.

Current limits are 32 completed takes, 64 reference images, 512 media files and
512 MiB of media, with a 514 MiB archive ceiling. Unsupported/custom workflow
nodes are rejected rather than silently rewritten. ZIP parsing uses the standard
library, bounded metadata/decompression and regular files only; no hard links
or archive extraction of arbitrary paths are required. Downloads stream from
saved server artifacts instead of buffering the whole ZIP in browser memory.
There is an interim limit of sixteen saved package builds per workspace; public
retention/deletion, aggregate quotas and decoder isolation are still release work.

A rendering-disabled browser test packages three existing native portrait takes,
recovers deliberately lost download/import replies, preserves their bytes and
references, revises the imported board and exports fifteen seconds with music
and a caption. Tablet and phone import/reload/playback also pass. These are
developer checks, not the independent trial or public-production approval.

### Product Shorts

**Standard flow (calm pacing, the default):** add a product photo, press
**Fill from photo** to draft the brief with an open-weights model on the Grid,
edit it, and create the short. The plan has two long, gentle shots (a slow
push-in hook under the opening caption and a slow pull-back reveal) and a
two-second packshot, so a 9-10 second short has two cuts. Generate each shot's
look, render its take, build the packshot, then press **Generate music** in the
Finish tab: one ACE-Step instrumental runs under the whole short and shot sound
is muted. Choose **Punchy** pacing for one shot per benefit.

**Start from** a template (an approved AIPG short) to copy its pacing, camera
moves, captions and music style; templates never copy media or briefs, and any
finished short can be saved as one. **3 versions** next to a look or take runs
three seeds one at a time and shows them side by side; pick one. Every Generate
button shows an approximate cost or GPU time, and Cloud jobs record measured
spend afterwards. Opt-in effects (wireframe, garden bloom, freezing) sit beside the camera moves
in the picker.

Camera moves come from reviewed presets (push-in, pull-back), each with a preview loop and a recommended trim that keeps
the move gentle. Fill from photo and Generate music need `GRID_API_KEY` in the
server environment; each makes one bounded request and never retries.


Choose **New short → Product ad**, add one to three product photos and a short
brief: name, tone, where the product lives, optional benefits, tagline and call
to action. The app plans a vertical board: a hook, a reveal, one shot per
benefit (or a detail shot) and a closing packshot. Every shot stays editable.

For each scene shot, **Generate product look** places your real photo into that
shot's art direction with FLUX.2 Klein 4B reference editing, then **Generate
take** animates it with LTX 2.5. Scene shots are trimmed to their first three
seconds, where the product is most faithful. On the owned image runtime,
**MOSS refine** adds a light MOSS pass (strength 0.4). MOSS alone is not used to
place products: in native tests it either kept the original photo or replaced
the product. The packshot is built locally from your photo, name, tagline and
call to action; no model draws the product's name or logo. A cut-out PNG with a
transparent background gives the cleanest packshot. Captions start in the
upper position so they do not cover a centered product.

An optional **hook** (ten words at most) becomes the opening caption; pick one
idea, such as a problem, a result first or a curiosity gap. Product shorts
caption only that opening line by default and let the two-second packshot carry
the close; choose **Every shot** to caption each benefit instead.

For apparel, **show it worn by a fictional AI model** plans waist-up model shots
instead of product-only scenes. The model is generated, never a real person's
likeness. Klein usually keeps a chest print readable, but native tests also
produced a misspelled wordmark, so zoom in on every look before rendering.

Packshot titles use a display face matched to the tone (Michroma for bold and
playful, Playfair Display for premium and calm) with Montserrat supporting
lines. Product shorts default to the Studio caption style: heavy Montserrat
with a soft shadow and scrim instead of a box.

Every scene shot's motion prompt carries a tone-matched sound line, because
LTX generates audio from the prompt: without one, native product takes came back
near-silent. Per-shot generated sound changes at every cut, so for a finished
ad prefer one music track: in the Finish tab add music across the whole short,
set each shot's volume to zero and fade out under the packshot.

Prompts never name the product, because image models print a named product's
name onto it. Models can still alter fine surface marks; review every look.
Product looks share the session look limit. Packshots are free local takes and
do not count toward the render limit.

### Sound And Captions

Switch a saved short to Finish to edit music, a voiceover layer and timed
captions. Shot sound stays independently adjustable under Selected take & sound
in the Shot view. Music and voiceover accept supported audio uploads up to 50 MB,
from 0.1 seconds to 30 minutes. This shorter minimum applies only to offline
finishing; audio-conditioned video generation still needs five seconds.

Each layer has a source offset, timeline start, length, gain/mute and fades.
Music can loop; voiceover cannot. Non-looping sources must cover their selected
duration. Timeline positions, lengths and fades use 24-fps frames. Individual
audio players audition source sections; Export short creates the final mix.
Changing a saved edit does not silently replace an older export or its sound.

Captions have editable text and in/out times, Clean/Bold styles and Lower/Center
positions. The lower position leaves space for mobile player/social controls.
The preview uses the same bundled Noto Sans renderer as the burned-in MP4, not
the browser's installed fonts. Unsupported characters (including emoji) and text
too long for readable placement are rejected rather than replaced or clipped.
There are at most 30 cues, each up to 160 characters; cues must not overlap or
extend past the short. Download captions separately as SRT. The font retains its
included SIL OFL license; it is not relicensed under the app's MIT license.

The real square browser test exports three captions and two uploaded audio
layers over the existing 15-second native sequence. Voiceover uses an original
synthetic timing fixture, not spoken narration. Boundary-pixel, audio-copy,
reload and mobile checks are documented in the footage notes; they are not
three approved creative showcases or a completed human trial.

### Owned Video Backend

Owned hardware is a first-class execution path, not a Cloud fallback. The native
LTX 2.5 and MOSS workflows run open-weights models through the official SDK and
`comfy-api-proxy`, without closed partner-model API nodes. Cloud hosting is not
required for this path. Open-weights execution does not relicense the weights:
the [component guide](MODELS.md) records their separate terms.

Install compatible ComfyUI, LTX nodes and the files in the
[component guide](MODELS.md). Start ComfyUI on loopback, then install the
official proxy in a separate environment. POSIX shell example:

```sh
uv venv --python 3.12 .proxy-venv
uv pip install --python .proxy-venv/bin/python comfy-api-proxy==0.1.6
.proxy-venv/bin/comfy-api-proxy run --comfyui http://127.0.0.1:8188 --host 127.0.0.1 --port 18291 --state-dir ./proxy-state
```

Keep that proxy running. In another terminal:

```sh
export COMFY_BASE_URL=http://127.0.0.1:18291
export COMFY_UPSTREAM_URL=http://127.0.0.1:8188
uv run openfield --backend self-hosted
```

Forward both loopback services over SSH for a remote worker and substitute your
forwarded ports. The app checks both before accepting a take: the proxy's own
health route does not check ComfyUI. Do not expose either service publicly.

### Klein Opening Looks On Your Own GPU

`--look-engine klein` runs FLUX.2 Klein 4B (`flux-2-klein-4b.safetensors`,
`qwen_3_4b.safetensors`, `flux2-vae.safetensors`) on the owned image worker set
by `COMFY_LOOK_BASE_URL`/`COMFY_LOOK_UPSTREAM_URL`, the same worker product
looks use. Transform styles were reviewed with Klein looks; MOSS restyles far
more gently.

```sh
uv run openfield --backend self-hosted --look-engine klein --max-renders 6 --max-looks 12
```

### Agents (MCP)

With a studio running, register the stdio server with any MCP client:

```sh
claude mcp add openfield -- uv run --directory /path/to/aipg-cinema openfield-mcp
```

Tools: `list_styles`, `transform_video` (style or direction, 5/10/15 s,
optional `save_to`), `generate_shot`, `run_tool` and `job_status`. The server
only talks to a loopback studio (`OPENFIELD_URL`, default
`http://127.0.0.1:8797`), so the studio's limits, estimates and receipts
apply; each call sends one request and never retries.

### Tools On Cloud Or Your GPU

FPS boost, background removal and upscale are core-node ComfyUI graphs. They
run on the video backend by default; a self-hosted worker needs
`rife_v4.26.safetensors` in `models/frame_interpolation`,
`birefnet.safetensors` in `models/background_removal` and
`RealESRGAN_x2plus.pth` in `models/upscale_models` (Comfy-Org publishes the
first two). Without them, send just the tools to Comfy Cloud:

```sh
uv run openfield --backend self-hosted --look-engine klein --tool-backend cloud
```

Reframe always runs locally with ffmpeg. Inputs are normalized to 24 fps and at
most fifteen seconds; every run downloads as an Open in ComfyUI bundle too.

### Optional MOSS Opening Looks

MOSS Cloud execution is not yet qualified. For an owned ComfyUI with the tested
MOSS loader and weights, run a second loopback official proxy. For example, with
that separate ComfyUI listening on port 8189:

```sh
.proxy-venv/bin/comfy-api-proxy run --comfyui http://127.0.0.1:8189 --host 127.0.0.1 --port 18389 --state-dir ./proxy-state/moss
```

Configure it independently from the video backend:

```sh
export COMFY_LOOK_BASE_URL=http://127.0.0.1:18389
export COMFY_LOOK_UPSTREAM_URL=http://127.0.0.1:8189
uv run --env-file .env openfield --backend cloud --max-renders 6 --max-looks 12
```

Those example ports must point to your own MOSS proxy and ComfyUI, directly or
through SSH forwards. Keep video on Cloud as above, or use the separately
configured owned video backend for a fully owned-hardware session:

```sh
export COMFY_BASE_URL=http://127.0.0.1:18291
export COMFY_UPSTREAM_URL=http://127.0.0.1:8188
export COMFY_LOOK_BASE_URL=http://127.0.0.1:18389
export COMFY_LOOK_UPSTREAM_URL=http://127.0.0.1:8189
uv run openfield --backend self-hosted --look-engine moss --max-renders 6 --max-looks 12
```

This uses the two loopback proxies configured above and needs no Cloud
subscription or Cloud key. Use compatible hardware and the exact native
components in the model guide; the tested hardware is not a minimum-VRAM claim.
`COMFY_LOOK_LOCAL_TOKEN` is optional when this second proxy requires
its own bearer token; neither the video token nor a Cloud key is sent to it.
Without that runtime, opening-image upload and the existing LTX Cloud path still
work; the MOSS generation button stays disabled.

The tested graph needs `moss_image_sft_bf16.safetensors`,
`qwen3.5_9b_int8_convrot.safetensors` with CLIP type `moss_image`, and
`flux2-vae.safetensors`. It uses 50 Euler/simple steps, CFG 3, the publisher's
layer-22 negative-branch skipping, and source-image
denoise of 0.4, 0.65 or 0.75. Balanced (0.65) is the starting value, not a promise
of the best edit on every input. This is source-guided img2img, not a trained
instruction editor. Stronger edits can change object geometry. Model, encoder
and VAE terms remain separate from the app's MIT license.

The look limit counts generated images independently from the video limit.
Requests, results and look history persist locally; recovery retrieves the same
saved job, never a replacement. A look completing after you switch clips is not
applied to the new source or the other frame selection. Takes made with generated
looks additionally export each image workflow, source frame and prompt/seed/denoise
in their settings. The closing MOSS source downloads as `closing-source.png`;
rebind its workflow's `LoadImage` input to that asset rather than the opening
`source.png`. Take settings identify these relative source/workflow filenames.
No direct Grid routing, credit billing or commercial marketplace rights are
implied by this owned-worker path.

A generated frame also keeps its original shot and selection intent. Changing
the image direction, choosing another reference or moving to another shot keeps
that finished image in history instead of replacing the newer draft. Unchanged
inputs still adopt normally after reload; motion-only edits remain independent.
Old saved watches without that intent can be applied explicitly from history.

The CLI supports the same explicit Cloud image option:

```sh
uv run --env-file .env aipg-cinema look source.mp4 --engine klein-cloud --prompt "Relight the existing scene with golden amber key light and copper highlights. Keep the source subject and composition." --run-dir runs/cloud-look --execute
```

Do not pass `--denoise` with Klein. Saved look jobs pin their original backend,
including when the app is later launched with a different image engine. Recovery
downloads that same job; it never submits an image with the newly selected engine.
Cloud execution uploads source frames and render inputs to Comfy Cloud. The key
stays in the server process and is never sent to a loopback MOSS proxy.

## Models, Reproduction and Recovery

The [component guide](MODELS.md) lists exact weight filenames, tested hardware
and applicable model terms. The [quality notes](tests/REAL_FOOTAGE.md) record
real-camera results and failures. Historical Cloud proofs and challenger-model
experiments are kept in private research notes, not alternative app defaults.

The browser retains uncertain submissions across reloads. Check status reads the
saved receipt without submitting generation again, even when the renderer is
offline. A missing receipt keeps the request intact; Retry submission is a
separate explicit action that resends its original ID/settings rather than
creating another take. Reconnecting clears the connection notice without erasing
unrelated form errors. Take settings remain downloadable for unfinished/failed
takes; a finished video is not required to inspect their frozen settings.
These controls do not enable the still-gated hosted credit executor.

Keep the exported source, opening image, workflow and settings together.
The CLI can reproduce or revise a take on the same configured backend:

```sh
uv run --env-file .env aipg-cinema reshoot source.mp4 --model ltx25 --prompt "Your saved art direction" --seed 42 --look-frame look.png --backend cloud --run-dir runs/revision --execute
```

Omit `--look-frame` when the take has no opening image. Use the saved prompt and
seed to reproduce settings, not a promise of bit-identical results across
hardware or runtime revisions. Provider asset-upload names in workflow JSON
must be rebound to your exported files; see the research notes.

The same closing-look path is available in the browser and CLI, with actual
owned-runtime and Cloud SDK tests. It adds native LTX keyframe guidance at
frame 120 with fixed strength 0.7 in both passes. It reduced
look fading in the mountain test; it is not a guarantee of exact geometry or
timing. Opening and closing images should match their source frames' composition.
With the two owned SDK endpoints configured above:

```sh
uv run aipg-cinema look source.mp4 --prompt "Describe the target scene" --denoise 0.75 --frame-index 0 --run-dir runs/opening --execute
uv run aipg-cinema look source.mp4 --prompt "Describe the target scene" --denoise 0.75 --frame-index 120 --run-dir runs/closing --execute
uv run aipg-cinema reshoot source.mp4 --model ltx25 --backend self-hosted --prompt "Follow the source motion and camera timing. Retain the look images throughout one continuous shot." --look-frame runs/opening/look.png --closing-frame runs/closing/look.png --run-dir runs/two-keyframe-take --execute
```

Inspect both images before sending the video. Source-guided edits can alter
framing or delete moving parts, as the rejected lava-lamp test demonstrates.
The two look commands submit two separate images; the video is a third explicit
job. Export `closing.png` alongside the other take inputs when using this path.

Interrupted jobs with a saved ID can be recovered through the app or CLI:

```sh
uv run --env-file .env aipg-cinema resume runs/web/jobs/TAKE_ID/render
```

Resume fetches the same saved job and repeats local export; it does not launch a
replacement render. A missing job ID requires manual backend review. Reconnect
the same proxy endpoint and state directory after a tunnel/proxy interruption.
Do not publish the local `job.json`, which contains private runtime details.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The tests use synthetic fixtures and local FFmpeg, not paid model jobs. A
Node.js installation additionally enables the inline JavaScript event-handler
regression; without it that one test is skipped. This does not replace real
browser checks.
A passing suite is not evidence of creative quality. Public release still needs
a clean-machine user test, final model/asset review and approved publication.
