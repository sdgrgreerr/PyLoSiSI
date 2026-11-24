import time
import wave
import threading
import numpy as np
from .modem import PyLoSiSi

try:
    import sounddevice as sd
except ImportError:
    sd = None


class LoSiSiOfflineEncoder:
    """Генерирует аудиосигнал PyLoSiSi в память или WAV-файл."""

    def __init__(self, base_freq: float = 1000.0, fec_level: int = 2):
        self.modem = PyLoSiSi(base_freq=base_freq, fec_level=fec_level)

    def encode_to_array(self, sender: str, target: str, meta: str, snr_db: float = None) -> np.ndarray:
        frame = self.modem.build_qso(sender, target, meta)
        audio = self.modem.modulate(frame)
        if snr_db is not None:
            audio = self.modem.add_awgn_noise(audio, snr_db)
        return audio

    def encode_to_wav(self, filename: str, sender: str, target: str, meta: str, snr_db: float = None):
        audio = self.encode_to_array(sender, target, meta, snr_db=snr_db)
        self.modem.save_wav(filename, audio)


class LoSiSiOfflineDecoder:
    """Декодирует сигналы PyLoSiSi из WAV-файлов или numpy-массивов."""

    def __init__(self, search_min_hz: float = 500.0, search_max_hz: float = 2500.0, fec_level: int = 2):
        self.modem = PyLoSiSi(fec_level=fec_level)
        self.search_min_hz = search_min_hz
        self.search_max_hz = search_max_hz

    def decode_array(self, audio: np.ndarray) -> list:
        return self.modem.demodulate(
            audio,
            search_min_hz=self.search_min_hz,
            search_max_hz=self.search_max_hz
        )

    def decode_wav(self, filename: str) -> list:
        with wave.open(filename, 'r') as wf:
            if wf.getframerate() != self.modem.SAMPLE_RATE:
                raise ValueError(f"Ожидается частота {self.modem.SAMPLE_RATE} Гц, получено {wf.getframerate()} Гц")
            n_frames = wf.getnframes()
            raw_data = wf.readframes(n_frames)
            audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float64) / 32768.0

        return self.decode_array(audio)


class LoSiSiStreamTransmitter:
    """Передает сообщения PyLoSiSi в реальном времени через аудиовыход."""

    def __init__(self, base_freq: float = 1000.0, fec_level: int = 2, device=None):
        if sd is None:
            raise ImportError("Для потоковой работы установите библиотеку: pip install sounddevice")
        self.modem = PyLoSiSi(base_freq=base_freq, fec_level=fec_level)
        self.device = device
        self._is_transmitting = False

    def transmit_qso(self, sender: str, target: str, meta: str, blocking: bool = True):
        frame = self.modem.build_qso(sender, target, meta)
        self.transmit_raw(frame, blocking=blocking)

    def transmit_raw(self, text: str, blocking: bool = True):
        audio = self.modem.modulate(text).astype(np.float32)

        def _play():
            self._is_transmitting = True
            try:
                sd.play(audio, samplerate=self.modem.SAMPLE_RATE, device=self.device)
                sd.wait()
            finally:
                self._is_transmitting = False

        if blocking:
            _play()
        else:
            threading.Thread(target=_play, daemon=True).start()

    def stop(self):
        sd.stop()
        self._is_transmitting = False


class LoSiSiStreamReceiver:
    """Слушает микрофон/трансивер в потоке и вызывает callback при приеме пакета."""

    def __init__(
        self,
        on_receive_callback,
        search_min_hz: float = 500.0,
        search_max_hz: float = 2500.0,
        fec_level: int = 2,
        device=None
    ):
        if sd is None:
            raise ImportError("Для потоковой работы установите библиотеку: pip install sounddevice")
        self.modem = PyLoSiSi(fec_level=fec_level)
        self.on_receive = on_receive_callback
        self.search_min_hz = search_min_hz
        self.search_max_hz = search_max_hz
        self.device = device

        dev_info = sd.query_devices(device, 'input')
        self.hw_samplerate = int(dev_info['default_samplerate'])
        self.decimate_factor = max(1, round(self.hw_samplerate / self.modem.SAMPLE_RATE))

        # Буфер на 45 секунд (с запасом под максимальный fec_level=8 длиной 37.6 сек)
        self.buffer_len = int(self.modem.SAMPLE_RATE * 45.0)
        self.ring_buffer = np.zeros(self.buffer_len, dtype=np.float64)
        self._lock = threading.Lock()
        self._running = False
        self._stream = None
        self._last_decoded_text = None

    def _audio_callback(self, indata, frames, time_info, status):
        raw_samples = indata[:, 0].astype(np.float64)
        if self.decimate_factor > 1:
            samples = raw_samples[::self.decimate_factor]
        else:
            samples = raw_samples

        n = len(samples)
        if n > 0:
            with self._lock:
                self.ring_buffer = np.roll(self.ring_buffer, -n)
                self.ring_buffer[-n:] = samples

    def start(self):
        if self._running:
            return
        self._running = True
        self._stream = sd.InputStream(
            samplerate=self.hw_samplerate,
            channels=1,
            dtype='float32',
            device=self.device,
            callback=self._audio_callback
        )
        self._stream.start()
        threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self):
        while self._running:
            time.sleep(1.6)
            with self._lock:
                snapshot = self.ring_buffer.copy()

            results = self.modem.demodulate(
                snapshot,
                search_min_hz=self.search_min_hz,
                search_max_hz=self.search_max_hz
            )

            for res in results:
                if res["crc_ok"] and res["text"] != self._last_decoded_text:
                    self._last_decoded_text = res["text"]
                    self.on_receive(res)

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
