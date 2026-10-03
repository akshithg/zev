# Product page

GitHub Pages serves these HTML, CSS, and SVG files directly. No build is needed.

Preview from the repository root:

```console
python3 -m http.server 8765 --bind 127.0.0.1 --directory docs
```

To publish, open the repository’s **Settings → Pages**. Choose
**Deploy from a branch**, then **main** and **/docs**, and save.
The site will be available at `https://akshithg.github.io/zev/` when deployment
finishes. All local asset paths are relative so they work under `/zev/`.
