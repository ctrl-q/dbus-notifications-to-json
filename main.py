import base64
import json
import os
import pickle
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import dbus
import dbus.mainloop.glib
import dbus.service
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


def to_pickle(payload: dict[str, Any]) -> bytes:
    def to_native_type(x: Any) -> Any:
        match x:
            case dbus.String():
                return str(x)
            case dbus.Boolean():
                return bool(x)
            case (
                dbus.Byte()
                | dbus.UInt16()
                | dbus.UInt32()
                | dbus.Int64()
                | dbus.Int16()
                | dbus.Int32()
            ):
                return int(x)
            case dbus.Double():
                return float(x)
            case dbus.ObjectPath():
                return str(x)
            case dbus.Array():
                if x.signature == dbus.Signature("y"):
                    return bytearray(x)
                else:
                    return [to_native_type(value) for value in x]
            case dbus.Dictionary():
                new_data = {}
                for key in x:
                    new_data[to_native_type(key)] = to_native_type(x[key])
                return new_data
            case _:
                return x

    return pickle.dumps(dict(zip(payload, map(to_native_type, payload.values()))))


def emit_signal():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    class NotificationSent(dbus.service.Object):
        @dbus.service.signal(
            dbus_interface="com.example.DbusNotificationsToJson",
            signature="s",
        )
        def NotificationSent(self, base64_encoded_args: str):
            pass

    NotificationSent(
        dbus.SessionBus(),
        "/com/example/DbusNotificationsToJson/notifications",
    ).NotificationSent(base64.b64encode(sys.stdin.buffer.read()).decode())


def write_to_file(message: MethodReturnMessage):
    if dict_ := MESSAGE_CACHE.pop(
        (message.get_destination(), message.get_sender(), message.get_reply_serial()),
        {},
    ):
        (notification_id,) = message.get_args_list()
        outdir = get_outdir(dict_)
        outdir.mkdir(parents=True, exist_ok=True)
        outfile = outdir / f"{time.strftime('%Y%m%d-%H%M%S')}-{notification_id}.json"

        payload = dict_ | {
            "id": notification_id,
            "path": str(outfile),
        }

        # I can't for the life of me figure out how to send a signal
        # within the same event loop
        # the program crashes as soon as it tries to emit the signal
        try:
            # I can't figure out how to pass list (the actions) and dict (the hints) args to notification-tray's signal receiver, so I'll base64-encode a pickle dump of the args
            subprocess.run(
                ["dbus-to-json", "emit"],
                input=to_pickle(payload),
            )

        except Exception as e:
            print("Error:", e, file=sys.stderr)
        with outfile.open("w") as f:
            json.dump(payload, f)
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
    if len(sys.argv) > 1 and sys.argv[-1] == "emit":
        emit_signal()
    else:
        main()
