"""Buzzer on a Raspberry Pi GPIO pin (gpiozero).  Falls back to a simulated buzzer
on a PC or when GPIO is unavailable, so the same code runs everywhere.

Wiring (active buzzer):  buzzer (+)  ->  GPIO18 (physical pin 12)
                         buzzer (-)  ->  GND    (physical pin 14)
"""
import time


class Buzzer:
    def __init__(self, pin=18):
        self.pin = pin
        self.mode = "simulated"
        self.reason = None
        self.last_alert = None      # monotonic timestamp
        self.alerts = 0
        self._dev = None
        try:
            from gpiozero import Buzzer as GZBuzzer
            self._dev = GZBuzzer(pin)
            self.mode = "gpio"
        except Exception as exc:  # noqa: BLE001 - no GPIO on PCs
            self.reason = f"{type(exc).__name__}: {exc}"

    def alert(self, beeps=3, on=0.18, off=0.12):
        """Non-blocking beep pattern."""
        self.last_alert = time.monotonic()
        self.alerts += 1
        if self._dev is not None:
            try:
                self._dev.beep(on_time=on, off_time=off, n=beeps, background=True)
            except Exception as exc:  # noqa: BLE001
                self.reason = f"{type(exc).__name__}: {exc}"
        else:
            print(f"[buzzer] (simulated) BZZT x{beeps}", flush=True)

    def info(self):
        age = None if self.last_alert is None else round(time.monotonic() - self.last_alert, 1)
        return {"mode": self.mode, "pin": self.pin, "reason": self.reason,
                "alerts": self.alerts, "last_alert_age": age}

    def close(self):
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:  # noqa: BLE001
                pass
