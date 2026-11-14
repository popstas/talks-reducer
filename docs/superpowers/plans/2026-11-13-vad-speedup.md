# VAD speedup mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Режим «Speedup no voice»: речь размечает Silero VAD вместо порога громкости, всё остальное идёт на `silent_speed`; чекбокс в GUI, пресет Voice, настройки VAD в Advanced, экспериментальные CLI-движки `torch` и `ten` для сравнения.

**Architecture:** Новый модуль `talks_reducer/vad.py` превращает уже извлечённый `audio_data` в булеву маску по кадрам видео той же длины, что `chunks.detect_loud_frames`; дальше пайплайн не меняется. Движки спрятаны за одним интерфейсом (вероятности по окнам + шаг окна), постобработка общая. Флаг `vad` проходит по всем поверхностям так же, как `fps`: `ProcessingOptions` → CLI → пресеты → GUI → remote API → Web UI → OBS dock.

**Tech Stack:** Python 3.10+ (CI 3.11), numpy, `silero-vad-lite` (основной), `silero-vad`+`torch` и `ten-vad` (extras), Tkinter, gradio, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-11-13-vad-speedup-design.md`

## Global Constraints

- `vad=False` (дефолт) — результат обработки байт-в-байт прежний; `detect_loud_frames` вызывается как раньше.
- VAD включён, а движок не импортируется → `VadUnavailableError` (наследник `RuntimeError`) с командой установки; **никакого** фолбэка на громкость.
- Зависимость: `silero-vad-lite>=0.4.0; python_version >= "3.10"` в `pyproject.toml` `dependencies` и в `requirements.txt`.
- Extras: `vad-torch = ["silero-vad>=6.0"]`, `vad-ten = ["ten-vad>=1.0.6"]`. `ten-vad` никогда не попадает в обязательные зависимости и в установщик (лицензия Apache 2.0 + условия Agora).
- Движки `torch`/`ten` — только CLI (`--vad-engine`). GUI, Web UI, dock, remote-сервер всегда используют `lite`; поле движка в remote API не передаётся.
- Дефолты: `vad_threshold=0.5`, `vad_padding_ms=150`, `vad_min_silence_ms=300`; внутренняя константа `MIN_SPEECH_MS = 250`.
- Метка поля пресета и чекбокса: `Speedup no voice`. Подсказка у заблокированного Threshold: `Not used with Speedup no voice`.
- Пресет **Voice**: `resolution="720p", fps="orig", silent_speed=10.0, sounded_speed=1.0, silent_threshold=0.01, video_codec="hevc", vad=True`, стоит сразу после Optimal.
- `PRESETS_VERSION = 3`.
- Каждая задача: `black` + `isort` на изменённых файлах, `.venv/Scripts/python -m pytest -q` зелёный перед коммитом.
- Коммиты без `feat:`/`fix:` для служебных шагов; фичевые коммиты — `feat:`.

## Review Focus

1. **Запись без речи вообще (только шум)** → маска вся `False`, весь ролик на `silent_speed`, без исключения в `build_chunks`/аудио. Тест: Task 2 `test_vad_all_noise_produces_single_silent_chunk`.
2. **Клип короче одного окна VAD (< 32 мс аудио) или пустой** → последнее окно дополняется нулями, маска нужной длины. Тест: Task 1 `test_detect_voice_frames_shorter_than_window`.
3. **Частота дискретизации не кратна 16 кГц (44100) и разные dtype WAV (int16, int32, float32), стерео** → корректная нормализация в [-1, 1] и длина после ресэмплинга. Тесты: Task 1 `test_to_mono_16k_*`.
4. **VAD вместе с Cut video и Remove ranges** → маска считается по обрезанному аудио, `apply_remove_ranges` применяется после. Тест: Task 2 `test_vad_with_remove_ranges_keeps_removed_chunks`.
5. **Переключение Voice → Optimal выключает VAD; пользовательский пресет без поля `vad` в Simple mode не включает VAD.** Тесты: Task 4 `test_optimal_after_voice_turns_vad_off`, Task 5 `test_simple_mode_ignores_remembered_vad`.

---

### Task 1: Ядро VAD (`vad.py`) и движок `lite`

**Files:**
- Create: `talks_reducer/vad.py`
- Modify: `pyproject.toml` (dependencies, optional-dependencies), `requirements.txt`
- Test: `tests/test_vad.py`

**Interfaces:**
- Produces:
  - `VAD_SAMPLE_RATE = 16000`, `MIN_SPEECH_MS = 250`, `ENGINE_NAMES = ("lite", "torch", "ten")`
  - `class VadUnavailableError(RuntimeError)`
  - `@dataclass(frozen=True) class VadSettings: engine: str = "lite"; threshold: float = 0.5; padding_ms: int = 150; min_silence_ms: int = 300`
  - `class VadEngine(Protocol): name: str; hop_samples: int; def probabilities(self, audio: np.ndarray, progress: Optional[Callable[[int], None]] = None) -> np.ndarray` — `audio` моно float32 16 кГц в [-1, 1]; возвращает по вероятности на окно `hop_samples`; `progress` получает приращения числа окон.
  - `load_engine(name: str) -> VadEngine` — `"lite"` → `LiteEngine` (`hop_samples=512`); неизвестное имя → `ValueError`; не импортируется → `VadUnavailableError` с текстом `pip install silero-vad-lite` / `pip install talks-reducer[vad-torch]` / `pip install talks-reducer[vad-ten]`.
  - `to_mono_16k(audio_data: np.ndarray, sample_rate: int) -> np.ndarray` (float32)
  - `speech_intervals(probs: np.ndarray, hop_seconds: float, settings: VadSettings, total_seconds: float) -> list[tuple[float, float]]`
  - `intervals_to_frame_mask(intervals: Sequence[tuple[float, float]], frame_count: int, frame_rate: float) -> np.ndarray` (bool, длина `frame_count`)
  - `@dataclass(frozen=True) class VadResult: mask: np.ndarray; intervals: list[tuple[float, float]]; engine: str; seconds: float; speech_ratio: float`
  - `detect_voice_frames(audio_data: np.ndarray, sample_rate: int, frame_rate: float, frame_count: int, settings: VadSettings, *, engine: Optional[VadEngine] = None, progress: Optional[Callable[[int], None]] = None) -> VadResult` — `engine=None` → `load_engine(settings.engine)`; `seconds` — время инференса (`time.perf_counter`); `speech_ratio` — доля `True` в маске.
  - `count_windows(sample_count_16k: int, hop_samples: int) -> int` — `ceil`, минимум 1 (для `total` задачи прогресса).

- [ ] **Step 1: Write the failing tests** в `tests/test_vad.py` (фейковый движок — класс с `name="fake"`, `hop_samples=512`, отдающий заданный массив вероятностей):
  - `test_to_mono_16k_int16_stereo_48k`: `np.full((48000, 2), 16384, np.int16)` → длина 16000, все значения ≈ 0.5 (`atol=1e-3`), dtype float32.
  - `test_to_mono_16k_44100_float32`: 44100 сэмплов float32 → длина в `{15999, 16000, 16001}`; синус 440 Гц: доминирующая частота FFT результата 440 ± 5 Гц.
  - `test_to_mono_16k_int32`: int32 полной шкалы → значения в [-1, 1].
  - `test_speech_intervals_hysteresis`: hop 0.032 с, probs `[0.1]*10 + [0.9]*20 + [0.3]*3 + [0.9]*20 + [0.1]*30`, `padding_ms=0, min_silence_ms=300` → один интервал (провал 0.3 короче 300 мс и выше `threshold-0.15` склеивается), начало ≈ 0.32 с.
  - `test_speech_intervals_drops_short_speech`: один всплеск 0.9 длиной 3 окна (96 мс < `MIN_SPEECH_MS`) → `[]`.
  - `test_speech_intervals_padding_clamped`: речь с 0 с, `padding_ms=150` → начало `0.0`, конец ≤ `total_seconds`.
  - `test_speech_intervals_splits_long_pause`: две речи, разделённые 1 с тишины при `min_silence_ms=300` → два интервала.
  - `test_intervals_to_frame_mask`: интервал `(1.0, 2.0)`, 30 fps, 90 кадров → `True` ровно на кадрах 30..59 (кадр отмечается, если перекрывает интервал).
  - `test_detect_voice_frames_shorter_than_window`: 100 сэмплов 48 кГц, фейковый движок → `mask.shape == (frame_count,)`, без исключения.
  - `test_detect_voice_frames_reports_progress`: сумма приращений `progress` == `count_windows(...)`.
  - `test_load_engine_unknown_raises_value_error`, `test_load_engine_missing_package_raises_unavailable` (через `monkeypatch.setitem(sys.modules, "silero_vad_lite", None)`; текст содержит `pip install silero-vad-lite`).
  - `test_lite_engine_detects_silence` (`pytest.importorskip("silero_vad_lite")`): 2 с нулей → все вероятности < 0.5, длина `count_windows(32000, 512)`.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_vad.py -q` — Expected: FAIL (`ModuleNotFoundError: talks_reducer.vad`).

- [ ] **Step 3: Добавить зависимости и установить**: `silero-vad-lite` в `pyproject.toml`/`requirements.txt` с маркером из Global Constraints, extras `vad-torch`/`vad-ten`; `.venv/Scripts/python -m pip install "silero-vad-lite>=0.4.0"`.

- [ ] **Step 4: Implement `talks_reducer/vad.py`.**
  - `to_mono_16k`: нормализация по dtype (`int16` / 32768, `int32` / 2³¹, `uint8` → (x−128)/128, float как есть, `clip(-1, 1)`), среднее по каналам; если `sample_rate % 16000 == 0` — усреднение блоками по `sample_rate // 16000`, иначе `np.interp` блоками по 10 с (не строить индексный массив на весь час аудио).
  - `speech_intervals` — постобработка как в Silero `get_speech_timestamps`:
    ```text
    neg = threshold - 0.15
    triggered = False; start = None; temp_end = None
    for i, p in enumerate(probs):
        t = i * hop
        if p >= threshold: temp_end = None; if not triggered: triggered, start = True, t
        elif triggered and p < neg:
            temp_end = temp_end if temp_end is not None else t
            if t + hop - temp_end >= min_silence: emit(start, temp_end); triggered = False; temp_end = None
    if triggered: emit(start, total_seconds)
    отбросить интервалы короче MIN_SPEECH_MS; расширить каждый на padding в обе стороны,
    обрезать по [0, total_seconds], слить перекрывающиеся.
    ```
  - `LiteEngine.probabilities`: `SileroVAD(16000)`, окна по 512 сэмплов, последнее дополнить нулями, `vad.process(memoryview(np.ascontiguousarray(chunk, np.float32)))`; `progress` вызывать пачками по 1000 окон и остатком.

- [ ] **Step 5: Run** `.venv/Scripts/python -m pytest tests/test_vad.py -q` — Expected: PASS.

- [ ] **Step 6: Commit**
  ```bash
  git add talks_reducer/vad.py tests/test_vad.py pyproject.toml requirements.txt
  git commit -m "feat: Add Silero VAD speech detection module"
  ```

### Task 2: VAD в пайплайне, `ProcessingOptions` и CLI

**Files:**
- Modify: `talks_reducer/models.py` (`ProcessingOptions`), `talks_reducer/pipeline.py:604-625`, `talks_reducer/cli.py` (`_build_parser`, сборка `option_kwargs` ~588-635)
- Test: `tests/test_pipeline.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `vad.detect_voice_frames`, `vad.VadSettings`, `vad.count_windows`, `vad.load_engine` (Task 1).
- Produces:
  - `ProcessingOptions` поля: `vad: bool = False`, `vad_engine: str = "lite"`, `vad_threshold: float = 0.5`, `vad_padding_ms: int = 150`, `vad_min_silence_ms: int = 300`, `vad_dump: bool = False`.
  - CLI: `--vad` / `--no-vad` (`dest="vad"`, default `None`), `--vad-engine {lite,torch,ten}`, `--vad-threshold FLOAT`, `--vad-padding MS` (`dest="vad_padding_ms"`, int), `--vad-min-silence MS` (`dest="vad_min_silence_ms"`, int), `--vad-dump` (store_true, help помечает «experimental»).
  - Стадия прогресса `"Voice detection:"` (unit `"windows"`).
  - Лог-строка: `Voice detection ({engine}): {seconds:.1f} s, speech {ratio:.0%} of audio`.
  - `--vad-dump` пишет `<input stem>.vad-<engine>.txt` рядом с выходным файлом: строка на интервал `HH:MM:SS.mmm\tHH:MM:SS.mmm` (через `timecode.format_timecode(..., milliseconds=True)`).

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_pipeline.py` (по образцу существующих тестов с фейковыми зависимостями; `vad.detect_voice_frames` подменить через `monkeypatch`):
    - `test_vad_off_uses_loud_frame_detection`: `vad=False` → `detect_voice_frames` не вызывается, `detect_loud_frames` вызывается.
    - `test_vad_on_replaces_loud_frame_detection`: `vad=True` → `detect_loud_frames` не вызывается, маска из VAD уходит в `build_chunks`; в логе строка `Voice detection (fake):`.
    - `test_vad_all_noise_produces_single_silent_chunk`: маска вся `False` → обработка завершается, все чанки с индексом скорости 0.
    - `test_vad_with_remove_ranges_keeps_removed_chunks`: VAD + `remove_ranges` → в чанках есть `REMOVED_SPEED_INDEX`.
    - `test_vad_unavailable_propagates`: `detect_voice_frames` бросает `VadUnavailableError` → исключение доходит до вызывающего (не глотается).
    - `test_vad_dump_writes_intervals_file`.
  - `tests/test_cli.py`: `test_vad_flags_map_to_options` (все пять флагов → поля `ProcessingOptions`), `test_no_vad_flag_sets_false`, `test_vad_engine_rejects_unknown` (`SystemExit`).

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_pipeline.py tests/test_cli.py -q -k vad` — Expected: FAIL.

- [ ] **Step 3: Implement.** В `pipeline.speed_up_video` при `options.vad` вместо `detect_loud_frames` — `with reporter.task(desc="Voice detection:", total=count_windows(...), unit="windows") as task: result = vad.detect_voice_frames(..., progress=task.advance)`; `has_loud_audio = result.mask`; лог; dump. В `cli.py` — флаги и перенос в `option_kwargs` по образцу `silent_threshold`.

- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` — Expected: PASS (весь набор: дефолтный путь не изменился).

- [ ] **Step 5: Commit** — `feat: Speed up non-voice frames with --vad`.

### Task 3: Экспериментальные движки `torch` и `ten` (только CLI)

**Files:**
- Modify: `talks_reducer/vad.py` (`TorchEngine`, `TenEngine`, ветки в `load_engine`)
- Test: `tests/test_vad.py`

**Interfaces:**
- Consumes: `VadEngine`, `load_engine`, `VadUnavailableError` (Task 1).
- Produces: `TorchEngine` (`name="torch"`, `hop_samples=512`), `TenEngine` (`name="ten"`, `hop_samples=256`).

- [ ] **Step 1: Write the failing tests:**
  - `test_load_engine_torch_missing_raises_unavailable` / `test_load_engine_ten_missing_raises_unavailable` (текст содержит `talks-reducer[vad-torch]` / `talks-reducer[vad-ten]`).
  - `test_torch_engine_detects_silence` (`importorskip("silero_vad")`), `test_ten_engine_detects_silence` (`importorskip("ten_vad")`): 2 с нулей → вероятности < 0.5, длина `count_windows(32000, hop)`.
  - `test_engines_agree_on_speech_ratio` (`importorskip` обоих silero-пакетов): на синтетическом сигнале `lite` и `torch` дают одинаковые интервалы (`speech_intervals`, допуск одно окно).

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_vad.py -q` — Expected: FAIL на `*_missing_*`.

- [ ] **Step 3: Implement.** `TorchEngine`: `from silero_vad import load_silero_vad`; `model = load_silero_vad(); model.reset_states()`; на окно `model(torch.from_numpy(chunk), 16000).item()` под `torch.no_grad()`. `TenEngine`: `from ten_vad import TenVad`; `TenVad(hop_size=256)` (его собственный флаг не используется — порог применяет общая постобработка); вход — `int16` (`(chunk * 32767).astype(np.int16)`), берётся вероятность (первый элемент результата `process(...)`; сверить с README `ten-vad`). Импорты ленивые, внутри `load_engine`.

- [ ] **Step 4: Установить extras и прогнать:** `.venv/Scripts/python -m pip install -e ".[vad-torch,vad-ten]"`, затем `.venv/Scripts/python -m pytest tests/test_vad.py -q` — Expected: PASS без skip.

- [ ] **Step 5: Commit** — `feat: Add experimental torch and TEN VAD engines for --vad-engine`.

### Task 4: Пресеты — поле `vad`, Voice, миграция v3

**Files:**
- Modify: `talks_reducer/presets.py`, `talks_reducer/cli.py:_apply_preset_to_args`, `talks_reducer/gui/preset_dialog.py` (`FIELD_SPECS` выводится из `PRESET_FIELD_LABELS` — проверить, что bool-поле рендерится чекбоксом без значения-числа)
- Test: `tests/test_presets.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `--vad`/`--no-vad` (Task 2).
- Produces:
  - `Preset.vad: Optional[bool] = None`; `"vad"` в конце `PRESET_VALUE_FIELDS`; `PRESET_FIELD_LABELS["vad"] = "Speedup no voice"`.
  - `from_dict`: `vad` → `bool` или `None`; `to_dict` пишет `true/false`.
  - `preset_to_cli_args`: `vad=True` → `--vad`, `False` → `--no-vad`.
  - `describe_preset_fields`: `Speedup no voice: on` / `off`.
  - `match_preset`: `vad` сравнивается точно с `bool(values.get("vad", False))`.
  - `DEFAULT_PRESETS`: Voice после Optimal (значения — Global Constraints); у Compatible, Optimal, Smallest, Compress, mp3 — `vad=False`.
  - `_migrate_v2_entries(raw: list) -> list` — каждому dict с `silent_speed` и без `vad` добавить `vad: False`; если нет пресета с именем `voice` (casefold) — вставить `DEFAULT_PRESETS`-Voice после первого `Optimal` (casefold), иначе в конец.
  - `load_presets`: `version < 2` → `_migrate_v1_entry` по элементам; затем `version < 3` → `_migrate_v2_entries`; один `save_settings` с маркером 3.

- [ ] **Step 1: Write the failing tests** (`tests/test_presets.py`):
  - `test_vad_round_trips_sparse` (`Preset(name="x", vad=True)` ↔ dict; без поля → `None`).
  - `test_preset_to_cli_args_vad_true_false`.
  - `test_describe_preset_lists_vad`.
  - `test_match_preset_distinguishes_vad`: значения Optimal + `vad=True` → `"Voice"`, + `vad=False` → `"Optimal"`.
  - `test_optimal_after_voice_turns_vad_off`: CLI `--preset Voice` → `vad=True`; `--preset Optimal` → `vad=False` (не наследует).
  - `test_fresh_install_seeds_voice_and_v3_marker`.
  - `test_v2_migration_adds_vad_false_and_inserts_voice_after_optimal`.
  - `test_v2_migration_keeps_existing_voice_preset` (пользовательский `voice` не трогается, второй не добавляется).
  - `test_v2_migration_appends_voice_when_no_optimal`.
  - `test_v1_file_migrates_through_v3` (старый `"1080p"` → `"orig"` и Voice добавлен).
  - `test_migration_leaves_sparse_preset_without_silent_speed_alone`.
  - `tests/test_cli.py`: `test_explicit_no_vad_beats_voice_preset`.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_presets.py tests/test_cli.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement** по Interfaces; `_apply_preset_to_args` пишет `parsed_args.vad`, если `"vad" not in explicit`. Обновить существующие тесты, которые фиксируют список/количество дефолтных пресетов или `PRESETS_VERSION == 2`.

- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` — Expected: PASS.

- [ ] **Step 5: Commit** — `feat: Add Voice preset with Speedup no voice`.

### Task 5: GUI — чекбокс Speedup no voice

**Files:**
- Modify: `talks_reducer/gui/layout.py` (строка Silence speedup ~916-947, `apply_preset_to_gui`, `advanced_preset_values`, `build_sparse_preset`), `talks_reducer/gui/app.py` (`vad_var`, `_collect_arguments`), `talks_reducer/gui/preferences.py`
- Test: `tests/test_gui_layout.py`, `tests/test_gui_app.py`, `tests/test_gui_real_tk.py`

**Interfaces:**
- Consumes: `Preset.vad`, `match_preset` с `vad` (Task 4); `ProcessingOptions.vad` (Task 2).
- Produces:
  - `gui.vad_var: tk.BooleanVar`, сохраняется в `GUIPreferences` ключом `vad_enabled` (default `False`); trace → `refresh_advanced_preset_selection`.
  - `gui.vad_check: ttk.Checkbutton(text="Speedup no voice")`, `pack(side=LEFT, padx=(CHECKBOX_ROW_GAP, 0))` в `gui.basic_presets_frame` после `basic_preset_control.frame`.
  - `advanced_preset_values()["vad"] = bool(gui.vad_var.get())`; `build_sparse_preset` кладёт `vad` как `bool`.
  - `apply_preset_to_gui`: `preset.vad is not None` → `gui.vad_var.set(preset.vad)`.
  - `update_threshold_for_vad(gui) -> None` в `layout.py`: при `vad_var` → Threshold-контрол (`SegmentedChoice` silent_threshold) заблокирован, тултип `Not used with Speedup no voice`; иначе — восстановлен. Вызывается из trace `vad_var` и после построения.
  - `_collect_arguments`: Advanced → `args["vad"] = bool(vad_var)`; Simple → `args["vad"] = True` только если выбранный в `simple_preset_var` пресет имеет `vad is True`, иначе `False`.

- [ ] **Step 1: Write the failing tests:**
  - `test_gui_layout.py`: `test_vad_check_packed_in_silence_speedup_row` (родитель — `basic_presets_frame`); `test_apply_preset_to_gui_sets_vad`; `test_apply_preset_without_vad_leaves_var`; `test_threshold_disabled_when_vad_on`; расширить `test_basic_options_frame_grid_positions_do_not_collide`, если меняется сетка.
  - `test_gui_app.py`: `test_collect_arguments_includes_vad_in_advanced`; `test_simple_mode_ignores_remembered_vad` (`vad_var=True`, Simple, выбранный пресет без `vad` → `args["vad"] is False`); `test_simple_mode_voice_preset_enables_vad`; `test_vad_preference_persists`.
  - `test_gui_real_tk.py`: `test_vad_check_shares_row_with_silence_speedup` — в реальном окне `vad_check.winfo_y()` совпадает с кнопками Silence speedup (± 4 px) и чекбокс правее них.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_gui_layout.py tests/test_gui_app.py tests/test_gui_real_tk.py -q -k vad` — Expected: FAIL.

- [ ] **Step 3: Implement** по Interfaces.

- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` — Expected: PASS. Запустить GUI (`.venv/Scripts/python -m talks_reducer.gui`), скриншотом проверить, что чекбокс в одной строке с Silence speedup, Threshold блокируется, выбор Voice ставит галочку, Optimal снимает.

- [ ] **Step 5: Commit** — `feat: Add Speedup no voice checkbox to the GUI`.

### Task 6: GUI — Advanced-настройки VAD и стадия прогресса

**Files:**
- Modify: `talks_reducer/gui/layout.py` (`advanced_frame` ~1204+), `talks_reducer/gui/app.py` (`_collect_arguments`, `_apply_stage_transition`), `talks_reducer/gui/progress.py`, `talks_reducer/gui/summaries.py` (`_TASK_PERCENT_PATTERN`, ветка stage-handling ~374), `talks_reducer/gui/remote.py` (~372, отмена таймера), `talks_reducer/gui/preferences.py`
- Test: `tests/test_gui_layout.py`, `tests/test_gui_app.py`, `tests/test_gui_progress.py`, `tests/test_gui_summary_parsing.py`

**Interfaces:**
- Consumes: `ProcessingOptions.vad_threshold/vad_padding_ms/vad_min_silence_ms` (Task 2).
- Produces:
  - Строки в `advanced_frame` через `layout.add_segmented`: **VAD threshold** `0.3/0.5/0.7` (custom 0.05–0.95, default 0.5, `vad_threshold_var`), **Voice padding, ms** `0/150/300/500` (custom 0–2000, default 150, `vad_padding_var`), **Min pause, ms** `100/300/500/1000` (custom 0–5000, default 300, `vad_min_silence_var`); preferences `vad_threshold`, `vad_padding_ms`, `vad_min_silence_ms`. Строки видны всегда в Advanced (не зависят от галочки).
  - `_collect_arguments` добавляет три значения только при `args["vad"]`.
  - `STAGE_PROGRESS_RANGES`: `("extracting audio:", 5, 10)`, `("voice detection:", 10, 15)`, `("audio processing:", 15, 20)`; остальные без изменений.
  - `Voice detection` в `_TASK_PERCENT_PATTERN`; начало стадии `voice detection` отменяет синтетический таймер так же, как `audio processing` (`_apply_stage_transition`, `summaries.py`, `remote.py`).

- [ ] **Step 1: Write the failing tests:** `test_vad_advanced_rows_registered_in_slider_updaters`; `test_collect_arguments_vad_settings_only_when_enabled`; `test_map_stage_progress_voice_detection_band` (50% → 12.5); `test_audio_processing_band_starts_at_15`; `test_voice_detection_cancels_synthetic_timer`; `test_task_percent_pattern_matches_voice_detection`.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest -q -k "vad or voice or stage"` — Expected: FAIL.

- [ ] **Step 3: Implement** по Interfaces; обновить тесты, фиксирующие старые границы полос.

- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` — Expected: PASS. Реальное окно: строки VAD в Advanced, `…`-слоты не сдвигают строку при редактировании.

- [ ] **Step 5: Commit** — `feat: Add VAD settings to Advanced options`.

### Task 7: Remote API, Web UI, OBS dock

**Files:**
- Modify: `talks_reducer/service_client.py:517-585`, `talks_reducer/server.py` (`process_video_ui`, `process_video_api`, `process_video`, `build_interface`, `preset_to_web_controls` ~1166), `talks_reducer/gui/remote.py:481-501`, `talks_reducer/cli.py:_process_via_server`, `talks_reducer/dock_server.py:build_args/start_talks_reducer`, `talks_reducer/resources/dock.html`
- Test: `tests/test_service_client.py`, `tests/test_server.py`, `tests/test_gui_remote.py`, `tests/test_dock_server.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `ProcessingOptions.vad*` (Task 2), `Preset.vad` (Task 4).
- Produces:
  - `send_video(..., vad: bool = False, vad_threshold: Optional[float] = None, vad_padding_ms: Optional[int] = None, vad_min_silence_ms: Optional[int] = None)` (keyword-only). При `vad=True` к `submit_args` добавляются `(target_height, frame_rate_cap, True, threshold, padding, min_silence)` — хвост `target_height, frame_rate_cap` дописывается и тогда, когда сам по себе не нужен, потому что аргументы позиционные. При `vad=False` — поведение прежнее (старые серверы совместимы).
  - `process_video_api(..., max_frame_rate: float = 0.0, vad: bool = False, vad_threshold: Optional[float] = None, vad_padding_ms: Optional[int] = None, vad_min_silence_ms: Optional[int] = None)`; `process_video` переносит их в `ProcessingOptions` (`vad_engine` всегда `"lite"`); `VadUnavailableError` на сервере отдаётся как ошибка обработки с текстом исключения.
  - Web UI: `gr.Checkbox(label="Speedup no voice")` рядом с контролами скорости, `process_video_ui(..., fps, vad: bool = False, ...)`; `preset_to_web_controls` кладёт `"vad"` для пресетов с полем.
  - Dock: чекбокс `Speedup no voice` в ⚙️ панели (не перемещается логикой preset/Custom, как FPS/Codec); поле `vad` → `build_args(..., vad: bool = False)` → `--vad` в ручном режиме; с выбранным пресетом — пресет решает.
  - GUI remote и CLI `_process_via_server` передают `vad` и три настройки.

- [ ] **Step 1: Write the failing tests:** `test_send_video_appends_vad_tail` (позиции и значения в `submit_args`); `test_send_video_without_vad_keeps_legacy_args`; `test_process_video_api_passes_vad_to_options`; `test_process_video_vad_unavailable_reports_error`; `test_web_preset_controls_include_vad`; `test_gui_remote_passes_vad_settings`; `test_cli_remote_passes_vad`; `test_dock_build_args_vad`.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest -q -k vad` — Expected: FAIL.

- [ ] **Step 3: Implement** по Interfaces.

- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` — Expected: PASS. Живая проверка: `talks-reducer --server` локально + GUI в Remote с галочкой → лог сервера содержит `Voice detection (lite):`.

- [ ] **Step 5: Commit** — `feat: Support Speedup no voice in Web UI, OBS dock and remote mode`.

### Task 8: Сборка, сравнение движков, документация

**Files:**
- Modify: `talks-reducer.spec` (при необходимости `collect_dynamic_libs("silero_vad_lite")` + `collect_data_files`), `tests/test_pyinstaller_spec.py`, `README.md`, `docs/cli.md`, `docs/gui.md`, `docs/build.md` (если описывает зависимости), `CLAUDE.md`, `docs/TODO.md`

- [ ] **Step 1: Test** `test_spec_collects_silero_vad_lite` в `tests/test_pyinstaller_spec.py` (по образцу существующих проверок спеки) — FAIL, затем правка спеки — PASS.

- [ ] **Step 2: Собрать exe** по `docs/build.md`; запустить собранный exe на эталонном видео с `--vad`: в логе `Voice detection (lite):`, обработка завершается. Записать прирост размера `dist/talks-reducer-windows` (ожидание ≤ 10 МБ по анти-цели).

- [ ] **Step 3: Сравнение** на `C:\Users\popstas\Videos\VID_20260220_145304_DOLBY_small_480.mp4` из `.venv` — четыре прогона с `-o` в разные файлы рядом с исходником (`_novad`, `_vad-lite`, `_vad-torch`, `_vad-ten`) и `--vad-dump`:
  ```bash
  .venv/Scripts/python -m talks_reducer "<video>" -o "<video>_novad.mp4"
  .venv/Scripts/python -m talks_reducer "<video>" --vad --vad-engine lite --vad-dump -o "<video>_vad-lite.mp4"
  ```
  (аналогично `torch`, `ten`). Таблица: время `Voice detection`, общее время, длительность результата (ffprobe), доля речи. Таблица идёт в описание PR.

- [ ] **Step 4: Документация.** README: чекбокс, пресет Voice, флаги `--vad*`, отдельный абзац «Experimental engines» с extras и пометкой о лицензии TEN. `docs/cli.md`, `docs/gui.md`. `CLAUDE.md`: поле пресета `vad`, миграция v3 (Voice добавляется в существующие списки — осознанное исключение), полоса `Voice detection` в Progress Convention, `vad.py` в Repository Structure. `docs/TODO.md`: отметить задачу и добавить `- [ ] Remove experimental VAD engines (torch, ten) and --vad-engine/--vad-dump before release`.

- [ ] **Step 5: Run** `.venv/Scripts/python -m pytest -q`, `black --check .`, `isort --check-only .` — Expected: всё зелёное.

- [ ] **Step 6: Commit** — `docs: Document Speedup no voice and VAD engines` (спека/сборка — отдельным `build:`-коммитом, если менялась).
