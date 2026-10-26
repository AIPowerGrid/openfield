# Credits

Openfield's code is MIT. The media bundled for previews and examples keeps its
own licence; none of it is relicensed under MIT. Videos in `showcase/` and
`styles/` are Openfield renders made from the sources below.

## Source footage

| Used in | Source | Author | Licence |
| --- | --- | --- | --- |
| Transform reel; Neon future, Full colour and Van Gogh oil styles; `styles/examples/market1906.mp4` | [A Trip Down Market Street (1906)](https://commons.wikimedia.org/wiki/File:A_Trip_Down_Market_Street_(Library_of_Congress_Print).webm) | Miles Brothers | Public domain |
| Anime, 3D animated film and Golden hour styles; `styles/examples/crosswalk.mp4` | [Diagonal crosswalk, Yonge–Dundas](https://commons.wikimedia.org/wiki/File:DiagonalCrosswalkYongeDundas.webm) | Raysonho @ Open Grid Scheduler / Grid Engine | CC0 |
| Transform reel; Bioluminescent night style; `styles/examples/beach.mp4` | [Aerial view of sand beach. Top view sea waves](https://commons.wikimedia.org/wiki/File:Aerial_view_of_sand_beach._Top_view_sea_waves._Drone_footage.webm) | Nature video, HD - 4K | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Ink wash style; `styles/examples/shanghai.mp4` | [Shanghai Bund, Lujiazui skyline timelapse](https://commons.wikimedia.org/wiki/File:Shanghai_Bund,_Lujiazui_Skyline_Timelapse.webm) | Yigang Yu | CC0 |
| Watercolor style; `styles/examples/horses.mp4` | [Horses running in a pasture](https://commons.wikimedia.org/wiki/File:Horses_running_in_a_pasture.webm) | Field of Dreams | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Transform reel; `styles/examples/car-snow.mp4` | [Aerial views of a car driving in snow through a forest](https://commons.wikimedia.org/wiki/File:Aerial_views_of_a_car_driving_in_snow_through_a_forest.webm) | Vladislav Sanikovich | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |

CC BY changes: trimmed to about ten seconds, scaled to 1920x1080 or smaller,
re-encoded at 24 fps without audio, and restyled by Openfield in the renders.

## Paintings and music

| Used in | Work | Author | Licence |
| --- | --- | --- | --- |
| Animate a photo showcase | [The Starry Night](https://commons.wikimedia.org/wiki/File:Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg) (1889) | Vincent van Gogh | Public domain |
| Animate a photo showcase | [Impression, Sunrise](https://commons.wikimedia.org/wiki/File:Monet_-_Impression,_Sunrise.jpg) (1872) | Claude Monet | Public domain |
| Shot from audio showcase | [In the Hall of the Mountain King](https://commons.wikimedia.org/wiki/File:Grieg_-_Peer_Gynt_Suite_No._1,_Op._46_-_IV._In_the_Hall_of_the_Mountain_King_(Musopen_Symphony).flac) | Edvard Grieg, performed by Musopen Symphony | Public domain |

## Product, fonts and icons

- The AIPG bottle, mug and tee photos, the product ad and template previews are
  AI Power Grid's own.
- Fonts: Montserrat, Michroma, Playfair Display and Noto Sans under the SIL Open
  Font License 1.1 (see `src/aipg_cinema/fonts/`).
- Icons: [Lucide](https://lucide.dev) under the ISC licence (see
  `src/aipg_cinema/icons/LICENSE`).

## Models

Renders use open models run through ComfyUI: LTX-2.5 with the LTX Union
Control IC-LoRA, FLUX.2 Klein 4B, RIFE v4.26, BiRefNet, RealESRGAN and Depth
Anything V2 Small, plus Whisper (faster-whisper) for captions and an optional
local Phi-4-mini prompt helper. Each model has its own licence; see `MODELS.md`. Our code
licence grants no rights to model weights.

## LTX LoRAs

Effects and Change what they say use LoRAs hosted by Comfy Cloud, under the
LTX-2 Community License unless their source says otherwise:
Lightricks' DubIt and Cross-Eyed IC-LoRAs, kabachuha's Inflate and Hydraulic
Press LoRAs, TheBurgstall's Googly Eyes LoRA, the Squish LoRA from Comfy Org's
LTX-2 template, and Nebsh's Atomic Explosion LoRA (no license stated). Change
what they say follows Lightricks' published DubIt two-stage recipe; the LTX-2
effect graph is adapted from Comfy Org's MIT-licensed LTX-2 LoRA template.
Sources for each are listed in `src/aipg_cinema/effects.py` and
`src/aipg_cinema/lipdub.py`.
