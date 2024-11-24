# dbus-to-json

Monitors [FreeDesktop Notifications Spec notifications](https://specifications.freedesktop.org/notification-spec/latest/protocol.html#command-notify) and:
1. Writes them to `slugify(<app_name>)/slugify(<summary>)/strftime('%Y%m%d-%H%M%S')-<id>.json`
    1. The subdirectory can be overridden (see #Configuration)
1. Emits a `com.example.DbusNotificationsToJson.NotificationSent` signal with the notification's arguments wrapped in a JSON dictionary

### Configuration

- The top-level storage directory is controlled by the `DBUS_TO_JSON_OUTDIR` environment variable
- A .settings.json file can be placed in any directory, with the following structure

```json5
{
    // (optional) lambda expression taking a notification dict as input, and returning a string or None
    // If the return value is None or "", the default outdir is used instead
    "subdir_callback": "lambda notification: 'some subdirectory'"
}
```

## FAQ

### Why not use more recent dbus libraries?

`dbus-next` was tried and found to not capture every message.

Any switch of library should come with performance tests showing all notifications being captured.