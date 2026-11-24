# PyLoSiSi

**PyLoSiSi** is a Python implementation of the narrowband **LoSiSi** (*Low-Signal Simple Interface*) audio modem protocol for weak-signal and high-noise amateur radio communication.

## What's New in v0.1.1

- **Forward Error Correction (FEC):** Reed-Solomon over GF(2⁶) with configurable `fec_level` (0–8), recovering up to 8 corrupted symbols per packet.
- **Dynamic Packet Duration:** Frame length scales dynamically based on parity symbols (from 24.8s up to 37.6s).
- **Enhanced Receiver Buffer:** Extended ring buffer capacity to 45s for real-time decoding at high FEC levels.
- **FT8-Style GUI Terminal:** Added a Tkinter transceiver application with live waterfall spectrum (500–2500 Hz), dual-pane logs, macros, and offline WAV tools.

## Protocol & Installation

- **Modulation:** CPFSK (64 tones), 8000 Hz sample rate, 0.8s symbol duration, 1.25 Hz tone spacing (~80 Hz bandwidth).
- **Installation:** 
  ```bash
  pip install pylosisi              # Core / WAV / NumPy
  pip install "pylosisi[stream]"    # Real-time soundcard streaming
  pip install matplotlib numpy      # GUI terminal support
  ```

## Usage Examples

### Offline WAV Processing
```python
from pylosisi import LoSiSiOfflineEncoder, LoSiSiOfflineDecoder

encoder = LoSiSiOfflineEncoder(base_freq=1000.0, fec_level=2)
encoder.encode_to_wav("qso_message.wav", sender="R1ABC", target="CQ", meta="KO59")

decoder = LoSiSiOfflineDecoder(search_min_hz=500.0, search_max_hz=2500.0, fec_level=2)
for pkt in decoder.decode_wav("qso_message.wav"):
    print(f"Received: '{pkt['text']}' | Freq: {pkt['freq_hz']} Hz | CRC: {pkt['crc_ok']}")
```

*(For complete usage details, AWGN noise testing, streaming examples, and package architecture, please refer to the source repository at [https://github.com/sdgrgreerr/PyLoSiSI](https://github.com/sdgrgreerr/PyLoSiSI)).*

## License
MIT License.
