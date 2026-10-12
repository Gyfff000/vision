"""Pure MicroPython contest state machine; no hardware imports."""
from config import QR_CONFIRM_FRAMES

PHASES = ("RAW1", "PROCESS_PUT1", "PROCESS_GET1", "STORE1",
          "RAW2", "PROCESS_PUT2", "PROCESS_GET2", "STACK2")

def parse_task(raw):
    if not isinstance(raw, str) or len(raw) != 15:
        raise ValueError("BAD_TASK")
    groups = raw.split("+")
    if len(groups) != 4 or any(len(g) != 3 for g in groups):
        raise ValueError("BAD_TASK")
    a, b, c, d = groups
    if (any(ch not in "123456" for ch in a+c) or len(set(a)) != 3 or
        sorted(a) != sorted(c) or sorted(b) != list("123") or sorted(d) != list("123")):
        raise ValueError("BAD_TASK")
    return tuple(tuple(int(ch) for ch in group) for group in groups)

def build_plan(raw):
    a, b, c, d = parse_task(raw)
    stored = dict(zip(a, b))
    plan = []
    for phase in PHASES:
        second = phase.endswith("2")
        colors, slots = (c, d) if second else (a, b)
        for i, color in enumerate(colors):
            if phase.startswith("RAW"):
                mode, profile, slot, action = "COLOR", "RAW", 0, "PICK_LOAD"
            elif phase.startswith("PROCESS_PUT"):
                mode, profile, slot, action = "RING", "PROCESS", slots[i], "PLACE"
            elif phase.startswith("PROCESS_GET"):
                mode, profile, slot, action = "COLOR", "PROCESS", slots[i], "PICK_LOAD"
            elif phase == "STORE1":
                mode, profile, slot, action = "RING", "STORE", slots[i], "PLACE"
            else:
                mode, profile, slot, action = "COLOR", "STACK", stored[color], "STACK"
            plan.append({"step":len(plan), "phase":phase, "color":color, "slot":slot,
                         "mode":mode, "profile":profile, "action":action})
    return plan

class Workflow:
    def __init__(self, session=0):
        self.session = session & 65535
        self.raw, self.token, self.plan = None, 0, []
        self.state, self.step = "SCAN", 0
        self.grabs, self.places = 0, 0
        self.previous, self.streak = None, 0

    def observe(self, raw, crc):
        if self.state != "SCAN":
            return False
        try:
            parse_task(raw)
        except ValueError:
            self.previous, self.streak = None, 0
            return False
        self.streak = self.streak+1 if raw == self.previous else 1
        self.previous = raw
        if self.streak < QR_CONFIRM_FRAMES:
            return False
        self.raw, self.plan = raw, build_plan(raw)
        self.token = (self.session << 16) | crc(raw.encode("ascii"))
        self.state = "WAIT_ACK"
        return True

    def acknowledge(self, token):
        if self.raw is None or token != self.token or self.state == "SCAN":
            raise ValueError("TASK_MISMATCH")
        if self.state == "WAIT_ACK":
            self.state = "RUN"

    def confirm_step(self, token, step):
        if token != self.token or self.raw is None:
            raise ValueError("TASK_MISMATCH")
        if 0 <= step < self.step:  # Lost ACK retry: do not count the action twice.
            return
        if self.state != "RUN" or step != self.step or step >= len(self.plan):
            raise ValueError("STEP_MISMATCH")
        if self.current()["action"] == "PICK_LOAD":
            self.grabs += 1
        else:
            self.places += 1
        self.step += 1
        if self.step == len(self.plan):
            self.state = "RETURN_HOME"

    def complete_home(self, token):
        if token != self.token or self.state not in ("RETURN_HOME", "COMPLETE"):
            raise ValueError("HOME_MISMATCH")
        self.state = "COMPLETE"

    def current(self):
        return self.plan[self.step] if self.raw and self.step < len(self.plan) else None

    def mode(self):
        # Detection starts as soon as a task is known; ACK gates motion, not LCD.
        return self.current()["mode"] if self.state in ("WAIT_ACK", "RUN") else "QR" if self.state == "SCAN" else "IDLE"

    def reset(self):
        self.__init__((self.session+1) & 65535)

    def pause(self):
        if self.state != "PAUSED":
            self.before_pause = self.state
            self.state = "PAUSED"

    def resume(self):
        if self.state == "PAUSED":
            self.state = self.before_pause

    def context(self):
        s = self.current() or {"phase":"NONE", "color":0, "slot":0, "profile":"NONE"}
        return (self.state, self.token, self.step, s["phase"], s["color"], s["slot"], self.mode(), s["profile"], self.grabs, self.places)
