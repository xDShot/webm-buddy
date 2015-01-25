import subprocess
import argparse
import json
import itertools
import os


target_size = 10000

parser = argparse.ArgumentParser(description='Some bydlo-code to make creating WebM files easier.')
parser.add_argument('-i', help='input file')
parser.add_argument('-start', help='start time (optional), HH:MM:SS.xxx')  # -ss
parser.add_argument('-end', help='end time (optional), HH:MM:SS.xxx')  # -to
parser.add_argument('-size', help='target file size in KiB, default is ' + str(target_size))
parser.add_argument('-vf', help='video filters (ffmpeg syntax)')
parser.add_argument('-noaudio', action="store_true", default=False, help='do not add audio stream into output WebM')
parser.add_argument('-audio', help='alternative audio input')
parser.add_argument('-aq', help='audio quality, 0..9')

args = parser.parse_args()

input_file_path = args.i

if args.size is not None:
    target_size = int(args.size)

file_path, file_ext = os.path.splitext(input_file_path)
out_file = file_path + "_converted.webm"
out_file_audio_temp = file_path + "_a.ogg"
out_file_video_temp = file_path + "_v.webm"
out_file_1pass_temp = file_path + "_dummy.webm"


def count(g):
    return sum(1 for x in g)


def probe_file(filename):
    command = ['ffprobe',
               '-print_format', 'json',
               '-show_format',
               '-show_streams',
               '-v', 'quiet',
               filename]
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(filename)
    out, err = p.communicate()

    result = json.loads(out.decode())
    return result


def is_audio(stream_info):
    return stream_info['codec_type'] == 'audio'


file_info = probe_file(input_file_path)

streams = file_info['streams']
total_duration = file_info['format']['duration']

audio_streams_count = count(itertools.filterfalse(lambda x: not is_audio(x), streams))

assert audio_streams_count <= 1


def print_json(s):
    print(json.dumps(s,
                     sort_keys=True,
                     indent=4,
                     separators=(',', ': ')))


def optional_arg(name, value):
    if value is not None:
        return [name, value]
    return []


def not_empty_if(p, value):
    if p:
        return value
    return []


def parse_time_to_seconds(s):
    """
    @type s: string
    """
    p = s.split(sep=':')
    if len(p) == 1:
        return float(p[0])
    if len(p) == 3:
        return int(p[0]) * 60 * 60 + int(p[1]) * 60 + float(p[2])
    raise ValueError("Unrecognized timestamp format: " + s)


if (args.end is None) and (args.start is None):
    length_seconds = parse_time_to_seconds(total_duration)
elif args.end is None:
    length_seconds = parse_time_to_seconds(total_duration) - parse_time_to_seconds(args.start)
elif args.start is None:
    length_seconds = parse_time_to_seconds(args.end)
else:
    length_seconds = parse_time_to_seconds(args.end) - parse_time_to_seconds(args.start)

# audio
has_audio = args.noaudio is False and ((args.audio is not None) or (audio_streams_count > 0))

if has_audio:

    audio_source = args.audio or input_file_path

    audio_time_args = \
        optional_arg('-ss', args.start) + \
        optional_arg('-to', args.end) if args.audio is None else \
            ['-to', str(length_seconds)]

    if args.aq == 'copy':
        command = \
            [
                'ffmpeg',
                '-i', audio_source,
                '-vn', '-sn',
                '-acodec', 'copy'
            ] + \
            audio_time_args + \
            [out_file_audio_temp]
    else:
        command = \
            [
                'ffmpeg',
                '-i', audio_source,
                '-vn',
                '-acodec', 'libvorbis'
            ] + \
            optional_arg('-q:a', args.aq) + \
            audio_time_args + \
            [out_file_audio_temp]

    print(command)
    print('running audio pass:')
    p = subprocess.Popen(command)
    p.wait()

# 1st pass


command = \
    [
        'ffmpeg',
        '-i', input_file_path,
        '-an', '-sn'
    ] + \
    optional_arg('-ss', args.start) + \
    optional_arg('-to', args.end) + \
    optional_arg('-vf', args.vf) + \
    [
        '-vcodec', 'libvpx',
        '-strict', 'experimental',
        '-auto-alt-ref', '1',
        '-lag-in-frames', '20',
        '-pass', '1',
        out_file_1pass_temp
    ]

print(command)
print('running 1st pass:')
p = subprocess.Popen(command)
p.wait()

if has_audio:
    audio_size = os.path.getsize(out_file_audio_temp) / 1024  # we want KiB
else:
    audio_size = 0

target_bitrate = (target_size - audio_size) * 8 / length_seconds
target_bitrate_chopped = int(target_bitrate)
print("Target video bitrate: " + str(target_bitrate_chopped))

# 2nd pass

command = \
    [
        'ffmpeg',
        '-i', input_file_path
    ] + \
    optional_arg('-ss', args.start) + \
    optional_arg('-to', args.end) + \
    optional_arg('-vf', args.vf) + \
    [
        '-vcodec', 'libvpx',
        '-strict', 'experimental',
        '-an', '-sn',
        '-b:v', str(target_bitrate_chopped) + "k",
        '-auto-alt-ref', '1',
        '-lag-in-frames', '20',
        '-quality', 'good',
        '-cpu-used', '0',
        '-pass', '2',
        out_file_video_temp
    ]

print(command)
print('running 2nd pass:')
p = subprocess.Popen(command)
p.wait()

os.remove('ffmpeg2pass-0.log')

# join streams
if has_audio:
    command = \
        [
            'ffmpeg',
            '-i', out_file_video_temp,
            '-i', out_file_audio_temp,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-fs', str(target_size) + 'k',
            out_file
        ]

    print(command)
    print('merging:')
    p = subprocess.Popen(command)
    p.wait()
