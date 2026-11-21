# PyLoSiSi

**PyLoSiSi** — реализация протокола узкополосного аудиомодема **LoSiSi** (*Low-Signal Simple Interface*) на языке Python. Протокол предназначен для надежной передачи коротких текстовых сообщений и радиолюбительских QSO-пакетов в условиях слабого сигнала и высокого уровня шумов.

## Особенности протокола

* **Модуляция:** CPFSK (непрерывная по фазе многочастотная манипуляция, 64 тона).
* **Параметры сигнала:** частота дискретизации `8000 Гц`, длительность символа `0.8 с`, ортогональный разнос частот `1.25 Гц` (общая полоса сигнала ~80 Гц).
* **Структура пакета:** 15 символов синхропреамбулы + 16 символов кадра (общая длительность передачи `24.8 с`).
* **Формат QSO-кадра (16 символов):**
  * `5 символов` — позывной получателя (`target`)
  * `5 символов` — позывной отправителя (`sender`)
  * `4 символа` — полезная нагрузка / локатор / рапорт (`meta`)
  * `2 символа` — контрольная сумма CRC

## Установка

Базовая установка (генерация и декодирование WAV-файлов и массивов `numpy`):

```bash
pip install pylosisi
```

Установка с поддержкой работы в реальном времени через звуковую карту (`sounddevice`):

```bash
pip install "pylosisi[stream]"
```

## Примеры использования

### 1. Запись и чтение WAV-файлов (Офлайн-режим)

```python
from pylosisi import LoSiSiOfflineEncoder, LoSiSiOfflineDecoder

# Генерация WAV-файла (16-бит, моно, 8000 Гц)
encoder = LoSiSiOfflineEncoder(base_freq=1000.0)
encoder.encode_to_wav(
    filename="qso_message.wav",
    sender="R1ABC",
    target="CQ",
    meta="KO59"
)

# Декодирование из WAV-файла (автопоиск сигнала в полосе 500–2500 Гц)
decoder = LoSiSiOfflineDecoder(search_min_hz=500.0, search_max_hz=2500.0)
packets = decoder.decode_wav("qso_message.wav")

for pkt in packets:
    print(f"Принято: '{pkt['text']}' | Частота: {pkt['freq_hz']} Гц | CRC: {pkt['crc_ok']}")
```

### 2. Тестирование с добавлением шума (AWGN)

```python
from pylosisi import LoSiSiOfflineEncoder, LoSiSiOfflineDecoder

encoder = LoSiSiOfflineEncoder(base_freq=1200.0)
decoder = LoSiSiOfflineDecoder()

# Генерация сигнала с отношением сигнал/шум -10 дБ
noisy_audio = encoder.encode_to_array(
    sender="UA1AA",
    target="R1ABC",
    meta="-10D",
    snr_db=-10.0
)

results = decoder.decode_array(noisy_audio)
print(results)
```

### 3. Передача и прием в реальном времени (Звуковая карта)

*(Требуется установка `pip install "pylosisi[stream]"`)*

```python
import time
from pylosisi import LoSiSiStreamTransmitter, LoSiSiStreamReceiver

# Коллбэк при успешном приеме пакета
def on_packet(packet):
    print(f"\n[ЭФИР] Принят пакет: {packet['text']} (базовая частота {packet['freq_hz']} Гц)")

# Запуск приемника в фоновом потоке
rx = LoSiSiStreamReceiver(on_receive_callback=on_packet, search_min_hz=500.0, search_max_hz=2500.0)
rx.start()

# Передача сообщения
tx = LoSiSiStreamTransmitter(base_freq=1000.0)
tx.transmit_qso(sender="R1ABC", target="CQ", meta="73!", blocking=True)

# Даем приемнику пару секунд на завершение обработки буфера
time.sleep(3)
rx.stop()
```

## Архитектура пакета

* `pylosisi.modem.PyLoSiSi` — математическое ядро: генерация преамбулы, модуляция CPFSK, скользящий БПФ-демодулятор, расчет CRC и симуляция канала с шумом.
* `pylosisi.io` — высокоуровневые обертки для работы с WAV (`LoSiSiOfflineEncoder`, `LoSiSiOfflineDecoder`) и потоковым аудио (`LoSiSiStreamTransmitter`, `LoSiSiStreamReceiver`).

## Лицензия

Проект распространяется под лицензией **MIT**. Подробности приведены в файле [LICENSE](LICENSE).
