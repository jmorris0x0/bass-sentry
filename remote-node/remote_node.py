import argparse
import functools
import json
import logging
import multiprocessing
import os
import platform
import signal
import sys
import time
from functools import partial
from pprint import pprint, pformat

import numpy as np
import ntplib
import sounddevice as sd
from scipy.signal import fftconvolve

# Add parent directory to path for common imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.time_sync import TimeSync

from processors import SignalProcessor
from telemetry_sender import TelemetrySender


def get_input_device():
    # PortAudio caches its device list at first init. If the USB audio
    # device enumerated AFTER python startup (recorder was patiently
    # waiting for it), sd.query_devices() will keep returning the stale
    # "no devices" view forever. Terminate+reinitialize forces a rescan.
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass

    devices = sd.query_devices()

    if platform.system() == "Linux":  # Assume Raspberry Pi
        for i, d in enumerate(devices):
            if "USB Audio CODEC" in d["name"]:
                return d
        return sd.query_devices(kind="input")  # Use the default device
    else:  # Use the default device
        return sd.query_devices(kind="input")


BIT_DEPTH = 16  # Default to 16 if subtype is not PCM

DATA_TYPE_MAPPING = {
    8: np.int8,
    16: np.int16,
    32: np.int32,
    64: np.int64,
}
FORMAT = DATA_TYPE_MAPPING[BIT_DEPTH]
TP_FACTORS = {"ns": 1e9, "us": 1e6, "ms": 1e3, "s": 1}
TIME_PRECISION = "ns"
TP_FACTOR = TP_FACTORS[TIME_PRECISION]

# Best-effort device query at import time. If USB audio isn't present now
# (over-current event, physical disconnect, cold boot before enumeration),
# fall through with safe defaults so the process can still start. The
# recorder subprocess re-queries and waits for the device to appear.
try:
    device_info = get_input_device()
    RATE = int(device_info["default_samplerate"])
    INPUT_DEVICE = int(device_info["index"])
except Exception as e:
    logging.warning(f"Audio device not available at import: {e}. Will retry in recorder.")
    RATE = 44100
    INPUT_DEVICE = -1

CHANNELS = 1
SENDING_RATE = 2  # Hz
CHUNK = int(RATE / SENDING_RATE)

# Cache for one-shot Graylog auto-discovery. Sentinel distinguishes
# "not yet queried" from "queried and found nothing".
_SENTINEL = object()
_CACHED_GRAYLOG_HOST = _SENTINEL
_GRAYLOG_LOGGED = False
# Maximum queue size to prevent memory exhaustion (max ~30 seconds of buffering)
MAX_QUEUE_SIZE = 60  # 60 chunks = 30 seconds at 2 Hz


def setup_logging():
    """
    Set up logging with optional Graylog support.

    Environment variables:
        GRAYLOG_HOST: Graylog server hostname (default: none, disables Graylog)
        GRAYLOG_PORT: Graylog GELF UDP port (default: 12201)
        LOG_LEVEL: Logging level (default: INFO)
        NODE_NAME: Node identifier for log tagging
    """
    # Define your date format
    date_format = "%Y-%m-%d %H:%M:%S %Z"  # This includes timezone information

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Include the asctime field in your format string and set the datefmt parameter
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s - Line %(lineno)d",
        datefmt=date_format,
    )
    logger = logging.getLogger(__name__)

    # Autodetect Graylog host if not explicitly set. RUNS ONCE PER PROCESS
    # — setup_logging() is called from the audio callback and other hot
    # paths, and doing a 2-second mDNS lookup on every call was blocking
    # the PortAudio callback long enough to cause the very overflow it
    # was trying to log. Cache the result at module scope so subsequent
    # calls are a fast dict lookup.
    global _CACHED_GRAYLOG_HOST, _GRAYLOG_LOGGED
    graylog_host = os.environ.get("GRAYLOG_HOST")
    if not graylog_host:
        if _CACHED_GRAYLOG_HOST is _SENTINEL:
            try:
                from zeroconf import Zeroconf, ServiceBrowser
                import socket as _sock
                zc = Zeroconf()
                found = {"host": None}

                class _Listener:
                    def add_service(self, zc, type_, name):
                        info = zc.get_service_info(type_, name, timeout=1500)
                        if info and info.addresses:
                            found["host"] = _sock.inet_ntoa(info.addresses[0])
                    def remove_service(self, *a, **k): pass
                    def update_service(self, *a, **k): pass
                ServiceBrowser(zc, "_telemetryservice._tcp.local.", _Listener())
                for _ in range(20):
                    if found["host"]: break
                    time.sleep(0.1)
                zc.close()
                _CACHED_GRAYLOG_HOST = found["host"]
            except Exception:
                _CACHED_GRAYLOG_HOST = None
        graylog_host = _CACHED_GRAYLOG_HOST
        if graylog_host and not _GRAYLOG_LOGGED:
            logger.info(f"Graylog host auto-discovered: {graylog_host}")
            _GRAYLOG_LOGGED = True

    if graylog_host:
        try:
            import graypy
            import socket
            # Only add the Graylog handler once per process. Root logger
            # already has one -> setup_logging was called earlier in the
            # same process, don't stack duplicates.
            root = logging.getLogger()
            if not any(isinstance(h, graypy.GELFUDPHandler) for h in root.handlers):
                graylog_port = int(os.environ.get("GRAYLOG_PORT", "12201"))
                node_name = os.environ.get("NODE_NAME") or socket.gethostname()
                handler = graypy.GELFUDPHandler(graylog_host, graylog_port)
                handler.facility = f"bass-sentry-{node_name}"
                root.addHandler(handler)
                logger.info(f"Graylog logging enabled: {graylog_host}:{graylog_port}")
        except ImportError:
            logger.warning("graypy not installed, Graylog logging disabled")
        except Exception as e:
            logger.warning(f"Failed to setup Graylog logging: {e}")

    return logger


def signal_handler(recorder_process, sender_process, time_sync_manager, sig, frame):
    logger = setup_logging()
    logger.info("Received signal to terminate.")

    # Stop time sync first
    if time_sync_manager:
        time_sync_manager.stop()

    # Terminate processes
    recorder_process.terminate()
    sender_process.terminate()
    recorder_process.join()
    sender_process.join()
    sys.exit(0)


def get_ntp_offset(ntp_server="pool.ntp.org"):
    logger = setup_logging()
    try:
        c = ntplib.NTPClient()
        response = c.request(ntp_server, version=3)
        return response.offset
    except Exception as e:
        logger.error(f"Failed to get NTP offset: {e}")
        return 0


def callback(
    indata,
    frames,
    time,
    status,
    data_queue,
    initial_time,
    ns_between_messages,
    sample_counter,
    time_sync,
    overflow_counter=None,
):
    # Never call setup_logging() inside this function — it runs on the
    # PortAudio callback thread and any blocking work (mDNS lookup,
    # handler-init, filesystem probes) delays the callback long enough
    # to cause the very input_overflow this function was trying to log.
    # Use the module-level logger directly; setup_logging has already
    # run in main() before this callback ever fires.
    logger = logging.getLogger(__name__)

    if status:
        status_flags = str(status).replace("CallbackFlags.", "") if status else "None"
        logger.warning(f"Status flags: {status_flags}")
        if status.input_overflow:
            # Count overflows in shared memory so the sender subprocess
            # can report the total in each heartbeat.
            if overflow_counter is not None:
                with overflow_counter.get_lock():
                    overflow_counter.value += 1
            logger.warning(
                "Input overflow - buffer may be too small or system too slow, data may be lost!"
            )

    # Check queue size to prevent memory exhaustion
    if data_queue.qsize() >= MAX_QUEUE_SIZE:
        logger.error(
            f"Queue full ({data_queue.qsize()} items), dropping audio chunk! "
            f"Sender process may be too slow or stalled."
        )
        # Still increment counter to maintain timestamp consistency
        sample_counter.value += 1
        return

    # Calculate timestamp with drift compensation
    base_timestamp = initial_time + sample_counter.value * ns_between_messages

    # Apply time sync offset (converted to nanoseconds)
    offset_ns = int(time_sync.get_offset() * TP_FACTOR)
    timestamp = base_timestamp + offset_ns

    logger.debug(
        f"ns_between_messages: {ns_between_messages}, sample_counter: {sample_counter.value}, "
        f"timestamp: {timestamp}, offset: {offset_ns}ns"
    )
    data_queue.put((indata.copy(), timestamp))
    sample_counter.value += 1


def recorder(data_queue, sample_counter, time_sync_manager, overflow_counter=None):
    logger = setup_logging()

    # Get initial offset from time sync
    ntp_offset = time_sync_manager.get_offset()
    initial_time = int((time.time_ns() + ntp_offset * TP_FACTOR))
    ns_between_messages = int(TP_FACTOR / SENDING_RATE)

    callback_with_queue = partial(
        callback,
        data_queue=data_queue,
        initial_time=initial_time,
        ns_between_messages=ns_between_messages,
        sample_counter=sample_counter,
        time_sync=time_sync_manager,
        overflow_counter=overflow_counter,
    )

    # Watchdog: track when a callback last fired so we can detect a silently-dead
    # audio stream (USB device reset does not raise, callbacks just stop).
    last_callback = [time.monotonic()]

    def timing_callback(indata, frames, tinfo, status):
        last_callback[0] = time.monotonic()
        callback_with_queue(indata, frames, tinfo, status)

    def open_stream():
        # Re-query the device by name in case the USB reset changed its index.
        info = get_input_device()
        idx = int(info["index"])
        if idx < 0:
            raise RuntimeError("no input device available")
        return sd.InputStream(
            device=idx,
            callback=timing_callback,
            channels=CHANNELS,
            dtype=FORMAT,
            samplerate=int(info["default_samplerate"]),
            blocksize=CHUNK,
            # Ask PortAudio for its high-latency preset so ALSA buffers
            # more samples internally. Reduces overflow warnings on the
            # Pi 4B at the cost of ~50-100ms extra measurement latency,
            # which doesn't matter for this application.
            latency='high',
            finished_callback=lambda: logger.info("Stream finished"),
        )

    def wait_for_device_and_open(max_attempt_log_interval=10):
        # Poll until the USB audio device is present. Runs on cold start when
        # the device hadn't enumerated yet, and after a USB reset if the
        # stream reopen fails because the device is temporarily gone.
        attempt = 0
        while True:
            try:
                s = open_stream()
                s.start()
                logger.info("Audio stream open")
                return s
            except Exception as e:
                attempt += 1
                if attempt % max_attempt_log_interval == 1:
                    logger.warning(
                        f"Waiting for input device (attempt {attempt}): {e}"
                    )
                time.sleep(1.0)

    WATCHDOG_TIMEOUT = 3.0  # seconds without a callback -> assume stream is dead

    stream = wait_for_device_and_open()
    try:
        while True:
            time.sleep(0.5)

            silence = time.monotonic() - last_callback[0]
            if silence > WATCHDOG_TIMEOUT:
                logger.warning(
                    f"Audio callback silent for {silence:.1f}s, reopening stream"
                )
                try:
                    stream.stop()
                    stream.close()
                except Exception as e:
                    logger.warning(f"Error closing stalled stream: {e}")
                time.sleep(0.5)  # let the USB stack settle
                # Wait indefinitely for the device to be available. Blocks
                # here (no CPU spin) if USB is physically unplugged so we
                # don't crash the whole process — recovers automatically
                # when the device comes back.
                stream = wait_for_device_and_open()
                # reset watchdog so we don't immediately re-trip
                last_callback[0] = time.monotonic()
                continue

            # Periodically log time sync status
            if sample_counter.value % (SENDING_RATE * 60) == 0:  # Every minute
                stats = time_sync_manager.get_stats()
                logger.debug(
                    f"Time sync: offset={stats['last_offset_seconds']*1000:.1f}ms, "
                    f"drift={stats['drift_ppm']:.2f}ppm"
                )
    except KeyboardInterrupt:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        logger.info("Recording stopped by user")
        return


def sender(data_queue, config, overflow_counter=None):
    logger = setup_logging()

    # Extract transport configuration (if provided)
    transport_config = config.get("transport", None)

    # Retry TelemetrySender setup indefinitely. Construction calls
    # discover_service() (raises after 60 attempts) and transport connect
    # (raises after 3 attempts). If the master is briefly unavailable —
    # restarted, WiFi hiccup, mDNS not yet advertising — the original code
    # would kill this subprocess, leaving the parent stuck on recorder.join()
    # forever with no way to recover. Now we keep retrying with backoff
    # until we get a working telemetry sender.
    backoff = 5
    while True:
        try:
            telemetry = TelemetrySender(
                topic_suffix="remote_node", transport_config=transport_config
            )
            # Expose shared overflow counter to heartbeat.
            telemetry.handler.overflow_counter = overflow_counter
            break
        except Exception as e:
            logger.warning(
                f"TelemetrySender setup failed ({e}); retrying in {backoff}s"
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
    prev_timestamp = None
    dropped_chunks = 0
    total_chunks = 0

    # Create an instance of SignalProcessor
    signal_processor = SignalProcessor(config)

    # Extract location from the config
    location = config.get("location", "")

    try:
        while True:
            try:
                data, timestamp = data_queue.get(timeout=1)
            except multiprocessing.queues.Empty:
                continue

            total_chunks += 1

            # Monitor queue health
            queue_size = data_queue.qsize()
            if queue_size > MAX_QUEUE_SIZE * 0.8:
                logger.warning(
                    f"Queue is {queue_size}/{MAX_QUEUE_SIZE} full ({queue_size/MAX_QUEUE_SIZE*100:.1f}%)"
                )

            current_timestamp = int(time.time() * TP_FACTOR)
            drift = current_timestamp - timestamp
            logger.debug(f"Timestamp drift: {drift} ns")

            # Detect dropped chunks by checking timestamp continuity
            if prev_timestamp is not None:
                diff = timestamp - prev_timestamp
                expected_diff = int(TP_FACTOR / SENDING_RATE)
                if abs(diff - expected_diff) > expected_diff * 0.1:
                    dropped_chunks += 1
                    logger.error(
                        f"Timestamp discontinuity detected! Expected {expected_diff} ns, "
                        f"got {diff} ns. Chunks may have been dropped. "
                        f"Total dropped: {dropped_chunks}/{total_chunks}"
                    )
                logger.debug(f"Timestamp diff: {diff} ns")

            prev_timestamp = timestamp

            np_data = np.frombuffer(data, dtype=np.int16).astype(float)

            audio_data = {
                "data_type": "audio_chunk",
                "data": np_data.tolist(),
                "timestamp": timestamp,
                "time_precision": TIME_PRECISION,
                "metadata": {
                    "sample_rate": RATE,
                    "bit_depth": BIT_DEPTH,
                    "location": location,
                },
            }

            processed_data_list = signal_processor.process(audio_data)

            for processed_data in processed_data_list:
                processed_data["station_id"] = telemetry.unit_name
                if type(processed_data["data"]) == np.ndarray:
                    processed_data["data"] = processed_data["data"].tolist()
                logger.debug("Processed data: %s", pformat(processed_data))

                telemetry.send_data(processed_data)

    except KeyboardInterrupt:
        telemetry.stop()
    except Exception as e:
        logger.error(f"Unexpected error in sender: {e}")
        telemetry.stop()


def main():
    parser = argparse.ArgumentParser(description="Process signals.")
    parser.add_argument("config", type=str, help="Path to the JSON configuration file")
    parser.add_argument(
        "--ntp-server",
        type=str,
        default="pool.ntp.org",
        help="NTP server for time sync (default: pool.ntp.org)",
    )
    parser.add_argument(
        "--sync-interval",
        type=int,
        default=300,
        help="NTP sync interval in seconds (default: 300)",
    )
    args = parser.parse_args()

    # Python 3.13+ on Debian defaults to spawn, which requires picklable Process args.
    # TimeSync holds a threading.Lock and is passed into a Process below, so force fork.
    multiprocessing.set_start_method("fork", force=True)

    logger = setup_logging()

    # Read the JSON configuration file
    with open(args.config, "r") as f:
        config = json.load(f)

    # Initialize continuous time synchronization
    logger.info(f"Starting time sync with server: {args.ntp_server}")
    time_sync_manager = TimeSync(
        ntp_server=args.ntp_server, sync_interval=args.sync_interval
    )
    time_sync_manager.start()

    # Use bounded queue to prevent memory exhaustion
    data_queue = multiprocessing.Queue(maxsize=MAX_QUEUE_SIZE)
    sample_counter = multiprocessing.Value("i", 0)
    overflow_counter = multiprocessing.Value("i", 0)

    # Initialize processes with daemon=True
    recorder_process = multiprocessing.Process(
        target=recorder, args=(data_queue, sample_counter, time_sync_manager, overflow_counter)
    )
    recorder_process.daemon = True  # Ensures it will close with main process

    sender_process = multiprocessing.Process(target=sender, args=(data_queue, config, overflow_counter))
    sender_process.daemon = True  # Ensures it will close with main process

    # Start both processes
    recorder_process.start()
    sender_process.start()

    # Set up signal handler
    handler = functools.partial(
        signal_handler, recorder_process, sender_process, time_sync_manager
    )
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    try:
        # Poll both subprocesses. If either dies unexpectedly, exit main
        # with an error so systemd restarts the whole thing. Prior behavior
        # (blocking join on recorder) meant a dead sender could stay dead
        # forever while systemd still thought the service was healthy.
        while True:
            if not recorder_process.is_alive():
                logger.error(
                    f"Recorder subprocess exited (code={recorder_process.exitcode}); "
                    f"failing whole service so systemd restarts it"
                )
                sys.exit(1)
            if not sender_process.is_alive():
                logger.error(
                    f"Sender subprocess exited (code={sender_process.exitcode}); "
                    f"failing whole service so systemd restarts it"
                )
                sys.exit(1)
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, terminating processes...")
        signal_handler(recorder_process, sender_process, time_sync_manager, None, None)
    finally:
        # Stop time sync
        time_sync_manager.stop()

        # Ensure all processes are terminated
        if recorder_process.is_alive():
            recorder_process.terminate()
        if sender_process.is_alive():
            sender_process.terminate()

        recorder_process.join()
        sender_process.join()


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()
