import subprocess
import shutil
import os
import re
import json
from collections.abc import Mapping

import cv2
import numpy as np
import torch

from PIL import Image

from folder_paths import base_path

"""
Attribution: ComfyUI-VideoHelperSuite

Portions of this code are adapted from GitHub repository `https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite`,
which is licensed under the GNU General Public License version 3 (GPL-3.0):

"""

_AUDIO_STREAM_PROBE_CACHE = {}

def __lnl_ffmpeg_suitability(path):
    try:
        version = subprocess.run([path, "-version"], check=True,
                                 capture_output=True).stdout.decode("utf-8")
    except:
        return 0
    score = 0
    #rough layout of the importance of various features
    simple_criterion = [("libvpx", 20),("264",10), ("265",3),
                        ("svtav1",5),("libopus", 1)]
    for criterion in simple_criterion:
        if version.find(criterion[0]) >= 0:
            score += criterion[1]
    #obtain rough compile year from copyright information
    copyright_index = version.find('2000-2')
    if copyright_index >= 0:
        copyright_year = version[copyright_index+6:copyright_index+9]
        if copyright_year.isnumeric():
            score += int(copyright_year)
    return score

def lnl_get_audio(file, start_time=0, duration=0):
    if ffmpeg_path is None:
        return b""
    args = [ffmpeg_path, "-v", "error", "-nostdin", "-i", file, "-map", "0:a:0", "-vn"]
    if start_time > 0:
        args += ["-ss", str(start_time)]
    if duration > 0:
        args += ["-t", str(duration)]
    try:
        return subprocess.run(args + ["-f", "wav", "-"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore") if e.stderr else ""
        stdout = e.stdout.decode("utf-8", errors="ignore") if e.stdout else ""
        combined = (stderr + "\n" + stdout).strip()
        if _lnl_is_no_audio_error(combined):
            return b""
        raise
    except OSError:
        return b""

def lnl_lazy_eval(func):
    class Cache:
        def __init__(self, func):
            self.res = None
            self.func = func
        def get(self):
            if self.res is None:
                self.res = self.func()
            return self.res
    cache = Cache(func)
    return lambda : cache.get()

def _lnl_probe_audio_stream_params(file):
    cached = _AUDIO_STREAM_PROBE_CACHE.get(file)
    if cached is not None:
        return cached

    ffprobe_cmd = shutil.which("ffprobe")
    if ffprobe_cmd is None and ffmpeg_path is not None:
        ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        ffprobe_candidate = os.path.join(os.path.dirname(ffmpeg_path), ffprobe_name)
        if os.path.exists(ffprobe_candidate):
            ffprobe_cmd = ffprobe_candidate

    if ffprobe_cmd is None:
        _AUDIO_STREAM_PROBE_CACHE[file] = (None, None)
        return (None, None)

    cmd = [
        ffprobe_cmd,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels",
        "-of", "json",
        file,
    ]
    try:
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        data = json.loads(process.stdout) if process.stdout else {}
        stream = (data.get("streams") or [None])[0]
        if not isinstance(stream, dict):
            _AUDIO_STREAM_PROBE_CACHE[file] = (None, None)
            return (None, None)
        sample_rate_raw = stream.get("sample_rate")
        channels_raw = stream.get("channels")
        sample_rate = int(sample_rate_raw) if str(sample_rate_raw).isdigit() else None
        channels = int(channels_raw) if isinstance(channels_raw, int) else None
        _AUDIO_STREAM_PROBE_CACHE[file] = (sample_rate, channels)
        return (sample_rate, channels)
    except Exception:
        _AUDIO_STREAM_PROBE_CACHE[file] = (None, None)
        return (None, None)

def _lnl_get_audio(file, start_time=0, duration=0):
    if ffmpeg_path is None:
        return lnl_empty_audio_dict()
    args = [ffmpeg_path, "-v", "error", "-nostdin", "-i", file, "-map", "0:a:0", "-vn"]
    if start_time > 0:
        args += ["-ss", str(start_time)]
    if duration > 0:
        args += ["-t", str(duration)]
    try:
        #TODO: scan for sample rate and maintain
        res =  subprocess.run(args + ["-f", "f32le", "-"],
                              capture_output=True, check=True)
        stderr_text = res.stderr.decode("utf-8", errors="ignore")
        raw_audio = res.stdout or b""
        if len(raw_audio) == 0:
            return lnl_empty_audio_dict()
        # f32le must be 4-byte aligned; truncate trailing partial bytes defensively.
        remainder = len(raw_audio) % 4
        if remainder:
            raw_audio = raw_audio[: len(raw_audio) - remainder]
        if len(raw_audio) == 0:
            return lnl_empty_audio_dict()
        audio = torch.frombuffer(bytearray(raw_audio), dtype=torch.float32)
        if audio.numel() == 0:
            return lnl_empty_audio_dict()
        match = re.search(', (\\d+) Hz, (\\w+), ', stderr_text)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore") if e.stderr else ""
        stdout = e.stdout.decode("utf-8", errors="ignore") if e.stdout else ""
        combined = (stderr + "\n" + stdout).strip()
        if _lnl_is_no_audio_error(combined):
            return lnl_empty_audio_dict()
        raise Exception(f"VHS failed to extract audio from {file}:\n" \
                + (combined or stderr))
    except OSError:
        return lnl_empty_audio_dict()
    if match:
        ar = int(match.group(1))
        # NOTE: Just throwing an error for other channel types right now
        # Will deal with issues if they come
        ac = {"mono": 1, "stereo": 2}.get(match.group(2), 2)
    else:
        probed_ar, probed_ac = _lnl_probe_audio_stream_params(file)
        ar = probed_ar if probed_ar and probed_ar > 0 else 44100
        ac = probed_ac if probed_ac and probed_ac > 0 else 2
    if ac <= 0:
        ac = 2
    usable_values = (audio.numel() // ac) * ac
    if usable_values <= 0:
        return lnl_empty_audio_dict(ar)
    if usable_values != audio.numel():
        audio = audio[:usable_values]
    audio = audio.reshape((-1,ac)).transpose(0,1).unsqueeze(0)
    return {'waveform': audio, 'sample_rate': ar}

def lnl_empty_audio_dict(sample_rate=44100):
    return {'waveform': torch.zeros((1, 1, 0), dtype=torch.float32), 'sample_rate': sample_rate}

def _lnl_is_no_audio_error(stderr):
    if not stderr:
        return False
    text = stderr.lower()
    return ("audio" not in text and "video" in text) \
        or "matches no streams" in text \
        or "no audio" in text \
        or "does not contain any stream" in text \
        or "output file does not contain any stream" in text \
        or ("error opening output file" in text and "pipe:" in text)

class LNLLazyAudioMap(Mapping):
    def __init__(self, file, start_time, duration):
        self.file = file
        self.start_time=start_time
        self.duration=duration
        self._dict=None
    def __getitem__(self, key):
        if self._dict is None:
            try:
                self._dict = _lnl_get_audio(self.file, self.start_time, self.duration)
            except Exception:
                self._dict = lnl_empty_audio_dict()
        return self._dict[key]
    def __iter__(self):
        if self._dict is None:
            try:
                self._dict = _lnl_get_audio(self.file, self.start_time, self.duration)
            except Exception:
                self._dict = lnl_empty_audio_dict()
        return iter(self._dict)
    def __len__(self):
        if self._dict is None:
            try:
                self._dict = _lnl_get_audio(self.file, self.start_time, self.duration)
            except Exception:
                self._dict = lnl_empty_audio_dict()
        return len(self._dict)

def lnl_lazy_get_audio(file, start_time=0, duration=0):
    return LNLLazyAudioMap(file, start_time, duration)

def lnl_cv_frame_generator(video, number_of_frames_to_process, skip_first_frames, select_every_nth,
                           force_size="Disabled", custom_width=512, custom_height=512):
    """
    Decode video frames using ffmpeg rawvideo pipe (with CUDA HW accel).
    Supports GPU-side scaling via force_size. Falls back to OpenCV.
    """
    # --- ffmpeg pipe (fast) ---
    if ffmpeg_path is not None:
        ffprobe_cmd = shutil.which("ffprobe")
        if ffprobe_cmd is None:
            ffn = "ffprobe.exe" if os.name == "nt" else "ffprobe"
            ffprobe_cmd = os.path.join(os.path.dirname(ffmpeg_path), ffn)
        if ffprobe_cmd and os.path.isfile(ffprobe_cmd):
            try:
                yield from _lnl_ffmpeg_pipe(ffmpeg_path, ffprobe_cmd, video,
                                            number_of_frames_to_process, skip_first_frames, select_every_nth,
                                            force_size, custom_width, custom_height)
                return
            except Exception:
                pass  # Fallback below

    # --- OpenCV fallback (no GPU-scale) ---
    try:
        video_cap = cv2.VideoCapture(video)
        if not video_cap.isOpened():
            raise ValueError(f"{video} could not be loaded with cv.")
        total_frame_count = 0
        total_frames_evaluated = -1
        frames_added = 0
        base_frame_time = 1/video_cap.get(cv2.CAP_PROP_FPS)
        width = video_cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        prev_frame = None

        target_frame_time = base_frame_time
        yield (width, height, target_frame_time)

        time_offset=target_frame_time - base_frame_time
        while video_cap.isOpened():
            if time_offset < target_frame_time:
                is_returned = video_cap.grab()
                if not is_returned:
                    break
                time_offset += base_frame_time
            if time_offset < target_frame_time:
                continue
            time_offset -= target_frame_time
            total_frame_count += 1
            if total_frame_count < skip_first_frames:
                continue
            else:
                total_frames_evaluated += 1

            if total_frames_evaluated%select_every_nth != 0:
                frames_added += 1
                if total_frame_count >= number_of_frames_to_process + skip_first_frames:
                    break
                continue

            unused, frame = video_cap.retrieve()
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = np.array(frame, dtype=np.float32) / 255.0
            if prev_frame is not None:
                inp  = yield prev_frame
                if inp is not None:
                    return
            prev_frame = frame
            frames_added += 1
            if number_of_frames_to_process > 0 and frames_added >= number_of_frames_to_process:
                break
        if prev_frame is not None:
            yield prev_frame
    finally:
        video_cap.release()


def _lnl_ffmpeg_pipe(ffmpeg_cmd, ffprobe_cmd, video,
                     number_of_frames_to_process, skip_first_frames, select_every_nth,
                     force_size="Disabled", custom_width=512, custom_height=512):
    """Decode video via ffmpeg rawvideo pipe (CUDA hwaccel, GPU-scale, batch read)."""
    import subprocess as sp
    import time as _time
    _t0 = _time.time()

    # Probe video dimensions / frame rate
    probe = sp.run(
        [ffprobe_cmd, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate",
         "-of", "json", video],
        capture_output=True, text=True, timeout=30,
    )
    info = json.loads(probe.stdout)
    stream = info.get("streams", (None,))[0]
    if stream is None:
        raise RuntimeError(f"No video stream in {video}")

    src_w = int(stream["width"])
    src_h = int(stream["height"])
    rate_str = stream.get("avg_frame_rate") or stream.get("r_frame_rate", "30/1")
    if "/" in rate_str:
        num, den = map(float, rate_str.split("/"))
        fps = num / den if den else 30.0
    else:
        fps = float(rate_str) if float(rate_str) > 0 else 30.0
    target_frame_time = 1.0 / fps

    print(f"[LNL-DEBUG] 视频: {src_w}x{src_h} {fps:.2f}fps, skip_first={skip_first_frames}, nth={select_every_nth}, need={number_of_frames_to_process}")

    # Calculate target size (GPU-side scale to reduce pipe data)
    target_w, target_h = src_w, src_h
    if force_size != "Disabled":
        target_w, target_h = lnl_target_size(src_w, src_h, force_size, custom_width, custom_height)
        print(f"[LNL-DEBUG] 缩放: {src_w}x{src_h} -> {target_w}x{target_h} (force_size={force_size}, cw={custom_width}, ch={custom_height})")
    else:
        print(f"[LNL-DEBUG] 缩放: Disabled, 保持 {src_w}x{src_h}")

    # Yield metadata (scaled dims so caller can skip Python resize)
    yield (target_w, target_h, target_frame_time)

    frame_size = target_w * target_h * 3

    # Quick CUDA availability check
    hwaccel_prefix = []
    try:
        hwaccel_test = sp.run(
            [ffmpeg_cmd, "-hwaccels"],
            capture_output=True, text=True, timeout=5,
        )
        cuda_ok = hwaccel_test.returncode == 0 and "cuda" in hwaccel_test.stdout
        if cuda_ok:
            hwaccel_prefix = ["-hwaccel", "cuda"]
        print(f"[LNL-DEBUG] CUDA 检测: {'可用 ✓' if cuda_ok else '不可用 ✗'}")
    except Exception as e:
        print(f"[LNL-DEBUG] CUDA 检测异常: {e}")

    # Fast seek + optional GPU-scale
    seek_ts = skip_first_frames * target_frame_time if skip_first_frames > 0 else 0
    print(f"[LNL-DEBUG] seek_ts={seek_ts:.4f}s ({skip_first_frames}帧 x {target_frame_time:.4f}s)")

    cmd = [ffmpeg_cmd] + hwaccel_prefix
    if seek_ts > 0:
        cmd += ["-ss", str(seek_ts)]
    cmd += ["-i", video]
    if target_w != src_w or target_h != src_h:
        cmd += ["-vf", f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black", "-sws_flags", "lanczos"]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-vsync", "0", "-v", "quiet", "-"]

    print(f"[LNL-DEBUG] ffmpeg 命令: {' '.join(cmd[:8])} ... -f rawvideo ...")
    _t_popen = _time.time()
    print(f"[LNL-DEBUG] probe+准备耗时: {_t_popen - _t0:.3f}s")

    proc = sp.Popen(cmd, stdout=sp.PIPE, stderr=sp.PIPE)

    BATCH_FRAMES = 32
    frame_idx = 0
    frames_added = 0
    total_bytes = 0
    _t_first_frame = None
    _t_batch_start = _time.time()

    try:
        while True:
            chunk = proc.stdout.read(frame_size * BATCH_FRAMES)
            if not chunk:
                print(f"[LNL-DEBUG] pipe 关闭, 共读取 {total_bytes/1024/1024:.1f}MB, frame_idx={frame_idx}, 产出={frames_added}")
                break

            chunk_len = len(chunk)
            total_bytes += chunk_len
            n_frames_in_chunk = chunk_len // frame_size
            if _t_first_frame is None:
                _t_first_frame = _time.time()
                print(f"[LNL-DEBUG] 首帧到达: {_t_first_frame - _t0:.3f}s (批量 {n_frames_in_chunk} 帧)")

            for offset in range(0, chunk_len, frame_size):
                raw = chunk[offset:offset + frame_size]
                if len(raw) < frame_size:
                    break

                if frame_idx % select_every_nth == 0:
                    frame = np.frombuffer(raw, np.uint8).reshape((target_h, target_w, 3))
                    frame = frame.astype(np.float32) / 255.0
                    inp = yield frame
                    if inp is not None:
                        return
                    frames_added += 1
                    if number_of_frames_to_process > 0 and frames_added >= number_of_frames_to_process:
                        break
                frame_idx += 1

            if number_of_frames_to_process > 0 and frames_added >= number_of_frames_to_process:
                break
    finally:
        _t_end = _time.time()
        elapsed = _t_end - _t0
        mb = total_bytes / 1024 / 1024
        mbps = mb / elapsed if elapsed > 0 else 0
        fps_effective = frames_added / (elapsed - (_t_first_frame - _t0)) if _t_first_frame and elapsed > (_t_first_frame - _t0) else 0
        print(f"[LNL-DEBUG] 总计: {elapsed:.3f}s, pipe={mb:.1f}MB ({mbps:.0f}MB/s), "
              f"frame={target_w}x{target_h}, 产出={frames_added}帧 ({fps_effective:.1f}f/s)")
        proc.stdout.close()
        try:
            proc.wait(timeout=10)
        except sp.TimeoutExpired:
            proc.kill()
            proc.wait()

def lnl_bislerp(samples, width, height):
    def slerp(b1, b2, r):
        '''slerps batches b1, b2 according to ratio r, batches should be flat e.g. NxC'''
        
        c = b1.shape[-1]

        #norms
        b1_norms = torch.norm(b1, dim=-1, keepdim=True)
        b2_norms = torch.norm(b2, dim=-1, keepdim=True)

        #normalize
        b1_normalized = b1 / b1_norms
        b2_normalized = b2 / b2_norms

        #zero when norms are zero
        b1_normalized[b1_norms.expand(-1,c) == 0.0] = 0.0
        b2_normalized[b2_norms.expand(-1,c) == 0.0] = 0.0

        #slerp
        dot = (b1_normalized*b2_normalized).sum(1)
        omega = torch.acos(dot)
        so = torch.sin(omega)

        #technically not mathematically correct, but more pleasing?
        res = (torch.sin((1.0-r.squeeze(1))*omega)/so).unsqueeze(1)*b1_normalized + (torch.sin(r.squeeze(1)*omega)/so).unsqueeze(1) * b2_normalized
        res *= (b1_norms * (1.0-r) + b2_norms * r).expand(-1,c)

        #edge cases for same or polar opposites
        res[dot > 1 - 1e-5] = b1[dot > 1 - 1e-5] 
        res[dot < 1e-5 - 1] = (b1 * (1.0-r) + b2 * r)[dot < 1e-5 - 1]
        return res
    
    def generate_bilinear_data(length_old, length_new, device):
        coords_1 = torch.arange(length_old, dtype=torch.float32, device=device).reshape((1,1,1,-1))
        coords_1 = torch.nn.functional.interpolate(coords_1, size=(1, length_new), mode="bilinear")
        ratios = coords_1 - coords_1.floor()
        coords_1 = coords_1.to(torch.int64)
        
        coords_2 = torch.arange(length_old, dtype=torch.float32, device=device).reshape((1,1,1,-1)) + 1
        coords_2[:,:,:,-1] -= 1
        coords_2 = torch.nn.functional.interpolate(coords_2, size=(1, length_new), mode="bilinear")
        coords_2 = coords_2.to(torch.int64)
        return ratios, coords_1, coords_2

    orig_dtype = samples.dtype
    samples = samples.float()
    n,c,h,w = samples.shape
    h_new, w_new = (height, width)
    
    #linear w
    ratios, coords_1, coords_2 = generate_bilinear_data(w, w_new, samples.device)
    coords_1 = coords_1.expand((n, c, h, -1))
    coords_2 = coords_2.expand((n, c, h, -1))
    ratios = ratios.expand((n, 1, h, -1))

    pass_1 = samples.gather(-1,coords_1).movedim(1, -1).reshape((-1,c))
    pass_2 = samples.gather(-1,coords_2).movedim(1, -1).reshape((-1,c))
    ratios = ratios.movedim(1, -1).reshape((-1,1))

    result = slerp(pass_1, pass_2, ratios)
    result = result.reshape(n, h, w_new, c).movedim(-1, 1)

    #linear h
    ratios, coords_1, coords_2 = generate_bilinear_data(h, h_new, samples.device)
    coords_1 = coords_1.reshape((1,1,-1,1)).expand((n, c, -1, w_new))
    coords_2 = coords_2.reshape((1,1,-1,1)).expand((n, c, -1, w_new))
    ratios = ratios.reshape((1,1,-1,1)).expand((n, 1, -1, w_new))

    pass_1 = result.gather(-2,coords_1).movedim(1, -1).reshape((-1,c))
    pass_2 = result.gather(-2,coords_2).movedim(1, -1).reshape((-1,c))
    ratios = ratios.movedim(1, -1).reshape((-1,1))

    result = slerp(pass_1, pass_2, ratios)
    result = result.reshape(n, h_new, w_new, c).movedim(-1, 1)
    return result.to(orig_dtype)

def lnl_lanczos(samples, width, height):
    images = [Image.fromarray(np.clip(255. * image.movedim(0, -1).cpu().numpy(), 0, 255).astype(np.uint8)) for image in samples]
    images = [image.resize((width, height), resample=Image.Resampling.LANCZOS) for image in images]
    images = [torch.from_numpy(np.array(image).astype(np.float32) / 255.0).movedim(-1, 0) for image in images]
    result = torch.stack(images)
    return result.to(samples.device, samples.dtype)

def lnl_common_upscale(samples, width, height, upscale_method, crop):
        if crop == "center":
            old_width = samples.shape[3]
            old_height = samples.shape[2]
            old_aspect = old_width / old_height
            new_aspect = width / height
            x = 0
            y = 0
            if old_aspect > new_aspect:
                x = round((old_width - old_width * (new_aspect / old_aspect)) / 2)
            elif old_aspect < new_aspect:
                y = round((old_height - old_height * (old_aspect / new_aspect)) / 2)
            s = samples[:,:,y:old_height-y,x:old_width-x]
        else:
            s = samples

        if upscale_method == "bislerp":
            return lnl_bislerp(s, width, height)
        elif upscale_method == "lanczos":
            return lnl_lanczos(s, width, height)
        else:
            return torch.nn.functional.interpolate(s, size=(height, width), mode=upscale_method)

def lnl_target_size(width, height, force_size, custom_width, custom_height) -> tuple[int, int]:
    if force_size == "Custom":
        return (custom_width, custom_height)
    elif force_size == "Custom Height":
        force_size = "?x"+str(custom_height)
    elif force_size == "Custom Width":
        force_size = str(custom_width)+"x?"

    if force_size != "Disabled":
        force_size = force_size.split("x")
        if force_size[0] == "?":
            width = (width*int(force_size[1]))//height
            #Limit to a multple of 8 for latent conversion
            width = int(width)+4 & ~7
            height = int(force_size[1])
        elif force_size[1] == "?":
            height = (height*int(force_size[0]))//width
            height = int(height)+4 & ~7
            width = int(force_size[0])
        else:
            width = int(force_size[0])
            height = int(force_size[1])
    return (width, height)

def get_video_info(video_path):
    full_video_path = video_path
    if not os.path.isabs(full_video_path) and not os.path.exists(full_video_path):
        full_video_path = os.path.join(base_path, video_path)
    if not os.path.exists(full_video_path):
        raise Exception(f"Video path does not exist: {full_video_path}")

    frame_rate = None
    total_frames = None
    duration = None

    ffprobe_cmd = shutil.which("ffprobe")
    if ffprobe_cmd is None and ffmpeg_path is not None:
        ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        ffprobe_candidate = os.path.join(os.path.dirname(ffmpeg_path), ffprobe_name)
        if os.path.exists(ffprobe_candidate):
            ffprobe_cmd = ffprobe_candidate

    if ffprobe_cmd is not None:
        cmd = [
            ffprobe_cmd, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=avg_frame_rate,r_frame_rate,nb_frames,duration',
            '-show_entries', 'format=duration',
            '-of', 'json',
            full_video_path,
        ]
        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            data = json.loads(process.stdout) if process.stdout else {}
        except json.JSONDecodeError:
            data = {}

        stream = None
        streams = data.get("streams") or []
        if streams:
            stream = streams[0]

        def _parse_rate(rate_value):
            if rate_value is None:
                return None
            if isinstance(rate_value, (int, float)):
                return float(rate_value)
            if isinstance(rate_value, str):
                if "/" in rate_value:
                    try:
                        num, den = map(float, rate_value.split("/", 1))
                        if den != 0:
                            return num / den
                    except ValueError:
                        return None
                try:
                    return float(rate_value)
                except ValueError:
                    return None
            return None

        if stream:
            frame_rate = _parse_rate(stream.get("avg_frame_rate")) or _parse_rate(stream.get("r_frame_rate"))
            nb_frames = stream.get("nb_frames")
            nb_read_frames = stream.get("nb_read_frames")
            stream_duration = stream.get("duration")

            def _parse_int(value):
                if isinstance(value, (int, float)):
                    return int(value)
                if isinstance(value, str) and value.isdigit():
                    return int(value)
                return None

            parsed_read = _parse_int(nb_read_frames)
            parsed_meta = _parse_int(nb_frames)
            if parsed_read is not None:
                total_frames = parsed_read
            elif parsed_meta is not None:
                total_frames = parsed_meta

            try:
                if duration is None and stream_duration is not None:
                    duration = float(stream_duration)
            except ValueError:
                duration = None

        if duration is None:
            try:
                duration = float(data.get("format", {}).get("duration"))
            except (TypeError, ValueError):
                duration = None

        if total_frames is None and frame_rate and duration:
            total_frames = int(round(duration * frame_rate))

    if frame_rate is None or total_frames is None or duration is None:
        cap = cv2.VideoCapture(full_video_path)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if frame_rate is None and fps > 0:
                frame_rate = fps
            if total_frames is None and frame_count > 0:
                total_frames = int(frame_count)
            if duration is None and fps > 0 and frame_count > 0:
                duration = frame_count / fps

            if ffprobe_cmd is None:
                try:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    precise_count = 0
                    while True:
                        ok = cap.grab()
                        if not ok:
                            break
                        precise_count += 1
                    if precise_count > 0:
                        total_frames = int(precise_count)
                        if frame_rate and frame_rate > 0:
                            duration = total_frames / frame_rate
                except Exception:
                    pass
        cap.release()

    if frame_rate is None or frame_rate <= 0:
        frame_rate = 1.0
    if total_frames is None or total_frames <= 0:
        total_frames = 1
    if duration is None or duration <= 0:
        duration = total_frames / frame_rate

    return frame_rate, total_frames, duration

ffmpeg_paths = []
try:
    from imageio_ffmpeg import get_ffmpeg_exe
    imageio_ffmpeg_path = get_ffmpeg_exe()
    ffmpeg_paths.append(imageio_ffmpeg_path)
except:
    print("Failed to import imageio_ffmpeg")
system_ffmpeg = shutil.which("ffmpeg")
if system_ffmpeg is not None:
    ffmpeg_paths.append(system_ffmpeg)

if len(ffmpeg_paths) == 0:
    print("No valid ffmpeg found.")
    ffmpeg_path = None
elif len(ffmpeg_paths) == 1:
    ffmpeg_path = ffmpeg_paths[0]
else:
    ffmpeg_path = max(ffmpeg_paths, key=__lnl_ffmpeg_suitability)


class LazyImageTensor:
    """惰性图像张量：包装解码函数，首次实际访问数据时才触发 ffmpeg 解码。

    可通过 __torch_function__ 协议参与 torch 函数的派发，
    支持 .shape/.to()/.clone() 等常用张量属性和方法。
    适合用于"输出已连接但不一定每次都需要"的场景（如 Image Batch）。
    """
    def __init__(self, shape, decode_fn, desc=""):
        self._shape = tuple(shape)
        self._decode_fn = decode_fn
        self._desc = desc
        self._tensor = None

    def _resolve(self):
        if self._tensor is None:
            print(f"[LNL] 触发惰性张量解码: {self._desc}")
            import time as _time
            _t0 = _time.time()
            self._tensor = self._decode_fn()
            _elapsed = _time.time() - _t0
            print(f"[LNL] 惰性张量解码完成: {_elapsed:.2f}s shape={self._tensor.shape}")
        return self._tensor

    @property
    def shape(self):
        return self._shape

    @property
    def dtype(self):
        return torch.float32

    @property
    def device(self):
        return torch.device('cpu')

    @property
    def ndim(self):
        return len(self._shape)

    def __len__(self):
        return self._shape[0]

    def __getitem__(self, key):
        return self._resolve()[key]

    def __iter__(self):
        return iter(self._resolve())

    def __contains__(self, item):
        return item in self._resolve()

    def __torch_function__(self, func, types, args=(), kwargs=None):
        if kwargs is None:
            kwargs = {}
        resolved_args = tuple(
            a._resolve() if isinstance(a, LazyImageTensor) else a
            for a in args
        )
        resolved_kwargs = {
            k: v._resolve() if isinstance(v, LazyImageTensor) else v
            for k, v in kwargs.items()
        }
        return func(*resolved_args, **resolved_kwargs)

    # --- 常用张量方法委托 ---
    def to(self, *args, **kwargs):
        return self._resolve().to(*args, **kwargs)

    def cpu(self):
        return self._resolve().cpu()

    def cuda(self, device=None):
        return self._resolve().cuda(device)

    def clone(self):
        return self._resolve().clone()

    def detach(self):
        return self._resolve().detach()

    def contiguous(self):
        return self._resolve().contiguous()

    def float(self):
        return self._resolve().float()

    def half(self):
        return self._resolve().half()

    def double(self):
        return self._resolve().double()

    def numpy(self):
        return self._resolve().numpy()

    def view(self, *shape):
        return self._resolve().view(*shape)

    def reshape(self, *shape):
        return self._resolve().reshape(*shape)

    def permute(self, *dims):
        return self._resolve().permute(*dims)

    def unsqueeze(self, dim):
        return self._resolve().unsqueeze(dim)

    def squeeze(self, dim=None):
        return self._resolve().squeeze(dim) if dim is not None else self._resolve().squeeze()

    def expand(self, *sizes):
        return self._resolve().expand(*sizes)

    def repeat(self, *sizes):
        return self._resolve().repeat(*sizes)

    def size(self, dim=None):
        return self._resolve().size(dim) if dim is not None else self._resolve().size()

    def numel(self):
        return self._resolve().numel()

    def mean(self, *args, **kwargs):
        return self._resolve().mean(*args, **kwargs)

    def sum(self, *args, **kwargs):
        return self._resolve().sum(*args, **kwargs)

    def min(self, *args, **kwargs):
        return self._resolve().min(*args, **kwargs)

    def max(self, *args, **kwargs):
        return self._resolve().max(*args, **kwargs)

    def abs(self):
        return self._resolve().abs()

    def neg(self):
        return self._resolve().neg()

    def sqrt(self):
        return self._resolve().sqrt()

    def type(self, *args, **kwargs):
        return self._resolve().type(*args, **kwargs)

    def type_as(self, tensor):
        return self._resolve().type_as(tensor)

    def requires_grad_(self, requires_grad=True):
        return self._resolve().requires_grad_(requires_grad)

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._resolve(), name)

    def __repr__(self):
        status = "resolved" if self._tensor is not None else "lazy"
        return f"LazyImageTensor(shape={self._shape}, {status}, desc='{self._desc}')"
