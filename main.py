import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import dbus
import dbus.mainloop.glib
from dbus.lowlevel import MethodCallMessage
from gi.repository import GLib

OUTDIR = os.environ["DBUS_TO_JSON_OUTDIR"]


def write_to_file(message: MethodCallMessage):
    def slugify(s: str):
        """Adapted from https://docs.djangoproject.com/en/4.1/ref/utils/#django.utils.text.slugify"""
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        s = re.sub(r"[^\w\s-]", "", s.lower())
        return re.sub(r"[-\s]+", "-", s).strip("-_")

    dict_ = dict(
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
    outdir = Path(OUTDIR) / slugify(dict_["app_name"])
    outdir.mkdir(parents=True, exist_ok=True)
    outfile = outdir / f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(dict_['summary'])}.json"
    with outfile.open("w") as f:
        json.dump(dict_, f)

    print(f"Notification written to {outfile}", file=sys.stderr)


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SessionBus()
    dbus.Interface(
        bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"),
        "org.freedesktop.DBus.Monitoring",
    ).BecomeMonitor(
        [
            "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"
        ],
        0,
    )
    bus.add_message_filter(
        lambda _, message: (
            write_to_file(message) if isinstance(message, MethodCallMessage) else None
        )
    )

    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
