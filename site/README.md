# openfield.video

The product landing page, served as a static Cloudflare Worker.

- `public/index.html` is the whole page; `public/media/` holds the showcase
  and style loops that `build.sh` copies from `src/aipg_cinema/showcase` and
  `src/aipg_cinema/styles`; `public/fonts/` holds the OFL fonts.
- Build and deploy: `cd site && ./build.sh && npx wrangler deploy` (needs Node 22+ and a Cloudflare
  login with the openfield.video zone). The custom domains in
  `wrangler.jsonc` create their DNS records on first deploy.
- No secrets; the build is a file copy.
