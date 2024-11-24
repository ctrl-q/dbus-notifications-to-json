import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import dbus
import dbus.mainloop.glib
from dbus.lowlevel import MethodCallMessage, MethodReturnMessage
from gi.repository import GLib

OUTDIR = os.environ["DBUS_TO_JSON_OUTDIR"]

# keys are sender, destination, serial
MESSAGE_CACHE: dict[tuple[int, int, int], dict[str, Any]] = {}


def cache(message: MethodCallMessage):
    MESSAGE_CACHE[
        (message.get_sender(), message.get_destination(), message.get_serial())
    ] = dict(
        zip(
            [
                "app_name",
                "replaces_id",
                "app_icon",
                "summary",
                "body",
                "actions",
                "hints",
                "expire_timeout",
            ],
            message.get_args_list(),
        )
    )


def get_outdir(notification: dict[str, str]) -> Path:
    def slugify(s: str):
        """Adapted from https://docs.djangoproject.com/en/4.1/ref/utils/#django.utils.text.slugify"""
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        s = re.sub(r"[^\w\s-]", "", s.lower())
        return re.sub(r"[-\s]+", "-", s).strip("-_")

    default_outdir = (
        Path(OUTDIR)
        / slugify(notification["app_name"])
        / slugify(notification["summary"])
    )
    try:
        for folder in reversed(
            [default_outdir, *default_outdir.relative_to(OUTDIR).parents]
        ):
            folder = OUTDIR / folder
            if (settings_file := OUTDIR / folder / ".settings.json").exists() and (
                subdir_callback := json.loads(settings_file.read_text()).get(
                    "subdir_callback"
                )
            ):
                subdir = eval(subdir_callback)(notification.copy())
                if subdir:
                    if (
                        folder.resolve()
                        in (outdir := (folder / slugify(str(subdir))).resolve()).parents
                    ):
                        return outdir
                    else:
                        print(f"Error: Subdir must be below {folder}, got {outdir}")
                        return default_outdir
    except Exception as e:
        print("Error:", e, file=sys.stderr)

    return default_outdir


def write_to_file(message: MethodReturnMessage):
    if dict_ := MESSAGE_CACHE.pop(
        (message.get_destination(), message.get_sender(), message.get_reply_serial()),
        {},
    ):
        (notification_id,) = message.get_args_list()
        payload = json.dumps(dict_ | {"id": notification_id})
        # I can't for the life of me figure out how to send a signal
        # using https://dbus.freedesktop.org/doc/dbus-python/tutorial.html#emitting-signals-with-dbus-service-signal
        # the program crashes as soon as it tries to emit the signal
        subprocess.run(
            [
                "gdbus",
                "emit",
                "--session",
                "--signal=com.example.DbusNotificationsToJson.NotificationSent",
                "--object-path=/com/example/DbusNotificationsToJson/notifications",
                payload,
            ]
        )
        outdir = get_outdir(dict_)
        outdir.mkdir(parents=True, exist_ok=True)
        # Now that the notification ID is in the filename, we don't need a JSONL file, but keeping for compatibility
        outfile = outdir / f"{time.strftime('%Y%m%d-%H%M%S')}-{notification_id}.jsonl"
        with outfile.open("a") as f:
            f.write(payload + "\n")
        print(f"Notification written to {outfile}", file=sys.stderr)


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SessionBus()
    dbus.Interface(
        bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"),
        "org.freedesktop.DBus.Monitoring",
    ).BecomeMonitor(
        [
            "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
            "type='method_return'",
        ],
        0,
    )
    bus.add_message_filter(
        lambda _, message: (
            cache(message)
            if isinstance(message, MethodCallMessage)
            else (
                write_to_file(message)
                if isinstance(message, MethodReturnMessage)
                else None
            )
        )
    )

    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
