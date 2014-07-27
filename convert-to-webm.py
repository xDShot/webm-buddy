import subprocess
import argparse
import json
import itertools
import os


target_size = 6144

parser = argparse.ArgumentParser()
parser.add_argument('-i', help='input file')
parser.add_argument('-start', help='start time (optional), HH:MM:SS.xxx')  # -ss, optional
parser.add_argument('-end', help='end time (optional), HH:MM:SS.xxx')  # -to, optional
parser.add_argument('-size', help='target file size in KiB, default is ' + str(target_size))  # optional



args = parser.parse_args()

input_file_path = args.i

if args.size is not None:
    target_size = args.size

file_path, file_ext = os.path.splitext(input_file_path)
out_file = file_path + "_converted.webm"
out_file_temp = file_path + "_a.webm"


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

# 1st pass
# ffmpeg -ss 10:00 -i video.mkv -t 2:00 -vf scale=500:-1 -auto-alt-ref 1 -lag-in-frames 20 -pass 1 out-a.webm

command = \
    [
        'ffmpeg',
        '-i', input_file_path
    ] + \
    optional_arg('-ss', args.start) + \
    optional_arg('-to', args.end) + \
    [
        # '-vf', 'scale=500:-1',
        '-auto-alt-ref', '1',
        '-lag-in-frames', '20',
        '-pass', '1',
        out_file_temp
    ]

print(command)
print('running 1st pass:')
p = subprocess.Popen(command)
p.wait()

# get video bitrate
# bitrate = (filesize - audio_size) * 8bit / time
# (6144 - 1532)KiB * 8bit / 120sec = 307kbit/s

def parse_time_to_seconds(s):
    """
    @type s: string
    """
    p = s.split(sep=':')
    p[-1] = p[-1].split(sep='.', maxsplit=1)[0]
    return int(p[0]) * 60 * 60 + int(p[1]) * 60 + int(p[2])


audio_size = os.path.getsize(out_file_temp) / 1024  # we want KiB
length_seconds = parse_time_to_seconds(args.end) - parse_time_to_seconds(args.start) + 1

target_bitrate = (target_size - audio_size) * 8 / length_seconds
target_bitrate_chopped = int(target_bitrate)
print("Target video bitrate: " + str(target_bitrate_chopped))

# 2nd pass

# ffmpeg -i video.mkv -i out-a.webm -t 2:00  -quality best -pass 2 out.webm

command = \
    [
        'ffmpeg',
        '-i', input_file_path,
        '-i', out_file_temp
    ] + \
    optional_arg('-ss', args.start) + \
    optional_arg('-to', args.end) + \
    [
        '-map', '0:v',
        '-map', '1:a',
        '-c:a', 'copy',
        # '-vf', 'scale=500:-1',
        '-b:v', str(target_bitrate_chopped) + "k",
        '-auto-alt-ref', '1',
        '-lag-in-frames', '20',
        '-quality', 'best',
        '-pass', '2',
        out_file
    ]

print(command)
print('running 2nd pass:')
p = subprocess.Popen(command)
p.wait()

os.remove(out_file_temp)
os.remove('ffmpeg2pass-0.log')
