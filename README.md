SpectreX360 hacks
===========================

A python3 (not yet daemon) script to enhance user experience on HP Spectre x360 under Ubuntu 16.10.


Dependencies
---------------------------
- Python 3
- [pydbus](https://github.com/LEW21/pydbus/blob/master/README.rst) (install through pip)
- python-gi (GLib bindings)
- inotifyx (with [python 3 compat patches](https://bugs.launchpad.net/inotifyx/+bug/1006053))

The script uses:
- [ScreenToolsSysIndicator](https://github.com/okaresz/ScreenToolsSysIndicator)
- xrandr, xinput
- dconf
- Onboard (the default on-screen-keyboard in Ubuntu Unity)

NOTES
----------------------------

### Python D-Bus
https://dbus.freedesktop.org/doc/dbus-python/doc/tutorial.html#receiving-signals
https://github.com/LEW21/pydbus/blob/master/README.rst

nice summary about understanding dbus-monitor output and DBus messages: http://askubuntu.com/a/38796


TODO
----------------
- move more stuff to Config (font scaling values, etc...)
- demonize with python-daemon
    - http://stackoverflow.com/questions/473620/how-do-you-create-a-daemon-in-python
    - http://stackoverflow.com/questions/13106221/how-do-i-set-up-a-daemon-with-python-daemon
- do not switch if already in that mode
- install to ~/.confing/autostart/desktop_file.desktop (would be nicer to read XDG CONFIG DIRS)
    - sys wide default is /usr/share/gnome/autostart/
- vbtn event file could be read binary, and figure out what data means what (insetad of reading syslog...)

