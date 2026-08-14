# reduzent2026

Distributed percussion/actuator system built on ESP32 hardware.

Each node is an ESP32-C3 with a piezo or solenoid actuator, powered by a
Li-ion battery with a step-up converter. A central controller (ESP32)
sends commands over ESP-NOW using a compact MIDI-like protocol. Node
configuration is done through the parasol web interface.

## Repository layout

```
reduzent2026/
├── src/         Firmware entry points (currently the piezo smoke test)
├── include/     Shared project headers
├── lib/         Shared libraries (future: espnow protocol, drivers)
├── test/        Unit tests
└── platformio.ini
```

## Node roles

- **leaf-piezo** — ESP32-C3 + piezo actuator (current board)
- **leaf-solenoid** — ESP32-C3 + solenoid actuator
- **controller** — ESP32 (non-C3) that sends ESP-NOW commands

See AGENTS.md for build commands and hardware details.
