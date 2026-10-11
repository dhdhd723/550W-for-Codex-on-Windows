from dataclasses import dataclass


@dataclass
class Gate:
    """A skip releases only the animation gate, never the window gate."""
    animation_done: bool = False
    window_ready: bool = False
    exiting: bool = False
    failed: bool = False

    def can_exit(self) -> bool:
        return self.animation_done and self.window_ready and not self.exiting and not self.failed

    def begin_exit(self) -> bool:
        if not self.can_exit():
            return False
        self.exiting = True
        return True
