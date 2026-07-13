# Vendored STAC Browser build

Prebuilt [stac-browser](https://github.com/radiantearth/stac-browser) v4.0.1,
served by `view_catalog.bat` next to the catalog. Viewers need nothing but
python and a web browser.

Rebuild (only to upgrade stac-browser; needs node once):

```
git clone --branch v4.0.1 https://github.com/radiantearth/stac-browser
cd stac-browser
npm install
npm run build -- --catalogUrl="/catalog/catalog.json" --pathPrefix="/browser/" --catalogTitle="Pielach River LiDAR Time Series"
```

Then replace the contents of this folder (keep this README) with `dist/`,
dropping the `*.map` source maps (~15 MB dev-only weight).
`catalogUrl` assumes the catalog lives at `<served root>/catalog/catalog.json`,
`pathPrefix` assumes this folder is served at `/browser/`.
