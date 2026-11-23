# ClawSona project page

A static English/Russian page with no framework, hosted model calls, analytics,
remote fonts, package installation or runtime server dependency. Example dialogs
are labeled illustrations. Audio controls play actual ElevenLabs samples.

## Preview

From the repository root:

```bash
uv run python scripts/build_site.py
python3 -m http.server 4173 --directory website/dist --bind 127.0.0.1
```

Open `http://127.0.0.1:4173`. The build copies the static page, shared SVG assets,
public samples and the verified source release into `website/dist`. It does not
read `.env`, OpenClaw profiles, private logs or model weights. Build the source
release with `uv build` before building the page.

`site-config.json` points to [mdfr11/clawsona](https://github.com/mdfr11/clawsona).
When hosting a fork, change `repository_url` to your real repository URL. The GitHub link
is shown only when that value is valid; source download works independently.

## GitHub Pages

The repository includes a manually triggered `pages.yml` workflow. In the public
repository, select **Settings → Pages → Source: GitHub Actions**, then run the
**Project page** workflow. It builds the source archive and the static page,
and publishes the `website/dist` artifact. Relative URLs support project subpaths.
No API keys or account tokens belong in the website.

## Media

`media/hello-ru.mp3` and `media/hello-en.mp3` are generated samples, not microphone
recordings. See [media provenance](media/README.md) and the
[third-party notices](../docs/THIRD_PARTY_NOTICES.md). The site does not request
microphone access. Shared artwork lives in `docs/assets`.
