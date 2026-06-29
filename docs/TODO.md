# TODO

- [x] Add "mp3" option to the codec selector; when selected, save the result as an mp3 file
- [x] Make menu bar icon on macOS monochrome
- [x] Launch the macOS app in `server-tray` mode from the regular app icon (not the terminal): add a setting in the main app to enable server mode and minimize to the tray, so it no longer requires the pip CLI command
- [x] Make the web UI PWA-ready: it is already installable (Gradio auto-serves `/manifest.json`), but the manifest still points at the default Gradio logo (`static/img/logo_nosize.svg`). Override `/manifest.json` (and apple-touch icons) to serve the app's own icon from `talks_reducer/resources` so the installed PWA shows the Talks Reducer icon instead of the Gradio one
