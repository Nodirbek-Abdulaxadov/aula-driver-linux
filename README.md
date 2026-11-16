# AULA F108Pro — Linux drayveri

AULA F108Pro (SONiX `0C45:800A`, 2.4G dongle `05AC:024F`) klaviaturasini Linux'da
sozlash uchun GTK4 dasturi. Protokol asl Windows drayveri
(«AULA F108Pro Driver 1.0.0.2», `DeviceDriver.exe`) REA/Ghidra yordamida
teskari muhandislik qilib tiklangan — batafsil: [docs/PROTOCOL.md](docs/PROTOCOL.md)
(sozlama qiymatlari uchun §8, real-vaqt oqimi uchun §9, makros rejimlari uchun §10
oldingi bo'limlardagi taxminlardan ustun).

> «Aula Hub» (va uning web-versiyasi) bu modelni umuman qo'llamaydi — u faqat
> F108Pro**V2** ni taniydi. Shuning uchun u «no device» deydi.

> Bu norasmiy loyiha, AULA bilan aloqasi yo'q. Ishlatish o'z javobgarligingizda.
> Repoda AULA'ning fayllari (dastur, rasm, konfiguratsiya) yo'q — klaviatura
> rasmi dastur tomonidan chiziladi.

## O'rnatish

```bash
./install.sh            # sudo paroli so'raladi (udev qoidasi uchun)
aula-f108               # yoki menyudan «AULA F108Pro»
./install.sh --uninstall
```

Faqat Python 3 + GTK4/libadwaita (`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`)
kerak; boshqa kutubxona yo'q. O'rnatmasdan ishga tushirish:
`python3 -m aula_f108` (bu papkada).

## Imkoniyatlar

| Bo'lim | Nima qiladi | USB | 2.4G |
|---|---|---|---|
| Yorug'lik | 20 ta o'rnatilgan effekt, rang / kamalak, yorqinlik 0–5, tezlik 0–5, yo'nalish | ✅ | ✅ |
| Ranglar | Har bir tugmaga alohida rang (klaviatura xotirasiga), joriy ranglarni o'qish | ✅ | ✅ (o'qish faqat USB) |
| Tugmalar | Asosiy va Fn qatlam: boshqa tugma/kombinatsiya, multimedia, sichqoncha, makros, o'chirish | ✅ | ✅ |
| Makroslar | Yozib olish (kechikishlar bilan), tahrirlash, 100 tagacha | ✅ | ✅ |
| Sozlamalar | Win / Alt+F4 / Alt+Tab bloklash, Fn rejimi, uyqu vaqti, debounce, ekran soati, tiklash | ✅ Win bloki, ekran soati | ✅ Win bloki |
| Batareya | Dongle orqali batareya foizi | — | ✅ |

✅ — klaviaturada tekshirilgan (tugma bosilganda klaviatura yuborgan HID
hisobotlari bilan). Alt+F4 / Alt+Tab bloklash, Fn rejimi, uyqu vaqti va
debounce klaviatura tomonidan qabul qilinadi, lekin ta'siri alohida
tekshirilmagan.

Tugmalar, makroslar va sozlamalarni yozish klaviaturadagi mavjud
jadvalni to'liq almashtiradi.

Klaviatura tugma xaritasi, makros va sozlamalarni qaytarib bera olmaydi, shu
sabab ular kompyuterda saqlanadi: `~/.config/aula-f108/profile.json`.

## Qilinmagan

- Ekranga GIF yuklash (protokoli `docs/PROTOCOL.md` §2.10 da bor).
- Musiqa ritmi rejimi.
- Proshivka yangilash — asl drayverda ham yo'q (alohida dastur), xavfli.

## Tuzilishi

```
aula_f108/hidio.py      hidraw: qurilma topish, feature/output report
aula_f108/protocol.py   F108Pro buyruqlari (USB va 2.4G)
aula_f108/layout.py     tugmalar joylashuvi (assets/layout.json)
aula_f108/gui.py        GTK4 / libadwaita interfeys
70-aula-f108pro.rules   udev qoidasi
```

## Litsenziya

[MIT](LICENSE)
