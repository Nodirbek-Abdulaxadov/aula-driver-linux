#!/usr/bin/env bash
# AULA F108Pro Linux drayverini o'rnatish / o'chirish.
#   ./install.sh            — o'rnatish
#   ./install.sh --uninstall — o'chirish
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/aula-f108"
BIN="$HOME/.local/bin/aula-f108"
DESKTOP="$HOME/.local/share/applications/aula-f108.desktop"
RULE=/etc/udev/rules.d/70-aula-f108pro.rules

reload_udev() {
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=hidraw
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -rf "$DEST" "$BIN" "$DESKTOP"
    if [[ -f "$RULE" ]]; then
        sudo rm -f "$RULE"
        reload_udev
    fi
    echo "O'chirildi. (Profil saqlanib qoldi: ~/.config/aula-f108)"
    exit 0
fi

python3 -c 'import gi; gi.require_version("Gtk","4.0"); gi.require_version("Adw","1")' 2>/dev/null || {
    echo "GTK4/libadwaita uchun Python kutubxonalari kerak:"
    echo "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
    exit 1
}

echo "1/3  udev qoidasi (klaviaturaga sudo'siz kirish uchun)…"
sudo install -m 0644 "$SRC/70-aula-f108pro.rules" "$RULE"
reload_udev

echo "2/3  Dastur fayllari → $DEST"
rm -rf "$DEST"
mkdir -p "$DEST" "$(dirname "$BIN")" "$(dirname "$DESKTOP")"
cp -r "$SRC/aula_f108" "$DEST/"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +

cat > "$BIN" <<EOF
#!/bin/sh
export PYTHONPATH="$DEST\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m aula_f108 "\$@"
EOF
chmod +x "$BIN"

echo "3/3  Menyu yorlig'i…"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=AULA F108Pro
Comment=AULA F108Pro klaviatura sozlamalari (yorug'lik, tugmalar, makroslar)
Exec=$BIN
Icon=input-keyboard
Terminal=false
Categories=Settings;HardwareSettings;
StartupWMClass=uz.local.AulaF108
EOF
update-desktop-database "$(dirname "$DESKTOP")" 2>/dev/null || true

echo
echo "Tayyor. Ilovalar menyusidan «AULA F108Pro» ni oching yoki terminalda: aula-f108"
echo "Dongle ishlatsangiz, uni bir marta chiqarib qayta ulang."
