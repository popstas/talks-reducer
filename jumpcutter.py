from audiotsm import phasevocoder
from audiotsm.io.array import ArrayReader, ArrayWriter
from scipy.io import wavfile
from shutil import rmtree
from tqdm import tqdm as std_tqdm
from functools import partial
import numpy as np
import subprocess
import argparse
import re
import math
import os
import time

tqdm = partial(std_tqdm,
               bar_format=('{desc:<20} {percentage:3.0f}%'
                           '|{bar:10}|'
                           ' {n_fmt:>6}/{total_fmt:>6} [{elapsed:^5}<{remaining:^5}, {rate_fmt}{postfix}]'))
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

    command = 'ffprobe -i "{}" -hide_banner -loglevel error -select_streams a' \
              ' -show_entries stream=codec_type'.format(filename)
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    outs, errs = None, None
    try:
        outs, errs = p.communicate(timeout=0.1)
    except subprocess.TimeoutExpired:
        p.kill()
        outs, errs = p.communicate()
    finally:
        # If the file is no file that ffprobe recognizes we will get an error in the errors
        # else wise we will obtain an output in outs if there exists at least one audio stream
        return len(errs) == 0 and len(outs) > 0


def _input_to_output_filename(filename):
    dot_index = filename.rfind(".")
    return filename[:dot_index] + "_ALTERED" + filename[dot_index:]


def _create_path(s):
    # assert (not os.path.exists(s)), "The filepath "+s+" already exists. Don't want to overwrite it. Aborting."
    try:
        os.mkdir(s)
    except OSError:
        assert False, "Creation of the directory failed." \
                      " (The TEMP folder may already exist. Delete or rename it, and try again.)"


def _delete_path(s):  # Dangerous! Watch out!
    try:
        rmtree(s, ignore_errors=False)
        for i in range(5):
            if not os.path.exists(s):
                return
            time.sleep(0.01 * i)
    except OSError:
        print('Deletion of the directory {} failed'.format(s))
        print(OSError)


# TODO maybe transition to use the time=... instead of frame=... as frame is not accessible when exporting audio only
def _run_timed_ffmpeg_command(command, **kwargs):
    p = subprocess.Popen(command, stderr=subprocess.PIPE, universal_newlines=True, bufsize=1)

    with tqdm(**kwargs) as t:
        while p.poll() is None:
            line = p.stderr.readline()
            m = re.search(r'frame=.*?(\d+)', line)
            if m is not None:
                new_frame = int(m.group(1))
                if t.total < new_frame:
                    t.total = new_frame
                t.update(new_frame - t.n)
        t.update(t.total - t.n)


def _get_tree_expression(chunks) -> str:
    return '{}/TB/FR'.format(_get_tree_expression_rec(chunks))


def _get_tree_expression_rec(chunks) -> str:
    """
    Build a 'Binary Expression Tree' for the ffmpeg pts selection

    :param chunks: List of chunks that have the format [oldStart, oldEnd, newStart, newEnd]
    :return: Binary tree expression to calculate the speedup for the given chunks
    """
    if len(chunks) > 1:
        split_index = int(len(chunks) / 2)
        center = chunks[split_index]
        return 'if(lt(N,{}),{},{})'.format(center[0],
                                           _get_tree_expression_rec(chunks[:split_index]),
                                           _get_tree_expression_rec(chunks[split_index:]))
    else:
        chunk = chunks[0]
        local_speedup = (chunk[3] - chunk[2]) / (chunk[1] - chunk[0])
        offset = - chunk[0] * local_speedup + chunk[2]
        return 'N*{}{:+}'.format(local_speedup, offset)


def speed_up_video(
        input_file: str,
        output_file: str = None,
        frame_rate: float = 30,
        sample_rate: int = 44100,
        silent_threshold: float = 0.03,
        silent_speed: float = 5.0,
        sounded_speed: float = 1.0,
        frame_spreadage: int = 1,
        audio_fade_envelope_size: int = 400,
        temp_folder: str = 'TEMP') -> None:
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
    """
    # Set output file name based on input file name if none was given
    if output_file is None:
        output_file = _input_to_output_filename(input_file)

    # Create Temp Folder
    if os.path.exists(temp_folder):
        _delete_path(temp_folder)
    _create_path(temp_folder)

    # Find out framerate and duration of the input video
    command = 'ffprobe -i "{}" -hide_banner -loglevel error -select_streams v' \
              ' -show_entries format=duration:stream=avg_frame_rate'.format(input_file)
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)
    std_out, err = p.communicate()
    match_frame_rate = re.search(r'frame_rate=(\d*)/(\d*)', str(std_out))
    if match_frame_rate is not None:
        frame_rate = float(match_frame_rate.group(1)) / float(match_frame_rate.group(2))
        # print(f'Found Framerate {frame_rate}')

    match_duration = re.search(r'duration=([\d.]*)', str(std_out))
    original_duration = 0.0
    if match_duration is not None:
        original_duration = float(match_duration.group(1))
        # print(f'Found Duration {original_duration}')

    # Extract the audio
    command = 'ffmpeg -i "{}" -ab 160k -ac 2 -ar {} -vn {} -hide_banner' \
        .format(input_file,
                sample_rate,
                temp_folder + '/audio.wav')

    _run_timed_ffmpeg_command(command, total=int(original_duration * frame_rate), unit='frames',
                              desc='Extracting audio:')

    wav_sample_rate, audio_data = wavfile.read(temp_folder + "/audio.wav")
    audio_sample_count = audio_data.shape[0]
    max_audio_volume = _get_max_volume(audio_data)
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
    for i in tqdm(range(audio_frame_count), desc='Finding chunks:', unit='frames'):
        start = int(max(0, i - frame_spreadage))
        end = int(min(audio_frame_count, i + 1 + frame_spreadage))
        should_include_frame[i] = np.any(has_loud_audio[start:end])
        if i >= 1 and should_include_frame[i] != should_include_frame[i - 1]:  # Did we flip?
            chunks.append([chunks[-1][1], i, should_include_frame[i - 1]])

    chunks.append([chunks[-1][1], audio_frame_count, should_include_frame[audio_frame_count - 1]])
    chunks = chunks[1:]

    # Generate audio data with varying speed for each chunk
    new_speeds = [silent_speed, sounded_speed]
    output_pointer = 0
    audio_buffers = []
    for index, chunk in tqdm(enumerate(chunks), total=len(chunks), desc='Changing audio:', unit='chunks'):
        audio_chunk = audio_data[int(chunk[0] * samples_per_frame):int(chunk[1] * samples_per_frame)]

        reader = ArrayReader(np.transpose(audio_chunk))
        writer = ArrayWriter(reader.channels)
        tsm = phasevocoder(reader.channels, speed=new_speeds[int(chunk[2])])
        tsm.run(reader, writer)
        altered_audio_data = np.transpose(writer.data)

        # smooth out transition's audio by quickly fading in/out
        if altered_audio_data.shape[0] < audio_fade_envelope_size:
            altered_audio_data[:] = 0  # audio is less than 0.01 sec, let's just remove it.
        else:
            premask = np.arange(audio_fade_envelope_size) / audio_fade_envelope_size
            mask = np.repeat(premask[:, np.newaxis], 2, axis=1)  # make the fade-envelope mask stereo
            altered_audio_data[:audio_fade_envelope_size] *= mask
            altered_audio_data[-audio_fade_envelope_size:] *= 1 - mask

        audio_buffers.append(altered_audio_data / max_audio_volume)

        end_pointer = output_pointer + altered_audio_data.shape[0]
        start_output_frame = int(math.ceil(output_pointer / samples_per_frame))
        end_output_frame = int(math.ceil(end_pointer / samples_per_frame))
        chunks[index] = chunk[:2] + [start_output_frame, end_output_frame]

        output_pointer = end_pointer

    # print(chunks)

    output_audio_data = np.concatenate(audio_buffers)
    wavfile.write(temp_folder + "/audioNew.wav", sample_rate, output_audio_data)

    # Cut the video parts to length
    expression = _get_tree_expression(chunks)

    filter_graph_file = open(temp_folder + "/filterGraph.txt", 'w')
    filter_graph_file.write(f'fps=fps={frame_rate},setpts=')
    filter_graph_file.write(expression.replace(',', '\\,'))
    filter_graph_file.close()

    command = 'ffmpeg -i "{}" -i "{}" -filter_script:v "{}" -map 0 -map -0:a -map 1:a -c:a aac "{}"' \
              ' -loglevel warning -stats -y -hide_banner' \
        .format(input_file,
                temp_folder + '/audioNew.wav',
                temp_folder + '/filterGraph.txt',
                output_file)

    _run_timed_ffmpeg_command(command, total=chunks[-1][3], unit='frames', desc='Generating final:')

    _delete_path(temp_folder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Modifies a video file to play at different speeds when there is sound vs. silence.')

    parser.add_argument('-i', '--input_file', type=str, dest='input_file', nargs='+', required=True,
                        help='The video file(s) you want modified.'
                             ' Can be one or more directories and / or single files.')
    parser.add_argument('-o', '--output_file', type=str, dest='output_file',
                        help="The output file. Only usable if a single file is given."
                             " If not included, it'll just modify the input file name by adding _ALTERED.")
    parser.add_argument('-t', '--silent_threshold', type=float, dest='silent_threshold',
                        help='The volume amount that frames\' audio needs to surpass to be consider "sounded".'
                             ' It ranges from 0 (silence) to 1 (max volume). Defaults to 0.03')
    parser.add_argument('-S', '--sounded_speed', type=float, dest='sounded_speed',
                        help="The speed that sounded (spoken) frames should be played at. Defaults to 1.")
    parser.add_argument('-s', '--silent_speed', type=float, dest='silent_speed',
                        help="The speed that silent frames should be played at. Defaults to 5")
    parser.add_argument('-fm', '--frame_margin', type=float, dest='frame_spreadage',
                        help="Some silent frames adjacent to sounded frames are included to provide context."
                             " This is how many frames on either the side of speech should be included. Defaults to 1")
    parser.add_argument('-sr', '--sample_rate', type=float, dest='sample_rate',
                        help="Sample rate of the input and output videos. FFmpeg tries to extract this information."
                             " Thus only needed if FFmpeg fails to do so.")
    parser.add_argument('-fr', '--frame_rate', type=float, dest='frame_rate',
                        help="Frame rate of the input and output videos. FFmpeg tries to extract this information."
                             " Thus only needed if FFmpeg fails to do so.")

    files = []
    for input_file in parser.parse_args().input_file:
        if os.path.isfile(input_file) and _is_valid_input_file(input_file):
            files += [os.path.abspath(input_file)]
        elif os.path.isdir(input_file):
            files += [os.path.join(input_file, file) for file in os.listdir(input_file)
                      if _is_valid_input_file(os.path.join(input_file, file))]

    args = {k: v for k, v in vars(parser.parse_args()).items() if v is not None}
    del args['input_file']
    if len(files) > 1 and 'output_file' in args:
        del args['output_file']

    # It appears as though nested progress bars are deeply broken
    # with tqdm(files, unit='file') as progress_bar:
    for index, file in enumerate(files):
        # progress_bar.set_description("Processing file '{}'".format(os.path.basename(file)))
        print(f"Processing file {index + 1}/{len(files)} '{os.path.basename(file)}'")
        local_options = dict(args)
        local_options['input_file'] = file
        speed_up_video(**local_options)
