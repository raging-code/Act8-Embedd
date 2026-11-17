"""Play a WAV file through the machine's own speaker (USB speaker/headphones on the Pi)."""
import shutil
import subprocess
import sys
import threading


class DevicePlayer:
    # first one found on PATH wins
    _LINUX_CMDS = (["aplay", "-q"], ["paplay"], ["pw-play"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"])

    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()
        self.backend = self._detect()

    def _detect(self):
        if sys.platform.startswith("win"):
            return "winsound"
        if sys.platform == "darwin":
            return "afplay" if shutil.which("afplay") else None
        for cmd in self._LINUX_CMDS:
            if shutil.which(cmd[0]):
                return cmd[0]
        return None

    def _command(self):
        if self.backend == "afplay":
            return ["afplay"]
        for cmd in self._LINUX_CMDS:
            if cmd[0] == self.backend:
                return cmd
        return None

    def play(self, path):
        """Start playback (replacing anything already playing). Returns True if started."""
        if self.backend is None:
            return False
        with self._lock:
            self._stop_locked()
            if self.backend == "winsound":
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
                return True
            self._proc = subprocess.Popen(self._command() + [str(path)],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True

    def _stop_locked(self):
        if self.backend == "winsound":
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        elif self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None

    def stop(self):
        with self._lock:
            self._stop_locked()

    def info(self):
        return {"backend": self.backend}
