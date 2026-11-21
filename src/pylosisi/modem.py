import wave
import zlib
import numpy as np


class PyLoSiSi:
    """Ядро протокола связи LoSiSi (Low-Signal Simple Interface)."""

    SAMPLE_RATE = 8000
    SYMBOL_DURATION = 0.8  # 0.8 сек на символ (из комментария: 1.6 сек = 2 символа)
    FRAME_LEN = 16         # Длина полезной нагрузки в символах
    ALPHABET = "0123456789- abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def __init__(self, base_freq: float = 1000.0):
        self.base_freq = base_freq
        self.tone_spacing = 1.0 / self.SYMBOL_DURATION  # Ортогональный шаг 1.25 Гц

    def _calc_crc(self, payload: str) -> str:
        """Вычисляет 2-символьную контрольную сумму."""
        crc = zlib.crc32(payload.encode("ascii")) & 0xFF
        c1 = self.ALPHABET[crc % len(self.ALPHABET)]
        c2 = self.ALPHABET[(crc // len(self.ALPHABET)) % len(self.ALPHABET)]
        return c1 + c2

    def build_qso(self, sender: str, target: str, meta: str) -> str:
        """Формирует стандартный 16-символьный QSO-кадр с контрольной суммой."""
        raw = f"{target[:5]:<5}{sender[:5]:<5}{meta[:4]:<4}".upper()
        sanitized = "".join(c if c in self.ALPHABET else " " for c in raw)
        return sanitized + self._calc_crc(sanitized)

    def modulate(self, text: str) -> np.ndarray:
        """Преобразует 16-символьную строку в аудиосигнал с синхропреамбулой."""
        if len(text) != self.FRAME_LEN:
            text = f"{text:<{self.FRAME_LEN}}"[:self.FRAME_LEN].upper()

        # Преамбула (15 символов синхронизации) + 16 символов данных = 31 символ (24.8 сек)
        sync_tones = [0, 4, 8, 12, 16] * 3
        data_tones = [self.ALPHABET.index(c) if c in self.ALPHABET else 0 for c in text]
        tones = sync_tones + data_tones

        samples_per_sym = int(self.SAMPLE_RATE * self.SYMBOL_DURATION)
        t_sym = np.arange(samples_per_sym) / self.SAMPLE_RATE
        signal = []

        phase = 0.0
        for tone in tones:
            freq = self.base_freq + tone * self.tone_spacing
            # Непрерывная по фазе частотная манипуляция (CPFSK)
            inst_phase = phase + 2 * np.pi * freq * t_sym
            signal.append(np.sin(inst_phase))
            phase = inst_phase[-1] % (2 * np.pi)

        audio = np.concatenate(signal) * 0.8
        return audio.astype(np.float64)

    def demodulate(
        self, audio: np.ndarray, search_min_hz: float = 500.0, search_max_hz: float = 2500.0
    ) -> list:
        """Ищет синхропреамбулу в полосе частот и декодирует кадр."""
        samples_per_sym = int(self.SAMPLE_RATE * self.SYMBOL_DURATION)
        total_symbols = 31
        packet_samples = samples_per_sym * total_symbols

        if len(audio) < packet_samples:
            return []

        results = []
        # Упрощенный поиск по скользящему окну FFT для каркаса пакета
        step = samples_per_sym // 2
        freqs = np.fft.rfftfreq(samples_per_sym, 1.0 / self.SAMPLE_RATE)
        band_mask = (freqs >= search_min_hz) & (freqs <= search_max_hz)

        for start in range(0, len(audio) - packet_samples + 1, step):
            segment = audio[start : start + packet_samples]
            detected_freqs = []

            for i in range(total_symbols):
                sym_chunk = segment[i * samples_per_sym : (i + 1) * samples_per_sym]
                spectrum = np.abs(np.fft.rfft(sym_chunk * np.hanning(samples_per_sym)))
                valid_spectrum = np.where(band_mask, spectrum, 0)
                peak_idx = np.argmax(valid_spectrum)
                detected_freqs.append(freqs[peak_idx])

            base_est = detected_freqs[0]
            # Проверка соответствия первых 5 тонов преамбуле [0, 4, 8, 12, 16]
            expected_sync = [base_est + k * self.tone_spacing for k in [0, 4, 8, 12, 16]]
            if all(abs(detected_freqs[i] - expected_sync[i]) < 2.0 for i in range(5)):
                chars = []
                for f in detected_freqs[15:]:
                    idx = int(round((f - base_est) / self.tone_spacing))
                    if 0 <= idx < len(self.ALPHABET):
                        chars.append(self.ALPHABET[idx])
                    else:
                        chars.append(" ")

                full_text = "".join(chars)
                payload, crc = full_text[:14], full_text[14:]
                crc_ok = self._calc_crc(payload) == crc

                if crc_ok:
                    results.append({
                        "text": full_text,
                        "crc_ok": True,
                        "freq_hz": round(float(base_est), 1),
                    })
                    break

        return results

    def add_awgn_noise(self, audio: np.ndarray, snr_db: float) -> np.ndarray:
        """Добавляет аддитивный белый гауссовский шум (AWGN) с заданным SNR."""
        sig_power = np.mean(audio ** 2)
        snr_linear = 10 ** (snr_db / 10.0)
        noise_power = sig_power / snr_linear
        noise = np.random.normal(0, np.sqrt(noise_power), size=audio.shape)
        return np.clip(audio + noise, -1.0, 1.0)

    def save_wav(self, filename: str, audio: np.ndarray):
        """Сохраняет массив float64 в 16-битный моно WAV."""
        pcm = np.int16(np.clip(audio, -1.0, 1.0) * 32767)
        with wave.open(filename, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
