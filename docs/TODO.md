# TODO

- [x] Add VAD speedup mode
  - Use Silero VAD or another light model to detect speech instead of relying on loudness alone.
  - Add a "Speedup no voice" checkbox to the UI next to the silence speedup controls (same row in the GUI).
  - Add preset `Voice`: Optimal + VAD.
- [ ] Remove experimental VAD engines (torch, ten) and --vad-engine/--vad-dump before release
