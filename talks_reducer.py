import argparse
import math
import os
import re
import subprocess
import sys
import time
import warnings
from functools import partial
from pprint import pprint
from shutil import rmtree, which

import numpy as np
from audiotsm import phasevocoder
from audiotsm.io.array import ArrayReader, ArrayWriter
from scipy.io import wavfile
from tqdm import tqdm as std_tqdm

# Suppress warnings that might occur during GPU operations
warnings.filterwarnings("ignore")


def find_ffmpeg():
    """Find FFmpeg executable in common locations"""
    # Check common Windows locations
    common_paths = [
        "C:\\ProgramData\\chocolatey\\bin\\ffmpeg.exe",
        "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
        "ffmpeg",  # Try system PATH as last resort
    ]

    for path in common_paths:
        if os.path.isfile(path) or which(path):
            return os.path.abspath(path) if os.path.isfile(path) else path

    return None


# Try to find FFmpeg
FFMPEG_PATH = find_ffmpeg()
if not FFMPEG_PATH:
    print(
        "Error: FFmpeg not found. Please install FFmpeg and add it to your PATH or specify the full path.",
        file=sys.stderr,
    )
    sys.exit(1)

print(f"Using FFmpeg at: {FFMPEG_PATH}")

tqdm = partial(
    std_tqdm,
    bar_format=(
        "{desc:<20} {percentage:3.0f}%"
        "|{bar:10}|"
        " {n_fmt:>6}/{total_fmt:>6} [{elapsed:^5}<{remaining:^5}, {rate_fmt}{postfix}]"
    ),
)
# tqdm = std_tqdm


def _get_max_volume(s):
    return max(-np.min(s), np.max(s))


def _is_valid_input_file(filename) -> bool:
    """
    Check wether the input file is one that ffprobe recognizes, i.e. a video / audio / ... file.
    If it does, check whether there exists an audio stream, as we could not perform the dynamic shortening without one.

    :param filename: The full path to the input that is to be checked
    :return: True if it is a file with an audio stream attached.
    """

    command = (
        'ffprobe -i "{}" -hide_banner -loglevel error -select_streams a'
        " -show_entries stream=codec_type".format(filename)
    )
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    outs, errs = None, None
    try:
        outs, errs = p.communicate(timeout=1)
        # pprint(outs)
    except subprocess.TimeoutExpired:
        print("Timeout while checking the input file. Aborting. Command:")
        print(command)
        p.kill()
        outs, errs = p.communicate()
    finally:
        # If the file is no file that ffprobe recognizes we will get an error in the errors
        # else wise we will obtain an output in outs if there exists at least one audio stream
        return len(errs) == 0 and len(outs) > 0


def _input_to_output_filename(filename, small=False):
    dot_index = filename.rfind(".")
    suffix = "_speedup_small" if small else "_speedup"
    return filename[:dot_index] + suffix + filename[dot_index:]


def _create_path(s):
    # assert (not os.path.exists(s)), "The filepath "+s+" already exists. Don't want to overwrite it. Aborting."
    try:
        os.mkdir(s)
    except OSError:
        assert False, (
            "Creation of the directory failed."
            " (The TEMP folder may already exist. Delete or rename it, and try again.)"
        )


def _check_cuda_available():
    """Check if CUDA encoding is available and working"""
    try:
        # Simple test: try to get encoder info
        result = subprocess.run(
            [FFMPEG_PATH, "-encoders"], capture_output=True, text=True, timeout=5
        )
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ):
        return False

    if result.returncode != 0:
        return False

    encoder_list = result.stdout.lower()
    return (
        "h264_nvenc" in encoder_list
        or "hevc_nvenc" in encoder_list
        or "nvenc" in encoder_list
    )


def _delete_path(s):  # Dangerous! Watch out!
    try:
        rmtree(s, ignore_errors=False)
        for i in range(5):
            if not os.path.exists(s):
                return
            time.sleep(0.01 * i)
    except OSError:
        print("Deletion of the directory {} failed".format(s))
        print(OSError)


def _run_timed_ffmpeg_command(command, **kwargs):
    """Run an FFmpeg command with progress tracking.

    Args:
        command: The FFmpeg command string to execute
        **kwargs: Additional arguments for tqdm progress bar
    """
    import shlex
    import sys

    try:
        args = shlex.split(command)
    except Exception as e:
        print(f"Error parsing command: {e}", file=sys.stderr)
        raise

    # Print the command for debugging
    # print("\nExecuting command:")
    # print(' '.join(f'"{arg}"' if ' ' in arg else arg for arg in args))

    # Run the command
    try:
        p = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,
            errors="replace",  # Handle encoding issues
        )
    except Exception as e:
        print(f"Error starting FFmpeg: {e}", file=sys.stderr)
        raise

    # Process output in real-time
    with tqdm(**kwargs) as t:
        while True:
            # Read from stderr
            line = p.stderr.readline()
            if not line and p.poll() is not None:
                break

            if not line:
                continue

            # Print FFmpeg output for debugging
            sys.stderr.write(line)
            sys.stderr.flush()

            # Update progress
            m = re.search(r"frame=\s*(\d+)", line)
            if m:
                try:
                    new_frame = int(m.group(1))
                    if t.total < new_frame:
                        t.total = new_frame
                    t.update(new_frame - t.n)
                except (ValueError, IndexError):
                    pass

        # Wait for process to complete
        p.wait()

        # Check for errors
        if p.returncode != 0:
            error_output = p.stderr.read()
            print(f"\nFFmpeg error (return code {p.returncode}):", file=sys.stderr)
            print(error_output, file=sys.stderr)
            raise subprocess.CalledProcessError(p.returncode, args)

        # Update progress bar to 100% if not already there
        if t.n < t.total:
            t.update(t.total - t.n)


def _get_tree_expression(chunks) -> str:
    return "{}/TB/FR".format(_get_tree_expression_rec(chunks))


def _get_tree_expression_rec(chunks) -> str:
    """
    Build a 'Binary Expression Tree' for the ffmpeg pts selection

    :param chunks: List of chunks that have the format [oldStart, oldEnd, newStart, newEnd]
    :return: Binary tree expression to calculate the speedup for the given chunks
    """
    if len(chunks) > 1:
        split_index = int(len(chunks) / 2)
        center = chunks[split_index]
        return "if(lt(N,{}),{},{})".format(
            center[0],
            _get_tree_expression_rec(chunks[:split_index]),
            _get_tree_expression_rec(chunks[split_index:]),
        )
    else:
        chunk = chunks[0]
        local_speedup = (chunk[3] - chunk[2]) / (chunk[1] - chunk[0])
        offset = -chunk[0] * local_speedup + chunk[2]
        return "N*{}{:+}".format(local_speedup, offset)


def speed_up_video(
    input_file: str,
    output_file: str = None,
    frame_rate: float = 30,
    sample_rate: int = 44100,
    silent_threshold: float = 0.03,
    silent_speed: float = 4.0,
    sounded_speed: float = 1.0,
    frame_spreadage: int = 2,
    audio_fade_envelope_size: int = 400,
    temp_folder: str = "TEMP",
    small: bool = False,
) -> None:
    """
    Speeds up a video file with different speeds for the silent and loud sections in the video.

    :param input_file: The file name of the video to be sped up.
    :param output_file: The file name of the output file. If not given will be 'input_file'_ALTERED.ext.
    :param frame_rate: The frame rate of the given video. Only needed if not extractable through ffmpeg.
    :param sample_rate: The sample rate of the audio in the video.
    :param silent_threshold: The threshold when a chunk counts towards being a silent chunk.
                             Value ranges from 0 (nothing) - 1 (max volume).
    :param silent_speed: The speed of the silent chunks.
    :param sounded_speed: The speed of the loud chunks.
    :param frame_spreadage: How many silent frames adjacent to sounded frames should be included to provide context.
    :param audio_fade_envelope_size: Audio transition smoothing duration in samples.
    :param temp_folder: The file path of the temporary working folder.
    :param small: Whether to apply small file optimizations (720p resize, 128k audio bitrate, best compression).
    """
    # Set output file name based on input file name if none was given
    if output_file is None:
        output_file = _input_to_output_filename(input_file, small)

    cuda_available = _check_cuda_available()

    # Create Temp Folder
    if os.path.exists(temp_folder):
        _delete_path(temp_folder)
    _create_path(temp_folder)

    # Find out framerate and duration of the input video
    command = (
        'ffprobe -i "{}" -hide_banner -loglevel error -select_streams v'
        " -show_entries format=duration:stream=avg_frame_rate".format(input_file)
    )
    p = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True,
    )
    std_out, err = p.communicate()
    match_frame_rate = re.search(r"frame_rate=(\d*)/(\d*)", str(std_out))
    if match_frame_rate is not None:
        frame_rate = float(match_frame_rate.group(1)) / float(match_frame_rate.group(2))
        # print(f'Found Framerate {frame_rate}')

    match_duration = re.search(r"duration=([\d.]*)", str(std_out))
    original_duration = 0.0
    if match_duration is not None:
        original_duration = float(match_duration.group(1))
        # print(f'Found Duration {original_duration}')

    # Extract the audio with hardware acceleration if enabled
    hwaccel = (
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if cuda_available else []
    )
    audio_bitrate = "128k" if small else "160k"
    command = " ".join(
        [
            f'"{FFMPEG_PATH}"',
            " ".join(hwaccel),
            f'-i "{input_file}"',
            f"-ab {audio_bitrate} -ac 2",
            f"-ar {sample_rate}",
            "-vn",
            f'"{os.path.join(temp_folder, "audio.wav")}"',
            "-hide_banner -loglevel warning -stats",
        ]
    )

    _run_timed_ffmpeg_command(
        command,
        total=int(original_duration * frame_rate),
        unit="frames",
        desc="Extracting audio:",
    )

    wav_sample_rate, audio_data = wavfile.read(temp_folder + "/audio.wav")
    audio_sample_count = audio_data.shape[0]
    max_audio_volume = _get_max_volume(audio_data)
    print("\nProcessing Information:")
    print(f"- Max Audio Volume: {max_audio_volume}")
    print(f"- Processing on: {'GPU (CUDA)' if cuda_available else 'CPU'}")
    if small:
        print("- Small mode: 720p video, 128k audio, optimized compression")
    samples_per_frame = wav_sample_rate / frame_rate
    audio_frame_count = int(math.ceil(audio_sample_count / samples_per_frame))

    # Find frames with loud audio
    has_loud_audio = np.zeros(audio_frame_count, dtype=bool)

    for i in range(audio_frame_count):
        start = int(i * samples_per_frame)
        end = min(int((i + 1) * samples_per_frame), audio_sample_count)
        audio_chunk = audio_data[start:end]
        chunk_max_volume = float(_get_max_volume(audio_chunk)) / max_audio_volume
        if chunk_max_volume >= silent_threshold:
            has_loud_audio[i] = True

    # Chunk the frames together that are quiet or loud
    chunks = [[0, 0, 0]]
    should_include_frame = np.zeros(audio_frame_count, dtype=bool)
    for i in tqdm(range(audio_frame_count), desc="Finding chunks:", unit="frames"):
        start = int(max(0, i - frame_spreadage))
        end = int(min(audio_frame_count, i + 1 + frame_spreadage))
        should_include_frame[i] = np.any(has_loud_audio[start:end])
        if (
            i >= 1 and should_include_frame[i] != should_include_frame[i - 1]
        ):  # Did we flip?
            chunks.append([chunks[-1][1], i, should_include_frame[i - 1]])

    chunks.append(
        [chunks[-1][1], audio_frame_count, should_include_frame[audio_frame_count - 1]]
    )
    chunks = chunks[1:]

    print(f"Generated {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks[:5]):  # Show first 5 chunks
        print(f"  Chunk {i}: {chunk}")
    if len(chunks) > 5:
        print(f"  ... and {len(chunks) - 5} more chunks")

    # Generate audio data with varying speed for each chunk
    new_speeds = [silent_speed, sounded_speed]
    output_pointer = 0
    audio_buffers = []

    # Process audio in batches to better utilize GPU
    batch_size = 10  # Adjust based on your GPU memory
    for batch_start in tqdm(
        range(0, len(chunks), batch_size), desc="Processing audio chunks"
    ):
        batch_chunks = chunks[batch_start : batch_start + batch_size]
        batch_audio = []

        for chunk in batch_chunks:
            audio_chunk = audio_data[
                int(chunk[0] * samples_per_frame) : int(chunk[1] * samples_per_frame)
            ]

            reader = ArrayReader(np.transpose(audio_chunk))
            writer = ArrayWriter(reader.channels)
            tsm = phasevocoder(reader.channels, speed=new_speeds[int(chunk[2])])
            tsm.run(reader, writer)
            altered_audio_data = np.transpose(writer.data)

            # Process fade in/out
            if altered_audio_data.shape[0] < audio_fade_envelope_size:
                altered_audio_data[:] = 0
            else:
                premask = np.arange(audio_fade_envelope_size) / audio_fade_envelope_size
                mask = np.repeat(premask[:, np.newaxis], 2, axis=1)
                altered_audio_data[:audio_fade_envelope_size] *= mask
                altered_audio_data[-audio_fade_envelope_size:] *= 1 - mask

            batch_audio.append(altered_audio_data / max_audio_volume)

        # Process batch updates
        for i, chunk in enumerate(batch_chunks):
            altered_audio_data = batch_audio[i]
            audio_buffers.append(altered_audio_data)

            end_pointer = output_pointer + altered_audio_data.shape[0]
            start_output_frame = int(math.ceil(output_pointer / samples_per_frame))
            end_output_frame = int(math.ceil(end_pointer / samples_per_frame))
            chunks[batch_start + i] = chunk[:2] + [start_output_frame, end_output_frame]
            output_pointer = end_pointer

    # print(chunks)

    output_audio_data = np.concatenate(audio_buffers)
    wavfile.write(temp_folder + "/audioNew.wav", sample_rate, output_audio_data)

    # Cut the video parts to length
    expression = _get_tree_expression(chunks)

    filter_graph_file = open(temp_folder + "/filterGraph.txt", "w")
    filter_parts = []

    if small:
        filter_parts.append("scale=-2:720")

    filter_parts.append(f"fps=fps={frame_rate}")
    filter_parts.append(f'setpts={expression.replace(",", "\\,")}')

    filter_graph_file.write(",".join(filter_parts))
    filter_graph_file.close()

    # Build the FFmpeg command with proper argument formatting
    global_command_parts = [f'"{FFMPEG_PATH}"', "-y"]

    hwaccel_args = (
        ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        if (cuda_available and not small)
        else []
    )

    input_command_parts = []
    output_command_parts = [
        "-map 0 -map -0:a -map 1:a",
        f'-filter_script:v "{os.path.join(temp_folder, "filterGraph.txt")}"',
    ]

    if hwaccel_args:
        global_command_parts.extend(hwaccel_args)

    input_command_parts.extend(
        [f'-i "{input_file}"', f'-i "{os.path.join(temp_folder, "audioNew.wav")}"']
    )

    video_encoder_args = []
    fallback_encoder_args = []
    use_cuda_encoder = False

    if small:
        if cuda_available:
            use_cuda_encoder = True
            video_encoder_args = [
                "-c:v h264_nvenc",
                "-preset p1",
                "-cq 28",
                "-tune",
                "ll",
            ]
            fallback_encoder_args = [
                "-c:v libx264",
                "-preset veryfast",
                "-crf 24",
                "-tune",
                "zerolatency",
            ]
        else:
            print("CUDA encoding not available, using software encoding")
            video_encoder_args = [
                "-c:v libx264",
                "-preset veryfast",
                "-crf 24",
                "-tune",
                "zerolatency",
            ]
    else:
        global_command_parts.append("-filter_complex_threads 1")
        if cuda_available:
            video_encoder_args = ["-c:v h264_nvenc"]
        else:
            print("CUDA encoding not available for normal mode, using copy mode")
            video_encoder_args = ["-c:v copy"]

    audio_command_parts = [
        "-c:a aac",
        f'"{output_file}"',
        "-loglevel info -stats -hide_banner",
    ]

    final_command_parts = (
        global_command_parts
        + input_command_parts
        + output_command_parts
        + video_encoder_args
        + audio_command_parts
    )
    command_str = " ".join(final_command_parts)

    fallback_command_str = None
    if fallback_encoder_args:
        fallback_command_parts = (
            global_command_parts
            + input_command_parts
            + output_command_parts
            + fallback_encoder_args
            + audio_command_parts
        )
        fallback_command_str = " ".join(fallback_command_parts)

    # Print the command for debugging
    print("\nExecuting FFmpeg command:")
    print(command_str)
    print(f"Command parts: {final_command_parts}")

    # Debug: Show filter file contents
    try:
        with open(os.path.join(temp_folder, "filterGraph.txt"), "r") as f:
            filter_content = f.read()
        print(f"Filter file contents: {filter_content}")
    except Exception as e:
        print(f"Could not read filter file: {e}")

    # Verify output directory exists
    output_dir = os.path.dirname(os.path.abspath(output_file))
    if output_dir and not os.path.exists(output_dir):
        print(f"Creating output directory: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)

    # Debug: Check if all required files exist before running final command
    print(f"Input file exists: {os.path.exists(input_file)}")
    print(
        f"Audio file exists: {os.path.exists(os.path.join(temp_folder, 'audioNew.wav'))}"
    )
    print(
        f"Filter file exists: {os.path.exists(os.path.join(temp_folder, 'filterGraph.txt'))}"
    )

    if not os.path.exists(os.path.join(temp_folder, "audioNew.wav")):
        print("ERROR: Audio file not found!")
        _delete_path(temp_folder)
        return

    if not os.path.exists(os.path.join(temp_folder, "filterGraph.txt")):
        print("ERROR: Filter file not found!")
        _delete_path(temp_folder)
        return

    try:
        _run_timed_ffmpeg_command(
            command_str, total=chunks[-1][3], unit="frames", desc="Generating final:"
        )
    except subprocess.CalledProcessError as e:
        if fallback_command_str and use_cuda_encoder:
            print("CUDA encoding failed, retrying with CPU encoder...")
            try:
                _run_timed_ffmpeg_command(
                    fallback_command_str,
                    total=chunks[-1][3],
                    unit="frames",
                    desc="Generating final (fallback):",
                )
            except subprocess.CalledProcessError:
                print(f"\nError running FFmpeg command: {e}")
                print(
                    "Please check if all input files exist and FFmpeg has proper permissions."
                )
                raise
        else:
            print(f"\nError running FFmpeg command: {e}")
            print(
                "Please check if all input files exist and FFmpeg has proper permissions."
            )
            raise

    _delete_path(temp_folder)


if __name__ == "__main__":
    start_time = time.time()
    parser = argparse.ArgumentParser(
        description="Modifies a video file to play at different speeds when there is sound vs. silence."
    )

    parser.add_argument(
        "-i",
        "--input_file",
        type=str,
        dest="input_file",
        nargs="+",
        required=True,
        help="The video file(s) you want modified."
        " Can be one or more directories and / or single files.",
    )
    parser.add_argument(
        "-o",
        "--output_file",
        type=str,
        dest="output_file",
        help="The output file. Only usable if a single file is given."
        " If not included, it'll just modify the input file name by adding _ALTERED.",
    )
    parser.add_argument(
        "--temp_folder",
        type=str,
        default="TEMP",
        help="The file path of the temporary working folder.",
    )
    parser.add_argument(
        "-t",
        "--silent_threshold",
        type=float,
        dest="silent_threshold",
        help='The volume amount that frames\' audio needs to surpass to be consider "sounded".'
        " It ranges from 0 (silence) to 1 (max volume). Defaults to 0.03",
    )
    parser.add_argument(
        "-S",
        "--sounded_speed",
        type=float,
        dest="sounded_speed",
        help="The speed that sounded (spoken) frames should be played at. Defaults to 1.",
    )
    parser.add_argument(
        "-s",
        "--silent_speed",
        type=float,
        dest="silent_speed",
        help="The speed that silent frames should be played at. Defaults to 4",
    )
    parser.add_argument(
        "-fm",
        "--frame_margin",
        type=float,
        dest="frame_spreadage",
        help="Some silent frames adjacent to sounded frames are included to provide context."
        " This is how many frames on either the side of speech should be included. Defaults to 2",
    )
    parser.add_argument(
        "-sr",
        "--sample_rate",
        type=float,
        dest="sample_rate",
        help="Sample rate of the input and output videos. FFmpeg tries to extract this information."
        " Thus only needed if FFmpeg fails to do so.",
    )
    parser.add_argument(
        "--small",
        action="store_true",
        help="Apply small file optimizations: resize video to 720p, audio to 128k bitrate, best compression (uses CUDA if available).",
    )

    files = []
    for input_file in parser.parse_args().input_file:
        if os.path.isfile(input_file) and _is_valid_input_file(input_file):
            files += [os.path.abspath(input_file)]
        elif os.path.isdir(input_file):
            files += [
                os.path.join(input_file, file)
                for file in os.listdir(input_file)
                if _is_valid_input_file(os.path.join(input_file, file))
            ]

    # pprint(files)
    args = {k: v for k, v in vars(parser.parse_args()).items() if v is not None}
    del args["input_file"]
    if len(files) > 1 and "output_file" in args:
        del args["output_file"]

    # It appears as though nested progress bars are deeply broken
    # with tqdm(files, unit='file') as progress_bar:
    for index, file in enumerate(files):
        # progress_bar.set_description("Processing file '{}'".format(os.path.basename(file)))
        print(f"Processing file {index + 1}/{len(files)} '{os.path.basename(file)}'")
        local_options = dict(args)
        local_options["input_file"] = file
        local_options["small"] = local_options.get("small", False)
        speed_up_video(**local_options)

    end_time = time.time()
    total_time = end_time - start_time
    hours, remainder = divmod(total_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"\nTime: {int(hours)}h {int(minutes)}m {seconds:.2f}s")
