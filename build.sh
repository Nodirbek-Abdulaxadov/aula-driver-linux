#!/usr/bin/env bash
# Build release files into dist/:
#   aula-f108_<version>_all.deb          — Debian / Ubuntu package
#   aula-driver-linux-<version>.tar.gz   — source archive (use ./install.sh)
#   SHA256SUMS
set -euo pipefail
cd "$(dirname "$0")"

NAME=aula-f108
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' aula_f108/__init__.py)
MAINTAINER="Nodirbek-Abdulaxadov <66748319+Nodirbek-Abdulaxadov@users.noreply.github.com>"
HOMEPAGE=https://github.com/Nodirbek-Abdulaxadov/aula-driver-linux
OUT=dist
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
rm -rf "$OUT"
mkdir -p "$OUT"

# ---------------------------------------------------------------- .deb
PKG="$BUILD/${NAME}_${VERSION}_all"
mkdir -p "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/lib/python3/dist-packages" \
         "$PKG/usr/lib/udev/rules.d" "$PKG/usr/share/applications" "$PKG/usr/share/doc/$NAME"

cp -r aula_f108 "$PKG/usr/lib/python3/dist-packages/"
find "$PKG" -name __pycache__ -prune -exec rm -rf {} +
install -m 0644 70-aula-f108pro.rules "$PKG/usr/lib/udev/rules.d/"
install -m 0644 LICENSE "$PKG/usr/share/doc/$NAME/copyright"
install -m 0644 README.md docs/PROTOCOL.md "$PKG/usr/share/doc/$NAME/"

cat > "$PKG/usr/bin/aula-f108" <<'EOF'
#!/bin/sh
exec python3 -m aula_f108 "$@"
EOF
chmod 0755 "$PKG/usr/bin/aula-f108"

cat > "$PKG/usr/share/applications/uz.local.AulaF108.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=AULA F108Pro
Comment=AULA F108Pro klaviatura sozlamalari (yorug'lik, tugmalar, makroslar, musiqa)
Exec=aula-f108
Icon=input-keyboard
Terminal=false
Categories=Settings;HardwareSettings;
StartupWMClass=uz.local.AulaF108
EOF

cat > "$PKG/DEBIAN/control" <<EOF
Package: $NAME
Version: $VERSION
Architecture: all
Maintainer: $MAINTAINER
Installed-Size: $(du -sk "$PKG/usr" | cut -f1)
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0 (>= 4.10), gir1.2-adw-1 (>= 1.6)
Recommends: pipewire-bin
Section: utils
Priority: optional
Homepage: $HOMEPAGE
Description: Unofficial configuration tool for the AULA F108Pro keyboard
 GTK4 / libadwaita app for the AULA F108Pro (USB 0C45:800A, 2.4G dongle
 05AC:024F): lighting effects, per-key colours, key remapping (main and Fn
 layer), macros, settings, clock sync and music rhythm mode.
 Includes a udev rule that gives the logged-in user access to the keyboard.
EOF

for script in postinst postrm; do
    cat > "$PKG/DEBIAN/$script" <<'EOF'
#!/bin/sh
set -e
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=hidraw || true
fi
EOF
    chmod 0755 "$PKG/DEBIAN/$script"
done

find "$PKG" -type d -exec chmod 0755 {} +
find "$PKG/usr" -type f -exec chmod 0644 {} +
chmod 0755 "$PKG/usr/bin/aula-f108"
dpkg-deb --root-owner-group --build "$PKG" "$OUT/" >/dev/null

# ---------------------------------------------------------------- source archive
git archive --format=tar.gz --prefix="aula-driver-linux-$VERSION/" \
    -o "$OUT/aula-driver-linux-$VERSION.tar.gz" HEAD

(cd "$OUT" && sha256sum -- * > SHA256SUMS)
ls -l "$OUT"
