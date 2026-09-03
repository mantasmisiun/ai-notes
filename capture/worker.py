#!/usr/bin/env python3
"""Capture the microphone, transcribe it in near-real-time into a markdown note,
then compress the audio into the vault and embed it.

Audio is written as headerless raw PCM so that a power cut costs only the tail,
never the whole file.
"""
import os, sys, re, time, json, wave, signal, subprocess, datetime, threading

from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
# faster_whisper and the CUDA libraries are imported inside main(), AFTER the
# microphone is open. They take seconds to load, and every one of those seconds
# was audio the user believed was being recorded.

RATE       = 16000
# Whisper's encoder always processes exactly 30 seconds: a shorter buffer is
# padded to that length, so it costs the same. Window size is therefore free up
# to 30s and only the update interval costs anything, which is why the old
# 12-second tiling wasted most of its compute and saw less context than Whisper
# expects. The interval comes from the benchmark: roughly 2 x 30 / real-time
# factor, so a fast machine updates often and a slow one does not fall behind.
WINDOW_SECS   = int(os.environ.get("LECTURE_WINDOW_SECS", "30"))
INTERVAL_SECS = int(os.environ.get("LECTURE_CHUNK_SECS", "12"))
MODEL      = os.environ.get("LECTURE_MODEL", "small.en")
# Three backends. cuda and cpu run faster-whisper (CTranslate2). vulkan runs
# whisper.cpp built with GGML_VULKAN, the only route onto an AMD or Intel GPU
# because CTranslate2 has no Vulkan. The benchmark measured vulkan with
# whisper.cpp while this worker knew only faster-whisper, so a config that said
# vulkan ran medium.en on the CPU at six threads and could not hold the
# interval that had been measured on the GPU.
BACKEND    = os.environ.get("LECTURE_BACKEND", "cpu").lower()
DEVICE     = "cuda" if BACKEND == "cuda" else "cpu"
COMPUTE    = os.environ.get("LECTURE_COMPUTE",
                            "int8_float16" if DEVICE == "cuda" else "int8")
THREADS    = int(os.environ.get("LECTURE_THREADS", "6"))
BITRATE    = os.environ.get("LECTURE_BITRATE", "24k")
LANGUAGE   = os.environ.get("LECTURE_LANGUAGE", "en")
WCPP       = Path(os.environ.get("LECTURE_WCPP")
                  or Path(__file__).resolve().parent / "whisper.cpp")

note_path = sys.argv[1]   # markdown note
raw_path  = sys.argv[2]   # scratch .pcm, outside the vault
ogg_path  = sys.argv[3]   # final .ogg, inside the vault
vault     = sys.argv[4]   # vault root, to build the embed link

_quiet = dict                 # replaced once the platform layer is imported
stop = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stop.set())
signal.signal(signal.SIGINT,  lambda *_: stop.set())

# On Windows a parent cannot deliver SIGTERM: Popen.terminate() there is an
# instant kill that runs no handler, so the last window was never flushed and
# the audio never converted. The stop request therefore arrives as a file, which
# works identically everywhere, and the signal handlers stay for Linux.
STOP_FILE = os.environ.get("LECTURE_STOP_FILE", "")


def stop_requested():
    return stop.is_set() or (STOP_FILE and os.path.exists(STOP_FILE))


def log(msg):
    """Progress to stderr, which record.py sends to worker.log. A run that
    quietly does nothing must look different from one that works."""
    try:
        print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", file=sys.stderr, flush=True)
    except Exception:
        pass


def append(text):
    with open(note_path, "a", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


# A chunk of two or more characters repeated three or more times inside one
# word is never speech. The segment-level compression ratio misses it when the
# segment also holds real words: a flush on trailing silence appended
# "džiaugiuosiuosiuosiuosiuose" after a correct final sentence.
STUTTER = re.compile(r"(..+?)\1{2,}")


class CT2Backend:
    """faster-whisper on CUDA or CPU. units() returns (start, end, word) for
    one buffer, already stripped of what Whisper's own statistics call
    hallucination."""
    name = DEVICE

    def __init__(self):
        import cuda_libs; cuda_libs.enable()
        from faster_whisper import WhisperModel
        self.model = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE,
                                  cpu_threads=THREADS)

    def units(self, buf_bytes):
        audio = np.frombuffer(buf_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio, language=LANGUAGE, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False,
            word_timestamps=True)
        out = []
        for seg in segments:
            # Whisper's own confidence statistics flag hallucinations, applied
            # by Whisper's own rule: a segment is silence being narrated only
            # when no-speech probability is high AND log-probability is low,
            # together. Dropping on low log-probability alone, as an earlier
            # version did, threw away whole 30-second windows of Lithuanian
            # from a multilingual model, whose every segment scores low; the
            # note then did not change for passes on end and the last words
            # before Stop never landed. High compression ratio is repetition
            # and is dropped on its own: a flush on trailing silence once
            # produced a dozen copies of one invented word.
            if (getattr(seg, "compression_ratio", 0) > 2.4
                    or (getattr(seg, "no_speech_prob", 0) > 0.6
                        and getattr(seg, "avg_logprob", 0) < -1.0)):
                continue
            words = seg.words or []
            if words:
                out += [(w.start, w.end, w.word.strip()) for w in words]
            else:
                out.append((seg.start, seg.end, seg.text.strip()))
        return out


class WhisperCppBackend:
    """whisper.cpp on Vulkan: one whisper-cli run per pass, one word per
    segment (-ml 1 -sow) so settling works on word timestamps exactly as with
    faster-whisper. The model is loaded afresh each pass, which is what the
    benchmark timed, so the interval it chose already includes that cost."""
    name = "vulkan"

    def __init__(self, scratch):
        self.cli  = WCPP / "build" / "bin" / "whisper-cli"
        # a converted directory such as paprika-whisper-lt-ct2 has its GGML
        # twin beside whisper.cpp's other models, ggml-paprika-whisper-lt.bin
        name = os.path.basename(MODEL.rstrip("/")) if os.path.isdir(MODEL) else MODEL
        name = name[:-4] if name.endswith("-ct2") else name
        self.ggml = WCPP / "models" / f"ggml-{name}.bin"
        if not self.cli.is_file():
            raise FileNotFoundError(f"{self.cli} is not built")
        if not self.ggml.is_file() and os.path.isdir(MODEL):
            raise FileNotFoundError(f"{self.ggml} was not converted")
        if not self.ggml.is_file():
            log(f"fetching {self.ggml.name} for whisper.cpp")
            subprocess.run(["sh", str(WCPP / "models" / "download-ggml-model.sh"), MODEL],
                           cwd=str(WCPP), check=True, capture_output=True)
        # Its shared libraries sit beside the binary. The build's RPATH pointed
        # into a build directory that no longer existed, and the binary could
        # not start until the path was given explicitly.
        self.libpath = dict(os.environ, LD_LIBRARY_PATH=str(self.cli.parent) + ":"
                            + os.environ.get("LD_LIBRARY_PATH", ""))
        # the window goes through a WAV on disk, in the scratch directory, never
        # in /tmp, which on this laptop is a RAM disk
        self.wav  = Path(scratch) / f".live-{os.getpid()}.wav"
        self.base = Path(scratch) / f".live-{os.getpid()}"
        self.first = True

    def units(self, buf_bytes):
        with wave.open(str(self.wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(buf_bytes)
        r = subprocess.run([str(self.cli), "-m", str(self.ggml), "-l", LANGUAGE,
                            "-t", str(THREADS), "-f", str(self.wav),
                            "-ml", "1", "-sow", "-oj", "-of", str(self.base), "-np"],
                           capture_output=True, text=True, env=self.libpath, **_quiet())
        if self.first:
            self.first = False
            for line in r.stderr.splitlines():
                if "ggml_vulkan" in line:          # proof of which device runs this
                    log(line.strip())
        js = self.base.with_suffix(".json")
        if r.returncode != 0 or not js.is_file():
            log(f"whisper-cli failed ({r.returncode}): {r.stderr.strip()[-300:]}")
            return []
        with open(js, encoding="utf-8") as f:
            entries = json.load(f).get("transcription", [])
        out = []
        for e in entries:
            text = e.get("text", "").strip()
            # whisper.cpp names silence and music in brackets
            if not text or (text[0] in "[(" and text[-1] in "])"):
                continue
            o = e.get("offsets", {})
            out.append((o.get("from", 0) / 1000.0, o.get("to", 0) / 1000.0, text))
        return out

    def close(self):
        for p in (self.wav, self.base.with_suffix(".json")):
            try:
                p.unlink()
            except OSError:
                pass


class Live:
    """Keeps the note in step with a rolling window.

    Each pass re-reads the last WINDOW seconds, so text near the end can change
    as more context arrives. Anything older than one interval is settled and
    kept; the tail is provisional and rewritten each time.
    """

    def __init__(self, header):
        self.header = header
        self.settled = ""          # text that will not change again
        self.settled_until = 0.0   # audio seconds covered by settled

    def write(self, provisional=""):
        body = (self.settled + provisional).strip()
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(self.header + body + "\n")
            f.flush()
            os.fsync(f.fileno())

    def update(self, backend, buf_bytes, buf_start, now):
        # Only the last interval is still in flux; everything before it has had
        # the full window of context and will not improve.
        cutoff_abs = now - INTERVAL_SECS

        # Settle WORDS, not segments. Whisper breaks segments mostly at
        # punctuation, and a model that emits none, or a speaker who never
        # pauses, yields segments that run to the present on every pass. Then
        # nothing ever ends before the cutoff, nothing settles, and once the
        # window slides the beginning falls off the buffer unwritten. Replaying
        # a real recording showed settled_until stuck at 0.0 for a full minute
        # and the first thirty words lost.
        keep, tail, settled_to = [], [], self.settled_until
        for w_start, w_end, text in backend.units(buf_bytes):
            if not text or STUTTER.search(text):
                continue
            start_abs, end_abs = buf_start + w_start, buf_start + w_end
            # Skip by where the word STARTS, with tolerance. Re-alignment
            # shifts a word's end by a fraction of a second between passes,
            # so a word settled just before the cutoff reappeared just after
            # the settled mark on the next pass and was written twice.
            if start_abs < self.settled_until - 0.15 or end_abs <= self.settled_until:
                continue
            if end_abs <= cutoff_abs:
                keep.append(text)
                settled_to = max(settled_to, end_abs)
            else:
                tail.append(text)

        # collapse a word repeated back to back, which is never speech
        def dedupe(ws):
            out = []
            for w in ws:
                if not out or out[-1].lower() != w.lower():
                    out.append(w)
            return out
        keep, tail = dedupe(keep), dedupe(tail)
        if keep and self.settled.split() and keep[0].lower() == self.settled.split()[-1].lower():
            keep = keep[1:]

        if keep:
            self.settled = (self.settled + " " + " ".join(keep)).strip() + " "
            self.settled_until = settled_to
        self.write(" ".join(tail))

    def flush_all(self, backend, buf_bytes, buf_start, now):
        """At stop there is no later pass to revise the tail, so settle it all."""
        self.update(backend, buf_bytes, buf_start, now + INTERVAL_SECS + 1)


def finalise():
    """Compress raw PCM into the vault and embed it. Keep the raw file if
    anything goes wrong, so audio is never lost to a failed conversion."""
    if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
        append("\n\n---\n*Stopped. No audio was captured.*\n")
        return
    os.makedirs(os.path.dirname(ogg_path), exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", raw_path,
         "-c:a", "libopus", "-b:a", BITRATE, ogg_path],
        capture_output=True, **_quiet())
    # The recording length is known precisely here, so the End cell is filled
    # in rather than left for you to type and mistype.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
        import rawnote
        notes_root = Path(ogg_path).parent.parent
        if notes_root.name == "auto":            # audio lives in auto/audio
            notes_root = notes_root.parent
        stamp_ = Path(ogg_path).stem
        rn = notes_root / "your notes" / f"{stamp_}.md"
        if rn.exists():
            rawnote.set_field(rn, "End", f"{datetime.datetime.now():%Y-%m-%d %H:%M}")
    except Exception:
        pass                       # never let bookkeeping lose a recording

    if r.returncode == 0 and os.path.exists(ogg_path):
        # forward slashes: os.path.relpath returns backslashes on Windows and
        # Obsidian does not resolve those
        rel = os.path.relpath(ogg_path, vault).replace(os.sep, "/")
        mb  = os.path.getsize(ogg_path) / 1e6
        os.remove(raw_path)
        append(f"\n\n---\n\n## Recording\n\n![[{rel}]]\n\n"
               f"*Stopped {datetime.datetime.now():%H:%M}, {mb:.1f} MB.*\n")
    else:
        append(f"\n\n---\n*Stopped {datetime.datetime.now():%H:%M}. "
               f"Conversion failed, raw audio kept at `{raw_path}` "
               f"(s16le, {RATE} Hz, mono).*\n")


def main():
    # "none" means the benchmark found nothing on this machine that keeps up
    # live, and the user chose to record anyway. Audio is still captured and
    # converted; the accurate transcript comes later from a machine that can.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
    import platform_support as ps
    global _quiet
    _quiet = ps.quiet_popen_kwargs
    if os.environ.get("LECTURE_INPUT"):
        src = os.environ["LECTURE_INPUT"].split(":", 1)
        # -re makes a synthetic source play at real time. Without it lavfi
        # generates as fast as it can, so a "25 second" test consumes the whole
        # source in seconds and never exercises the stop path at all.
        source = (["-re"] if src[0] == "lavfi" else []) + ["-f", src[0], "-i", src[1]]
    else:
        source = ps.default_input_device()

    log("ffmpeg source: " + " ".join(source))
    ff = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error"] + source +
        ["-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE, **_quiet())

    win_bytes  = RATE * 2 * WINDOW_SECS
    step_bytes = RATE * 2 * INTERVAL_SECS

    # Reading ffmpeg and transcribing must not share a thread. A pass blocks
    # for seconds, and on a machine near its limit passes run back to back, so
    # nothing drained ffmpeg and its capture buffer overflowed: the log filled
    # with "real-time buffer too full, frame dropped" and audio was lost. The
    # reader thread owns the pipe and the raw file; the main thread only
    # transcribes from a snapshot of the rolling window.
    import queue
    chunks_q = queue.Queue()

    capturing = os.environ.get("LECTURE_CAPTURING_FILE", "")

    def reader():
        first = True
        with open(raw_path, "wb") as raw:
            while True:
                data = ff.stdout.read(4096)
                if not data:
                    log("audio source ended")
                    if first:
                        # never produced a byte: the cached device is stale
                        ps.forget_input_device()
                    chunks_q.put(None)
                    return
                if first:
                    log("first audio received")
                    first = False
                    if capturing:
                        try:
                            Path(capturing).touch()   # the window starts its clock now
                        except OSError:
                            pass
                raw.write(data)
                raw.flush()
                chunks_q.put(data)

    threading.Thread(target=reader, daemon=True).start()

    # Capture is already running; the first pass will pick up the backlog.
    record_only = MODEL.strip().lower() in ("", "none")
    log(f"model={MODEL!r} backend={BACKEND} device={DEVICE} compute={COMPUTE} "
        f"window={WINDOW_SECS}s interval={INTERVAL_SECS}s language={LANGUAGE}")
    backend = None
    if record_only:
        log("record-only mode: no live transcription on this machine")
        append("*Recording audio only: no live transcript on this machine. "
               "The transcript and notes are produced afterwards.*\n\n")
    else:
        append(f"*Model `{os.path.basename(MODEL.rstrip('/'))}` on {BACKEND}, "
               f"{WINDOW_SECS}s window every {INTERVAL_SECS}s. Loading...*\n")
        if BACKEND == "vulkan":
            try:
                backend = WhisperCppBackend(Path(raw_path).parent)
            except Exception as e:
                # never lose a recording to a missing build: the CPU is slower,
                # not absent
                log(f"vulkan backend unavailable ({e}); falling back to faster-whisper on cpu")
                append("*whisper.cpp is not available here; running on the CPU instead.*\n")
        if backend is None:
            backend = CT2Backend()
        log(f"model loaded on {backend.name}")
        append("*ready, recording*\n\n")
    ready = os.environ.get("LECTURE_READY_FILE", "")
    if ready:
        try:
            Path(ready).touch()
        except Exception:
            pass

    # Everything record.py and the load messages wrote stays as the header; the
    # body below it is rewritten each pass because the tail can change.
    header = open(note_path, encoding="utf-8").read()
    live = Live(header)

    buf = b""                 # the rolling window, at most win_bytes
    since_pass = 0            # bytes accumulated since the last transcription
    total = 0                 # bytes of audio seen, for absolute timing
    ended = False

    try:
        while not stop_requested() and not ended:
            # take everything that has arrived; block briefly only when idle
            try:
                data = chunks_q.get(timeout=0.25)
            except queue.Empty:
                continue
            while data is not None:
                buf += data
                total += len(data)
                since_pass += len(data)
                try:
                    data = chunks_q.get_nowait()
                except queue.Empty:
                    break
            if data is None:
                ended = True
                live.write("\n\n*Audio source ended unexpectedly.*")
            # Keep at least the window, and never less than the audio no pass has
            # transcribed yet plus ten seconds of context. Trimming to a fixed
            # 30 s meant a late pass silently lost whatever had aged past it.
            keep_bytes = max(win_bytes, since_pass + RATE * 2 * 10)
            if len(buf) > keep_bytes:
                buf = buf[-keep_bytes:]

            if backend is not None and since_pass >= step_bytes:
                now = total / (RATE * 2)
                t0 = datetime.datetime.now()
                live.update(backend, buf, now - len(buf) / (RATE * 2), now)
                log(f"pass at {now:.0f}s of audio took "
                    f"{(datetime.datetime.now() - t0).total_seconds():.1f}s; "
                    f"settled {len(live.settled.split())} words")
                since_pass = 0

        # Stop the microphone first, then take every byte ffmpeg emitted before
        # the last pass. Stop used to flush the window as of the previous
        # drain, so the final fraction of a second was in the audio but never
        # in the text. Draining has to follow the terminate: a live source
        # never goes quiet on its own, so waiting for the queue to empty
        # would wait forever.
        if not ended:
            ff.terminate()
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    data = chunks_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if data is None:
                    break
                buf += data
                total += len(data)
        log(f"stopping after {total / (RATE * 2):.0f}s of audio")
        if backend is not None and buf:
            now = total / (RATE * 2)
            live.flush_all(backend, buf, now - len(buf) / (RATE * 2), now)
            log(f"final pass done; settled {len(live.settled.split())} words")
    finally:
        ff.terminate()
        try:
            ff.wait(timeout=5)
        except Exception:
            ff.kill()
        if backend is not None and hasattr(backend, "close"):
            backend.close()
        finalise()


if __name__ == "__main__":
    main()
