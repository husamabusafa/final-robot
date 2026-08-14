"""Minimal wake-up test for the wireless Reachy Mini.

Runs entirely on the robot's Raspberry Pi -- no camera, no GUI, no YOLO,
no Gemini. Just connects to the daemon, wakes the motors, does a tiny
head motion so you can see it's alive, then puts it back to sleep.

Deploy & run (from your Mac):
    scp wake_up.py pollen@reachy-mini.local:/home/pollen/
    ssh pollen@reachy-mini.local
    source /venvs/apps_venv/bin/activate
    python /home/pollen/wake_up.py
"""
from __future__ import annotations

import sys
import time

from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose


def main() -> int:
    print("Connecting to Reachy Mini daemon...")
    try:
        mini = ReachyMini()
    except Exception as exc:
        print(f"Could not connect to the daemon: {exc}", file=sys.stderr)
        print("Is the robot powered on and on the same Wi-Fi network?", file=sys.stderr)
        return 1

    with mini:
        print("Connected!")

        print("Enabling motors (torque on)...")
        mini.enable_motors()
        time.sleep(0.5)

        print("Waking up (head lifts + sound)...")
        mini.wake_up()
        time.sleep(1.5)

        print("Nodding the head up a little...")
        mini.goto_target(
            head=create_head_pose(z=10, mm=True),  # ~10 mm up
            duration=1.0,
        )
        time.sleep(1.2)

        print("Returning to center...")
        mini.goto_target(
            head=create_head_pose(z=0, mm=True),
            duration=1.0,
        )
        time.sleep(1.2)

        print("Wiggling antennas once...")
        mini.goto_target(antennas=[0.4, -0.4], duration=0.4)
        mini.goto_target(antennas=[-0.4, 0.4], duration=0.4)
        mini.goto_target(antennas=[0.0, 0.0], duration=0.4)
        time.sleep(0.6)

        print("Going back to sleep...")
        mini.goto_sleep()
        time.sleep(1.0)

    print("Done. If the head moved and the antennas wiggled, the robot is good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
