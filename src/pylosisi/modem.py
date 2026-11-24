import wave
import zlib
import numpy as np


class ReedSolomonGF64:
    """Кодек Рида-Соломона над полем Галуа GF(2^6) для 64-символьного алфавита."""

    PRIM_POLY = 0b1000011  # x^6 + x + 1

    def __init__(self):
        self.exp = [0] * 128
        self.log = [0] * 64
        x = 1
        for i in range(63):
            self.exp[i] = x
            self.log[x] = i
            x <<= 1
            if x & 64:
                x ^= self.PRIM_POLY
        for i in range(63, 128):
            self.exp[i] = self.exp[i - 63]

    def _mul(self, a: int, b: int) -> int:
        if a == 0 or b == 0:
            return 0
        return self.exp[self.log[a] + self.log[b]]

    def _div(self, a: int, b: int) -> int:
        if b == 0:
            raise ZeroDivisionError()
        if a == 0:
            return 0
        return self.exp[(self.log[a] - self.log[b]) % 63]

    def _poly_mul(self, p: list, q: list) -> list:
        res = [0] * (len(p) + len(q) - 1)
        for j, q_val in enumerate(q):
            for i, p_val in enumerate(p):
                res[i + j] ^= self._mul(p_val, q_val)
        return res

    def _poly_eval(self, poly: list, x: int) -> int:
        y = poly[0]
        for coeff in poly[1:]:
            y = self._mul(y, x) ^ coeff
        return y

    def _generator_poly(self, nsym: int) -> list:
        g = [1]
        for i in range(nsym):
            g = self._poly_mul(g, [1, self.exp[i]])
        return g

    def encode(self, msg: list, nsym: int) -> list:
        if nsym == 0:
            return list(msg)
        gen = self._generator_poly(nsym)
        res = list(msg) + [0] * nsym
        for i in range(len(msg)):
            coef = res[i]
            if coef != 0:
                for j in range(1, len(gen)):
                    res[i + j] ^= self._mul(gen[j], coef)
        return list(msg) + res[len(msg):]

    def decode(self, msg_in: list, nsym: int):
        """Возвращает (исправленные_данные, количество_исправленных_ошибок) или (None, -1)."""
        if nsym == 0:
            return list(msg_in), 0

        msg = list(msg_in)
        synd = [self._poly_eval(msg, self.exp[i]) for i in range(nsym)]
        if max(synd) == 0:
            return msg[:-nsym], 0

        # Алгоритм Берлекэмпа-Месси для поиска локаторов ошибок
        err_loc = [1]
        old_loc = [1]
        for i in range(nsym):
            delta = synd[i]
            for j in range(1, len(err_loc)):
                delta ^= self._mul(err_loc[-(j + 1)], synd[i - j])
            old_loc = old_loc + [0]
            if delta != 0:
                if len(old_loc) > len(err_loc):
                    new_loc = [self._mul(x, delta) for x in old_loc]
                    old_loc = [self._mul(x, self._div(1, delta)) for x in err_loc]
                    err_loc = new_loc
                scale = [self._mul(x, delta) for x in old_loc]
                err_loc = [a ^ b for a, b in zip(err_loc, scale)]

        errs = len(err_loc) - 1
        if errs * 2 > nsym:
            return None, -1

        # Поиск позиций ошибок (поиск Ченя)
        err_pos = []
        n = len(msg)
        for i in range(n):
            if self._poly_eval(err_loc, self.exp[(63 - (n - 1 - i)) % 63]) == 0:
                err_pos.append(i)

        if len(err_pos) != errs:
            return None, -1

        # Вычисление величин ошибок (алгоритм Форни)
        err_eval = self._poly_mul(synd[::-1], err_loc)[-nsym:]
        err_loc_prime = []
        for idx, c in enumerate(err_loc[:-1]):
            power = len(err_loc) - 1 - idx
            err_loc_prime.append(c if power % 2 == 1 else 0)

        for pos in err_pos:
            x_inv = self.exp[(63 - (n - 1 - pos)) % 63]
            y = self._poly_eval(err_eval, x_inv)
            denom = self._poly_eval(err_loc_prime, x_inv)
            if denom == 0:
                return None, -1
            msg[pos] ^= self._div(y, denom)

        # Финальная проверка синдромов после исправления
        if max(self._poly_eval(msg, self.exp[i]) for i in range(nsym)) != 0:
            return None, -1

        return msg[:-nsym], errs


class PyLoSiSi:
    """Ядро протокола связи LoSiSi (Low-Signal Simple Interface) с настраиваемым FEC."""

    SAMPLE_RATE = 8000
    SYMBOL_DURATION = 0.8
    FRAME_LEN = 16
    ALPHABET = "0123456789- abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def __init__(self, base_freq: float = 1000.0, fec_level: int = 2):
        """
        fec_level: уровень коррекции ошибок от 0 до 8.
        Исправляет до `fec_level` поврежденных символов, добавляя `fec_level * 2` проверочных символов.
        0 = без коррекции (16 симв. данных)
        1 = базовая (18 симв., исправляет 1 символ / 6 бит)
        2 = стандартная (20 симв., исправляет 2 символа / 12 бит)
        8 = максимальная (32 симв., удвоение кадра, исправляет 8 символов / 48 бит)
        """
        if not (0 <= fec_level <= 8):
            raise ValueError("fec_level должен быть в диапазоне от 0 до 8")
        self.base_freq = base_freq
        self.fec_level = fec_level
        self.nsym = fec_level * 2
        self.tone_spacing = 1.0 / self.SYMBOL_DURATION
        self.rs = ReedSolomonGF64()

    def _calc_crc(self, payload: str) -> str:
        crc = zlib.crc32(payload.encode("ascii")) & 0xFF
        c1 = self.ALPHABET[crc % len(self.ALPHABET)]
        c2 = self.ALPHABET[(crc // len(self.ALPHABET)) % len(self.ALPHABET)]
        return c1 + c2

    def build_qso(self, sender: str, target: str, meta: str) -> str:
        raw = f"{target[:5]:<5}{sender[:5]:<5}{meta[:4]:<4}".upper()
        sanitized = "".join(c if c in self.ALPHABET else " " for c in raw)
        return sanitized + self._calc_crc(sanitized)

    def modulate(self, text: str) -> np.ndarray:
        if len(text) != self.FRAME_LEN:
            text = f"{text:<{self.FRAME_LEN}}"[:self.FRAME_LEN].upper()

        sync_tones = [0, 4, 8, 12, 16] * 3
        raw_tones = [self.ALPHABET.index(c) if c in self.ALPHABET else 0 for c in text]

        # Кодирование Рида-Соломона добавляет self.nsym проверочных символов
        data_tones = self.rs.encode(raw_tones, self.nsym)
        tones = sync_tones + data_tones

        samples_per_sym = int(self.SAMPLE_RATE * self.SYMBOL_DURATION)
        t_sym = np.arange(samples_per_sym) / self.SAMPLE_RATE
        signal = []

        phase = 0.0
        for tone in tones:
            freq = self.base_freq + tone * self.tone_spacing
            inst_phase = phase + 2 * np.pi * freq * t_sym
            signal.append(np.sin(inst_phase))
            phase = inst_phase[-1] % (2 * np.pi)

        audio = np.concatenate(signal) * 0.8
        return audio.astype(np.float64)

    def demodulate(
        self, audio: np.ndarray, search_min_hz: float = 500.0, search_max_hz: float = 2500.0
    ) -> list:
        samples_per_sym = int(self.SAMPLE_RATE * self.SYMBOL_DURATION)
        total_symbols = 15 + self.FRAME_LEN + self.nsym
        packet_samples = samples_per_sym * total_symbols

        if len(audio) < packet_samples:
            return []

        results = []
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
            expected_sync = [base_est + k * self.tone_spacing for k in [0, 4, 8, 12, 16]]

            if all(abs(detected_freqs[i] - expected_sync[i]) < 2.0 for i in range(5)):
                raw_tones = []
                for f in detected_freqs[15:]:
                    idx = int(round((f - base_est) / self.tone_spacing))
                    # Ограничиваем индекс рамками алфавита, чтобы FEC мог исправить выброс
                    idx = max(0, min(len(self.ALPHABET) - 1, idx))
                    raw_tones.append(idx)

                corrected_tones, fixed_errors = self.rs.decode(raw_tones, self.nsym)
                if corrected_tones is None:
                    continue

                full_text = "".join(self.ALPHABET[idx] for idx in corrected_tones)
                payload, crc = full_text[:14], full_text[14:]
                crc_ok = self._calc_crc(payload) == crc

                if crc_ok:
                    results.append({
                        "text": full_text,
                        "crc_ok": True,
                        "freq_hz": round(float(base_est), 1),
                        "fec_fixed": fixed_errors,  # Количество исправленных символов
                    })
                    break

        return results

    def add_awgn_noise(self, audio: np.ndarray, snr_db: float) -> np.ndarray:
        sig_power = np.mean(audio ** 2)
        snr_linear = 10 ** (snr_db / 10.0)
        noise_power = sig_power / snr_linear
        noise = np.random.normal(0, np.sqrt(noise_power), size=audio.shape)
        return np.clip(audio + noise, -1.0, 1.0)

    def save_wav(self, filename: str, audio: np.ndarray):
        pcm = np.int16(np.clip(audio, -1.0, 1.0) * 32767)
        with wave.open(filename, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
